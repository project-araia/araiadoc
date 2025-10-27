import asyncio
import csv
import random
from pathlib import Path

import click
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.utils import _prep_output_dir


@click.group()
def main():
    pass


@click.command()
@click.argument("input_csv", nargs=1, type=click.Path(exists=True))
def complete_semantic_scholar(input_csv: Path):
    async def _complete_semantic_scholar(chunk_idx, data_chunk, output_dir, progress):

        color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
        task = progress.add_task(f"[{color}]" + chunk_idx, total=len(data_chunk))
        progress.update(task, advance=1)

    async def main_multiple_ss(input_csv):

        path = _prep_output_dir("SEMANTIC_SCHOLAR_complete_")
        data = open(input_csv / "complete_semantic_scholar.csv", "w")

        # split data into 4 equal chunks
        with open(input_csv, "r") as f:
            reader = csv.reader(f)
            data = list(reader)
            chunk_size = len(data) // 4
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            await asyncio.gather(
                *[_complete_semantic_scholar(i, chunk, path, progress) for i, chunk in enumerate(chunks)]
            )

    asyncio.run(main_multiple_ss(input_csv))
