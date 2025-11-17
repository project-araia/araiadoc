import asyncio
import csv
import json
from pathlib import Path

import click
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from semanticscholar import AsyncSemanticScholar

from climpdfgetter.schema import ParsedDocumentSchema
from climpdfgetter.utils import _collect_from_path, _prep_output_dir


@click.command()
@click.argument("input_file", nargs=1, type=click.Path(exists=True))
@click.option("--input_format", "-i", nargs=1, type=click.Choice(["csv", "checkpoint", "pes2o"]), default="checkpoint")
@click.option("--output_format", "-o", nargs=1, type=click.Choice(["metadata", "pdf"]), default="metadata")
@click.option("-nproc", "-n", nargs=1, type=click.INT)
@click.option("-nchunks", "-c", nargs=1, type=click.INT)
def complete_semantic_scholar(input_csv: Path, input_format: str, output_format: str, nproc: int, nchunks: int):
    """
    Given an input file or directory, containing either:
        1. A CSV with the following columns: `lineno,abstract,score,year,field,title,paper_id,authors`
        2. A `.json` file containing a list of semantic scholar corpus IDs
        3. A directory containing multiple subdirectories of pes2o files

    Download either:
        1. PDFs from Semantic Scholar
        2. Metadata from Semantic Scholar

    and match them with the input data.
    """

    async def _get_document(paper_id, semaphore, asch):
        async with semaphore:
            return await asch.get_paper("CorpusID:" + str(paper_id))

    async def _complete_semantic_scholar(
        chunk_idx, data_chunk, output_dir, progress, checkpoint_data, lock, semaphore, output_format
    ):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        asch = AsyncSemanticScholar()

        if input_format == "csv":
            work_tasks = [asyncio.create_task(_get_document(doc[6], semaphore, asch)) for doc in data_chunk]
        elif input_format == "checkpoint":
            work_tasks = [asyncio.create_task(_get_document(doc, semaphore, asch)) for doc in data_chunk]
        elif input_format == "pes2o":
            stems = [i.stem for i in data_chunk]
            work_tasks = [asyncio.create_task(_get_document(stem, semaphore, asch)) for stem in stems]

        for paper_task in asyncio.as_completed(work_tasks):
            try:
                paper = await paper_task

                if paper is None:
                    continue

                if output_format == "pdf":
                    if not paper["isOpenAccess"]:
                        continue

                    if paper["openAccessPdf"]["status"] != "GOLD":  # pdf likely undownloadable
                        continue

                    pdf_url = paper["openAccessPdf"]["url"]
                    pdf_name = paper["corpusId"]
                    pdf_path = subdir / Path(str(pdf_name) + ".pdf")
                    if not pdf_path.exists() and pdf_name not in checkpoint_data:
                        r = requests.get(pdf_url, stream=True, timeout=10)
                        r.raise_for_status()
                        with pdf_path.open("wb") as f:
                            f.write(r.content)

                elif output_format == "metadata":

                    if input_format == "pes2o":
                        # TODO: Associate metadata from SemanticScholar with input pes2o dataset
                        schema = ParsedDocumentSchema(
                            source="Semantic Scholar",
                            title=paper["title"],
                            text=paper["abstract"],
                            abstract=paper["abstract"],
                            authors=paper["authors"],
                            publisher=paper["publisher"],
                            date=paper["year"],
                            unique_id=paper["corpusId"],
                            doi=paper["doi"],
                            references=paper["references"],
                        )

                        metadata_path = subdir / Path(str(paper["corpusId"]) + ".json")
                        if not metadata_path.exists() and paper["corpusId"] not in checkpoint_data:
                            with metadata_path.open("w") as f:
                                f.write(json.dumps(schema))

                    else:
                        metadata_path = subdir / Path(str(paper["corpusId"]) + ".json")
                        if not metadata_path.exists() and paper["corpusId"] not in checkpoint_data:
                            with metadata_path.open("w") as f:
                                f.write(json.dumps(paper))

                checkpoint_data.append(paper["corpusId"])

            except KeyboardInterrupt:
                progress.log("KeyboardInterrupt")
                if output_format == "pdf":
                    checkpoint_data.extend([doc[6] for doc in data_chunk])
                else:
                    checkpoint_data.extend([doc for doc in data_chunk])
                return
            except Exception as e:
                progress.log("Error: " + str(e))
                progress.update(task, advance=1)
                if output_format == "pdf":
                    checkpoint_data.extend([doc[6] for doc in data_chunk])
                else:
                    checkpoint_data.extend([doc for doc in data_chunk])
                continue
            progress.update(task, advance=1)

    async def main_multiple_ss(input_csv, input_format, output_format, nproc, nchunks):

        path = _prep_output_dir("SEMANTIC_SCHOLAR_complete")
        checkpoint = path.parent / Path("SS_checkpoint.json")
        if not checkpoint.exists():
            checkpoint.touch()
            checkpoint_data = []
        else:
            try:
                checkpoint_data = checkpoint.read_text()
                checkpoint_data = json.loads(checkpoint_data)
            except json.decoder.JSONDecodeError:
                checkpoint_data = []

        checkpoint_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(nproc)

        # split data into 2 equal chunks

        if input_format == "pes2o":
            data = _collect_from_path(input_csv)
            chunk_size = len(data) // nchunks
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        if input_format == "csv" or input_format == "checkpoint":
            with open(input_csv, "r") as f:
                if input_format == "csv":
                    reader = csv.reader(f)
                    # data = list(reader)
                    data = list(reader)[1:]  # first line is header
                    chunk_size = len(data) // nchunks
                    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa
                elif input_format == "checkpoint":
                    try:
                        checkpoint_data = checkpoint.read_text()
                        checkpoint_data = json.loads(checkpoint_data)
                    except json.decoder.JSONDecodeError:
                        checkpoint_data = []
                    chunk_size = len(checkpoint_data) // nchunks
                    chunks = [
                        checkpoint_data[i : i + chunk_size] for i in range(0, len(checkpoint_data), chunk_size)  # noqa
                    ]

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn(), disable=True) as progress:
            await asyncio.gather(
                *[
                    _complete_semantic_scholar(
                        i, chunk, path, progress, checkpoint_data, checkpoint_lock, semaphore, output_format
                    )
                    for i, chunk in enumerate(chunks)
                ]
            )

        with open(checkpoint, "w") as f:
            f.write(json.dumps(checkpoint_data))

    asyncio.run(main_multiple_ss(input_csv, input_format, output_format, nproc, nchunks))
