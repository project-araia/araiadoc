# import sys
from pathlib import Path

import click

# import json
# import psycopg2
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .utils import _collect_from_path

# from joblib import Parallel, delayed


# from .schema import ParsedDocumentSchema


def _metadata_workflow(source_dir, dbname, user, password, host, port, table_name, progress):

    collected_input_files = _collect_from_path(Path(source_dir))
    # success_count = 0
    # fail_count = 0
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    # task = progress.add_task("[green]Fetching metadata", total=len(collected_input_files))
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    output_dir = Path(str(source_dir) + "_with_metadata")
    output_dir.mkdir(exist_ok=True, parents=True)


@click.command()
@click.argument("source_dir", nargs=1)
@click.argument("dbname")
@click.argument("user")
@click.argument("password")
@click.argument("host")
@click.argument("port")
@click.argument("table_name")
def get_metadata_from_database(source_dir, dbname, user, password, host, port, table_name):
    """
    Grabs metadata from a postgresql database and associates it with each of the processed input files.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _metadata_workflow(source_dir, dbname, user, password, host, port, table_name, progress)


if __name__ == "__main__":
    get_metadata_from_database()
