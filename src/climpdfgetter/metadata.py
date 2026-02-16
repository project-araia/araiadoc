# import sys
import json
from pathlib import Path

import click
import psycopg2
import requests
from joblib import Parallel, delayed
from ratelimit import limits, sleep_and_retry
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .schema import ParsedDocumentSchema
from .utils import _collect_from_path

SINGLE_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&" + "indent=true&q.op=OR&q={}&useParams="
)


def _metadata_one_file_db(input_path, output_dir, dbname, user, password, host, port, table_name):

    conn = psycopg2.connect(dbname=dbname, user=user, password=password, host=host, port=port)
    cur = conn.cursor()

    corpus_id = input_path.stem.removesuffix("_processed")

    query = f"SELECT * FROM {table_name} WHERE corpus_id = {corpus_id} LIMIT 1;"  # noqa
    try:
        cur.execute(query)
    except Exception as e:
        return False, corpus_id, str(e)
    rows = cur.fetchall()

    with open(input_path, "r") as f:
        sectioned_text = json.load(f)

    if rows:
        data = {desc.name: val for desc, val in zip(cur.description, rows[0])}
    else:
        return False, corpus_id, "Table is empty or not found."

    abstract = sectioned_text.get("Abstract", "") or ""
    if len(abstract):
        sectioned_text.pop("Abstract")
    references = sectioned_text.get("References", "") or ""
    if len(references):
        sectioned_text.pop("References")

    document = ParsedDocumentSchema(
        unique_id=corpus_id,
        source="s2orc",
        title=data.get("title", "") or "",
        text=sectioned_text,
        abstract=abstract,
        authors=data.get("author", "") or "",
        publisher=data.get("publisher", "") or "",
        date=data.get("date", 0) or 0,
        doi=data.get("doi", "") or "",
        references=references,
    )

    output_path = output_dir / (corpus_id + ".json")
    with open(output_path, "w") as f:
        json.dump(document.model_dump(mode="json"), f)

    conn.close()
    cur.close()

    return True, corpus_id, None


def _metadata_one_file_semanticscholar(input_path, output_dir):

    corpus_id = input_path.stem.removesuffix("_processed")

    with open(input_path, "r") as f:
        sectioned_text = json.load(f)

    data = {}

    abstract = sectioned_text.get("Abstract", "") or ""
    if len(abstract):
        sectioned_text.pop("Abstract")
    references = sectioned_text.get("References", "") or ""
    if len(references):
        sectioned_text.pop("References")

    document = ParsedDocumentSchema(
        unique_id=corpus_id,
        source="s2orc",
        title=data.get("title", "") or "",
        text=sectioned_text,
        abstract=abstract,
        authors=data.get("author", "") or "",
        publisher=data.get("publisher", "") or "",
        date=data.get("date", 0) or 0,
        doi=data.get("doi", "") or "",
        references=references,
    )

    output_path = output_dir / (corpus_id + ".json")
    with open(output_path, "w") as f:
        json.dump(document.model_dump(mode="json"), f)

    return True, corpus_id, None


def _metadata_one_file_solr(input_path, output_dir):
    corpus_id = input_path.stem.removesuffix("_processed")

    with open(input_path, "r") as f:
        schema = json.load(f)

    @sleep_and_retry
    @limits(calls=60, period=1)
    def _do_request(corpus_id):
        return requests.get(SINGLE_REQUESTS_QUERY.format(corpus_id), stream=True, timeout=10)

    try:
        response = _do_request(corpus_id)
        abstract = response.json()["response"]["docs"][0]["abstract"][0]
    except Exception:
        return False, corpus_id, "Unable to obtain abstract from solr."

    references = schema.get("References", "") or ""
    if len(references):
        schema.pop("References")

    try:
        document = ParsedDocumentSchema(
            unique_id=corpus_id,
            source="s2orc",
            title=schema.get("title", "") or "",
            text=schema.get("text", "") or "",
            abstract=abstract,
            authors=schema.get("authors", "") or "",
            publisher=schema.get("publisher", "") or "",
            date=schema.get("date", 0) or 0,
            doi=schema.get("doi", "") or "",
            references=references,
        )
    except Exception:
        return False, corpus_id, "Input data likely not in the expected format."

    output_path = output_dir / (corpus_id + ".json")
    with open(output_path, "w") as f:
        json.dump(document.model_dump(mode="json"), f)

    return True, corpus_id, None


def _metadata_workflow(source_dir, progress, metadata_source, *args):

    collected_input_files = _collect_from_path(Path(source_dir))
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    output_dir = Path(str(Path(source_dir)) + "_with_metadata_" + metadata_source)
    output_dir.mkdir(exist_ok=True, parents=True)

    success_count = 0
    fail_count = 0
    task = progress.add_task(
        "[green]Fetching metadata from " + str(metadata_source) + ":", total=len(collected_input_files)
    )

    if metadata_source == "db":
        _metadata_one_file = _metadata_one_file_db
    elif metadata_source == "semanticscholar":
        _metadata_one_file = _metadata_one_file_semanticscholar
    elif metadata_source == "solr":
        _metadata_one_file = _metadata_one_file_solr
    else:
        raise ValueError("Invalid metadata source.")

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_metadata_one_file)(i, output_dir, *args) for i in collected_input_files
    )

    for success, stem, error in results:
        progress.update(task, advance=1)
        if success:
            success_count += 1
        else:
            fail_count += 1
            progress.log(f"* Error on: {stem}: {error}")

    progress.log("\n* Metadata fetching:")
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
        _metadata_workflow(source_dir, progress, "db", dbname, user, password, host, port, table_name)


@click.command()
@click.argument("source_dir", nargs=1)
def get_abstracts_from_solr(source_dir):
    """
    Grabs abstracts from solr and associates it with each of the processed input files
    that is already in the schema pattern.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _metadata_workflow(source_dir, progress, "solr")


@click.command()
@click.argument("source_dir", nargs=1)
def get_metadata_from_semanticscholar(source_dir):
    """
    Grabs metadata from a postgresql database and associates it with each of the processed input files.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _metadata_workflow(source_dir, progress, "semanticscholar")
