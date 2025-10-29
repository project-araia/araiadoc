import asyncio
import csv
import json
from pathlib import Path

import click
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from semanticscholar import AsyncSemanticScholar

from climpdfgetter.utils import _prep_output_dir


@click.command()
@click.argument("input_csv", nargs=1, type=click.Path(exists=True))
@click.option("-nproc", "-n", nargs=1, type=click.INT)
def complete_semantic_scholar(input_csv: Path, nproc: int):
    async def _get_document(paper_id):
        asch = AsyncSemanticScholar()
        return await asch.get_paper("CorpusID:" + paper_id)

    async def _complete_semantic_scholar(chunk_idx, data_chunk, output_dir, progress, checkpoint_data, lock):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        work_tasks = [asyncio.create_task(_get_document(doc[6])) for doc in data_chunk]

        async for paper_task in asyncio.as_completed(work_tasks):
            try:
                paper = await paper_task
                paper.get_paper("CorpusID:")  # TODO
                async with lock:
                    checkpoint_data.append(paper.id)
            except TimeoutError as e:
                progress.log("Error: " + str(e))
            progress.update(task, advance=1)

    async def main_multiple_ss(input_csv, nproc):

        path = _prep_output_dir("SEMANTIC_SCHOLAR_complete")
        checkpoint = path.parent / Path("SS_checkpoint.json")
        if not checkpoint.exists():
            checkpoint.touch()
        checkpoint_data = checkpoint.read_text()
        checkpoint_data = json.loads(checkpoint_data)

        checkpoint_lock = asyncio.Lock()

        # split data into 2 equal chunks
        with open(input_csv, "r") as f:
            reader = csv.reader(f)
            # data = list(reader)
            data = list(reader)[:10]
            chunk_size = len(data) // nproc
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            await asyncio.gather(
                *[
                    _complete_semantic_scholar(i, chunk, path, progress, checkpoint_data, checkpoint_lock)
                    for i, chunk in enumerate(chunks)
                ]
            )

    asyncio.run(main_multiple_ss(input_csv, nproc))
