import asyncio
import csv
import gzip
import json
import time
from pathlib import Path

import click
from ratelimit import limits, sleep_and_retry
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.searches import q
from climpdfgetter.utils import _build_session, _prep_output_dir

SINGLE_CORPUS_ID_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&" + "indent=true&q.op=OR&q={}&useParams="
)


TITANV_SELECT_URL = "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select"


def _complete_all_terms_cursor(
    output_dir: Path,
    progress,
    rows: int = 1000,
    flush_every_pages: int = 25,
):
    """
    Download all matching Solr documents using cursor-based pagination and write them
    to compressed JSONL batches.

    Output layout:
      output_dir/
        all_terms/
          batches/
            batch_000001.jsonl.gz
            batch_000002.jsonl.gz
            ...
          ids.txt
          checkpoint.json
    """
    session = _build_session()

    subdir = output_dir / "all_terms"
    subdir.mkdir(exist_ok=True)

    batch_dir = subdir / "batches"
    batch_dir.mkdir(exist_ok=True)

    ids_path = subdir / "ids.txt"
    checkpoint_path = subdir / "checkpoint.json"

    # Resume support
    cursor_mark = "*"
    page_index = 0
    batch_index = 0
    total_downloaded = 0

    if checkpoint_path.exists():
        try:
            checkpoint_data = json.loads(checkpoint_path.read_text())
            cursor_mark = checkpoint_data.get("cursor_mark", "*")
            page_index = checkpoint_data.get("page_index", 0)
            batch_index = checkpoint_data.get("batch_index", 0)
            total_downloaded = checkpoint_data.get("total_downloaded", 0)
        except json.JSONDecodeError:
            pass

    # First request: get numFound for progress
    initial_params = {
        "df": "paragraph",
        "indent": "true",
        "q.op": "OR",
        "q": q,
        "rows": rows,
        "sort": "id asc",  # replace if needed with true unique sort field
        "cursorMark": cursor_mark,
        "useParams": "",
    }

    r = session.get(TITANV_SELECT_URL, params=initial_params, timeout=120)
    r.raise_for_status()
    payload = r.json()

    num_found = payload["response"]["numFound"]
    task = progress.add_task("[white]All Terms: ", total=num_found, completed=total_downloaded)

    pending_docs = []
    pending_ids = []

    while True:
        params = {
            "df": "paragraph",
            "indent": "true",
            "q.op": "OR",
            "q": q,
            "rows": rows,
            "sort": "id asc",  # replace if needed
            "cursorMark": cursor_mark,
            "useParams": "",
        }

        try:
            r = session.get(TITANV_SELECT_URL, params=params, timeout=120)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            progress.log(f"* Error fetching cursor page {page_index}: {e}")
            time.sleep(5)
            continue

        response = payload["response"]
        docs = response["docs"]
        next_cursor_mark = payload.get("nextCursorMark", cursor_mark)

        if not docs:
            progress.log("* No more docs returned; stopping.")
            break

        pending_docs.extend(docs)
        pending_ids.extend(str(doc["corpus_id"][0]) for doc in docs if "corpus_id" in doc)

        page_index += 1
        total_downloaded += len(docs)
        progress.update(task, advance=len(docs))

        should_flush = page_index % flush_every_pages == 0

        if should_flush:
            batch_index += 1
            batch_path = batch_dir / f"batch_{batch_index: 06}.jsonl.gz"

            with gzip.open(batch_path, "at", encoding="utf-8") as f:
                for doc in pending_docs:
                    f.write(json.dumps(doc))
                    f.write("\n")

            with ids_path.open("a", encoding="utf-8") as f:
                for corpus_id in pending_ids:
                    f.write(corpus_id)
                    f.write("\n")

            checkpoint_data = {
                "cursor_mark": next_cursor_mark,
                "page_index": page_index,
                "batch_index": batch_index,
                "total_downloaded": total_downloaded,
                "rows": rows,
            }
            checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2))

            pending_docs.clear()
            pending_ids.clear()

        if next_cursor_mark == cursor_mark:
            progress.log("* Cursor did not advance; finished.")
            break

        cursor_mark = next_cursor_mark

    # Final flush
    if pending_docs:
        batch_index += 1
        batch_path = batch_dir / f"batch_{batch_index: 06}.jsonl.gz"

        with gzip.open(batch_path, "at", encoding="utf-8") as f:
            for doc in pending_docs:
                f.write(json.dumps(doc))
                f.write("\n")

        with ids_path.open("a", encoding="utf-8") as f:
            for corpus_id in pending_ids:
                f.write(corpus_id)
                f.write("\n")

    checkpoint_data = {
        "cursor_mark": cursor_mark,
        "page_index": page_index,
        "batch_index": batch_index,
        "total_downloaded": total_downloaded,
        "rows": rows,
        "complete": True,
    }
    checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2))

    return total_downloaded


@click.command()
@click.option("--source", "-s", nargs=1, type=click.Path(exists=True))
@click.option("--all-terms", "-a", is_flag=True)
def get_from_titanv(source: Path, all_terms: bool):
    """Provide an input dataset containing corpus IDs OR perform an "all terms" search.

    Use one of the options, not multiple.

    Args:
        source (Path): Path to input dataset.
        all_terms (bool): Whether to perform the pre-defined "all terms" search.
    """

    session = _build_session()

    @sleep_and_retry
    @limits(calls=180, period=1)
    def _do_request(corpus_id):
        return session.get(SINGLE_CORPUS_ID_REQUESTS_QUERY.format(corpus_id), timeout=5)

    def _complete_semantic_scholar(chunk_idx, data_chunk, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        for doc in data_chunk:
            try:
                corpus_id = doc[6]
                doc_path = subdir / Path(str(corpus_id) + ".json")
                r = _do_request(corpus_id)
                r.raise_for_status()
                progress.update(task, advance=1)
                checkpoint_data.append(corpus_id)

                if r.json()["response"]["numFound"] == 0:
                    continue
                with doc_path.open("w") as f:
                    json.dump(r.json(), f)

            except KeyboardInterrupt:
                progress.log("\n* User interrupted. Exiting.")
                return checkpoint_data
            except Exception as e:
                progress.log(f"\n* Error with {corpus_id}. Error: {e}")
                progress.update(task, advance=1)
                checkpoint_data.append(corpus_id)
                continue

        return checkpoint_data

    async def finish_main(source, all_terms):
        if not source and not all_terms:
            click.echo("Please provide a source (-s) or use --all-terms (-a).")
            return

        if all_terms:
            path = _prep_output_dir("titanv_all_terms_results_v2")
        else:
            path = _prep_output_dir("titanv_id_results_v2")

        checkpoint = path.parent / Path("titanv_checkpoint.json")
        if not checkpoint.exists():
            checkpoint.touch()
            checkpoint_data = []
        else:
            try:
                checkpoint_data = checkpoint.read_text()
                checkpoint_data = json.loads(checkpoint_data)
            except json.decoder.JSONDecodeError:
                checkpoint_data = []

        nchunks = 8
        checkpoint_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(nchunks)
        checkpoint_chunks = []

        if source:
            source_path = Path(source)
            if source_path.suffix == ".json":
                with source_path.open("r") as f:
                    ids = json.load(f)
                # Convert list of IDs to the format expected by _complete_semantic_scholar (id at index 6)
                data = [[None] * 6 + [cid] for cid in ids]
            else:
                with open(source, "r") as f:
                    reader = csv.reader(f)
                    data = list(reader)[1:]  # first line is header

            if not data:
                return

            chunk_size = max(1, len(data) // nchunks)
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                checkpoint_chunks = await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            _complete_semantic_scholar,
                            i,
                            chunk,
                            path,
                            progress,
                            checkpoint_data,
                            checkpoint_lock,
                            semaphore,
                        )
                        for i, chunk in enumerate(chunks)
                    ]
                )

        elif all_terms:
            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                totals = await asyncio.gather(
                    asyncio.to_thread(
                        _complete_all_terms_cursor,
                        path,
                        progress,
                        200,  # rows
                        50,  # flush_every_pages
                    )
                )
                progress.log(f"\n* Found {sum(totals)} documents.")
            return

        output_checkpoint_data = []
        output_checkpoint_data += sum(checkpoint_chunks, [])
        progress.log(f"\n* Found {len(output_checkpoint_data)} documents.")
        with checkpoint.open("w") as f:
            f.write(json.dumps(output_checkpoint_data))

    asyncio.run(finish_main(source, all_terms))
