# import sys
import json
from pathlib import Path

import click
import psycopg2
from joblib import Parallel, delayed
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .schema import ParsedDocumentSchema
from .utils import _collect_from_path


def _metadata_one_file(input_path, output_dir, cur, table_name):

    corpus_id = input_path.stem

    query = f"SELECT * FROM {table_name} WHERE corpus_id = {corpus_id} LIMIT 1;"  # noqa
    cur.execute(query)
    rows = cur.fetchall()

    with open(input_path, "r") as f:
        sectioned_text = json.load(f)

    if rows:
        for row in rows:
            # getting column names
            colnames = [desc[0] for desc in cur.description]
            print("\nFirst row found:")
            print("-" * 30)
            for i, val in enumerate(row):
                print(f"{colnames[i]}: {val} (Type: {type(val)})")
    else:
        print("Table is empty or not found.")

    document = ParsedDocumentSchema(
        unique_id=corpus_id,
        source="s2orc",
        title=rows[0]["title"],
        text=sectioned_text,
        abstract="",
        authors=rows[0]["author"],
        publisher=rows[0]["publisher"],
        date=0,
        doi=rows[0]["doi"],
        references="",
    )

    output_path = output_dir / (corpus_id + ".json")
    with open(output_path, "w") as f:
        json.dump(document.model_dump(mode="json"), f)


def _metadata_workflow(source_dir, dbname, user, password, host, port, table_name, progress):

    collected_input_files = _collect_from_path(Path(source_dir))
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    output_dir = Path(str(source_dir) + "_with_metadata")
    output_dir.mkdir(exist_ok=True, parents=True)

    success_count = 0
    fail_count = 0
    task = progress.add_task("[green]Fetching metadata from" + str(host) + ":", total=len(collected_input_files))

    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)
    cur = conn.cursor()

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_metadata_one_file)(i, output_dir, cur, table_name) for i in collected_input_files
    )

    conn.close()
    cur.close()

    for success, stem, error in results:
        progress.update(task, advance=1)
        if success:
            success_count += 1
        else:
            fail_count += 1
            progress.log(f"* Error on: {stem}: {error}")

    progress.log("\n* Sectionization:")
    progress.log("* Successes: " + str(success_count))
    progress.log("* Failures: " + str(fail_count))


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
