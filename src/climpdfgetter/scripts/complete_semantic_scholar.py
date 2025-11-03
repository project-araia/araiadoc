import asyncio
import csv
import json
from pathlib import Path

import click
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from semanticscholar import AsyncSemanticScholar

from climpdfgetter.utils import _prep_output_dir


@click.command()
@click.argument("input_csv", nargs=1, type=click.Path(exists=True))
@click.option("-nproc", "-n", nargs=1, type=click.INT)
@click.option("-nchunks", "-c", nargs=1, type=click.INT)
def complete_semantic_scholar(input_csv: Path, nproc: int, nchunks: int):
    async def _get_document(paper_id, semaphore, asch):
        async with semaphore:
            return await asch.get_paper("CorpusID:" + paper_id)

    async def _complete_semantic_scholar(chunk_idx, data_chunk, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        asch = AsyncSemanticScholar()

        work_tasks = [asyncio.create_task(_get_document(doc[6], semaphore, asch)) for doc in data_chunk]

        for paper_task in asyncio.as_completed(work_tasks):
            try:
                paper = await paper_task
                if paper is None or not paper["isOpenAccess"]:
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

                    checkpoint_data.append(paper["corpusId"])

            except KeyboardInterrupt:
                progress.log("KeyboardInterrupt")
                checkpoint_data.extend([doc[6] for doc in data_chunk])
                return
            except Exception as e:
                progress.log("Error: " + str(e))
                progress.update(task, advance=1)
                checkpoint_data.append(paper["corpusId"])
                continue
            progress.update(task, advance=1)

    async def main_multiple_ss(input_csv, nproc, nchunks):

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
        with open(input_csv, "r") as f:
            reader = csv.reader(f)
            # data = list(reader)
            data = list(reader)[1:]  # first line is header
            chunk_size = len(data) // nchunks
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            await asyncio.gather(
                *[
                    _complete_semantic_scholar(i, chunk, path, progress, checkpoint_data, checkpoint_lock, semaphore)
                    for i, chunk in enumerate(chunks)
                ]
            )

        with open(checkpoint, "w") as f:
            f.write(json.dumps(checkpoint_data))

    asyncio.run(main_multiple_ss(input_csv, nproc, nchunks))
