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


def _chunk_list(data, n):
    if not data:
        return []
    chunk_size = max(1, len(data) // n)
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa


async def _get_document(paper_id, semaphore, asch):
    async with semaphore:
        return await asch.get_paper("CorpusID:" + str(paper_id))


async def _process_combined_chunk(
    data_chunk, metadata_map, checkpoint_data, lock, subdir, progress, task, color, semaphore=None, asch=None
):
    import ast

    for file_path in data_chunk:
        try:
            if file_path is None:
                continue

            stem = file_path.stem
            corpus_id = stem.replace("_processed", "")

            if corpus_id in checkpoint_data:
                progress.update(task, advance=1)
                continue

            meta = None
            paper = None

            # Try to get metadata from CSV map
            if metadata_map and corpus_id in metadata_map:
                meta = metadata_map[corpus_id]

            # If not found, try API if allowed
            if not meta and asch:
                try:
                    async with semaphore:
                        paper = await asch.get_paper("CorpusID:" + str(corpus_id))
                except Exception:
                    # progress.log(f"[{color}]API Error for {corpus_id}: {e}")
                    pass

            if not meta and not paper:
                # progress.log(f"[{color}]ID {corpus_id} not found in metadata or API.")
                progress.update(task, advance=1)
                continue

            # Prepare fields
            title = ""
            abstract = ""
            year = 0
            authors_list = []

            if meta:
                title = meta["title"]
                abstract = meta["abstract"]
                year = meta["year"] if meta["year"] else 0

                try:
                    raw_authors = meta["authors"]
                    if raw_authors:
                        authors_data = ast.literal_eval(raw_authors)
                        for au in authors_data:
                            name = f"{au.get('first', '')} {au.get('last', '')}".strip()
                            if name:
                                authors_list.append(name)
                except Exception:
                    pass
            elif paper:
                title = paper.title
                abstract = paper.abstract
                year = paper.year
                authors_list = [author.name for author in paper.authors]

            # Read text content
            with open(file_path, "r") as f:
                text_content = json.load(f)

            final_text = text_content if isinstance(text_content, dict) else {}

            schema = ParsedDocumentSchema(
                source="Semantic Scholar",
                title=title,
                text=final_text,
                abstract=abstract,
                authors=authors_list,
                publisher="",
                date=year,
                unique_id=corpus_id,
                doi="",
                references="",
            )

            out_path = subdir / f"{corpus_id}.json"
            with open(out_path, "w") as f:
                f.write(json.dumps(schema.model_dump(mode="json", by_alias=True)))

            async with lock:
                checkpoint_data.append(corpus_id)

            progress.update(task, advance=1)

        except Exception as e:
            progress.log(f"[{color}]Error processing {file_path}: {e}")
            progress.update(task, advance=1)


async def _process_api_chunk(
    data_chunk,
    input_format,
    output_format,
    checkpoint_data,
    semaphore,
    subdir,
    progress,
    task,
    color,
):
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
                        text={"abstract": paper["abstract"]} if paper["abstract"] else {},
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
                    schema = ParsedDocumentSchema(
                        source="Semantic Scholar",
                        title=paper.title,
                        text={},
                        abstract=paper.abstract,
                        authors=paper.authors,
                        publisher=paper.journal["name"],
                        date=paper.year,
                        unique_id=paper.corpusId,
                        doi=paper["doi"],
                        references=paper.references,
                    )
                    metadata_path = subdir / Path(str(paper["corpusId"]) + ".json")
                    if not metadata_path.exists():
                        with metadata_path.open("w") as f:
                            f.write(json.dump(schema.model_dump(mode="json", by_alias=True)))

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


@click.command()
@click.argument("input_file", nargs=1, type=click.Path(exists=True))
@click.option(
    "--input_format", "-i", nargs=1, type=click.Choice(["csv", "checkpoint", "pes2o", "combined"]), default="checkpoint"
)
@click.option("--input_metadata_file", "-m", nargs=1, type=click.Path(exists=True))
@click.option("--output_format", "-o", nargs=1, type=click.Choice(["metadata", "pdf", "combined"]), default="combined")
@click.option("-nproc", "-n", nargs=1, type=click.INT, default=1)
def complete_semantic_scholar(
    input_file: Path, input_format: str, input_metadata_file: Path, output_format: str, nproc: int
):
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

    async def _complete_semantic_scholar(
        chunk_idx,
        data_chunk,
        output_dir,
        progress,
        checkpoint_data,
        lock,
        semaphore,
        output_format,
        metadata_map=None,
    ):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        if output_format == "combined":
            asch = AsyncSemanticScholar() if input_format == "combined" else None

            if not metadata_map and input_format != "combined":
                progress.log(f"[{color}]Error: Metadata map is empty and fallback logic disabled.")
                return

            await _process_combined_chunk(
                data_chunk, metadata_map, checkpoint_data, lock, subdir, progress, task, color, semaphore, asch
            )
        else:
            await _process_api_chunk(
                data_chunk,
                input_format,
                output_format,
                checkpoint_data,
                semaphore,
                subdir,
                progress,
                task,
                color,
            )

    async def main_multiple_ss(input_file, input_format, input_metadata_file, output_format, nproc):

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
        click.echo(f"Loaded {len(checkpoint_data)} processed IDs from checkpoint.")

        checkpoint_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(nproc)

        # split data into 2 equal chunks

        if input_format == "pes2o" or input_format == "combined":
            data = _collect_from_path(Path(input_file))
            # Ignore rejected files
            data = [f for f in data if not f.name.endswith("_rejected.json")]
            click.echo(f"Found {len(data)} input files.")

            chunk_size = len(data) // nproc
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        if input_format == "csv" or input_format == "checkpoint":
            with open(input_file, "r") as f:
                if input_format == "csv":
                    reader = csv.reader(f)
                    # data = list(reader)
                    data = list(reader)[1:]  # first line is header
                    chunk_size = len(data) // nproc
                    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa
                elif input_format == "checkpoint":
                    try:
                        with open(input_file, "r") as f:
                            checkpoint_data = json.load(f)
                    except json.decoder.JSONDecodeError:
                        checkpoint_data = []
                    chunk_size = len(checkpoint_data) // nproc
                    chunks = [
                        checkpoint_data[i : i + chunk_size] for i in range(0, len(checkpoint_data), chunk_size)  # noqa
                    ]

        metadata_map = {}
        if output_format == "combined":
            if input_metadata_file:  # Only load if provided
                click.echo("Loading metadata map...")
                with open(input_metadata_file, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Assuming paper_id is the key
                        metadata_map[row["paper_id"]] = row
                click.echo(f"Loaded {len(metadata_map)} metadata entries.")
            elif input_format != "combined":
                click.echo(
                    "Error: --input_metadata_file / -m required for combined output unless input_format is 'combined'."
                )
                return

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn(), disable=True) as progress:
            await asyncio.gather(
                *[
                    _complete_semantic_scholar(
                        i,
                        chunk,
                        path,
                        progress,
                        checkpoint_data,
                        checkpoint_lock,
                        semaphore,
                        output_format,
                        metadata_map,
                    )
                    for i, chunk in enumerate(chunks)
                ]
            )

        with open(checkpoint, "w") as f:
            f.write(json.dumps(checkpoint_data))

    asyncio.run(main_multiple_ss(input_file, input_format, input_metadata_file, output_format, nproc))


if __name__ == "__main__":
    complete_semantic_scholar()
