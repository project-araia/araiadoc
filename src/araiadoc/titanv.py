import asyncio
import csv
import gzip
import json
import time
from pathlib import Path

import click
from ratelimit import limits, sleep_and_retry
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from araiadoc.searches import Q2_NOT_BLOCK, q, q2_chunks
from araiadoc.utils import _build_session, _prep_output_dir

SINGLE_CORPUS_ID_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&" + "indent=true&q.op=OR&q={}&useParams="
)


TITANV_SELECT_URL = "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select"


def _complete_all_terms_cursor(
    output_dir: Path,
    progress,
    query_text: str,
    search_name: str,
    rows: int = 1000,
    flush_every_pages: int = 25,
    seen_ids: set | None = None,
    chunk_idx: int = 1,
    filter_query: str | None = None,
):
    """
    Download matching Solr documents using cursor-based pagination and write them
    to compressed JSONL batches.

    If ``seen_ids`` is provided (a shared set), any document whose corpus_id is
    already in the set is skipped and the set is updated with newly-written ids.
    This enables cross-chunk deduplication when the same output directory is
    reused across multiple sub-queries.

    ``chunk_idx`` is used to give each sub-query its own checkpoint file so that
    resume logic does not bleed across chunks.

    Output layout:
      output_dir/
        <search_name>/
          batches/
            batch_000001.jsonl.gz
            ...
          ids.txt
          checkpoint_1.json  (one per chunk)
    """
    if seen_ids is None:
        seen_ids = set()

    session = _build_session()

    subdir = output_dir / search_name
    subdir.mkdir(exist_ok=True)

    batch_dir = subdir / "batches"
    batch_dir.mkdir(exist_ok=True)

    ids_path = subdir / "ids.txt"
    checkpoint_path = subdir / f"checkpoint_{chunk_idx}.json"

    # Resume support
    cursor_mark = "*"
    page_index = 0
    total_downloaded = 0

    # Determine starting batch_index: continue from highest existing batch file
    # to avoid overwriting batches written by previous chunks.
    existing_batches = sorted(batch_dir.glob("batch_*.jsonl.gz"))
    if existing_batches:
        # Parse the numeric part from e.g. "batch_ 00008.jsonl.gz"
        last_name = existing_batches[-1].stem.replace(".jsonl", "")  # "batch_ 00008"
        try:
            batch_index = int(last_name.split("batch_")[1].strip())
        except (ValueError, IndexError):
            batch_index = len(existing_batches)
    else:
        batch_index = 0

    if checkpoint_path.exists():
        try:
            checkpoint_data = json.loads(checkpoint_path.read_text())
            if checkpoint_data.get("complete"):
                progress.log(
                    f"* Chunk {chunk_idx} already complete ({checkpoint_data.get('total_downloaded', '?')} docs)."
                    + " Skipping."
                )
                return checkpoint_data.get("total_downloaded", 0)
            cursor_mark = checkpoint_data.get("cursor_mark", "*")
            page_index = checkpoint_data.get("page_index", 0)
            batch_index = checkpoint_data.get("batch_index", 0)
            total_downloaded = checkpoint_data.get("total_downloaded", 0)
            progress.log(f"* Resuming from checkpoint: {total_downloaded} documents downloaded.")
        except json.JSONDecodeError:
            pass

    # First request: get numFound for progress
    initial_params = {
        "df": "paragraph",
        "indent": "true",
        "q.op": "OR",
        "q": query_text,
        "rows": rows,
        "sort": "id asc",  # replace if needed with true unique sort field
        "cursorMark": cursor_mark,
        "useParams": "",
    }
    if filter_query:
        initial_params["fq"] = filter_query

    for attempt in range(10):
        try:
            r = session.post(TITANV_SELECT_URL, data=initial_params, timeout=300)
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as e:
            progress.log(f"* Initial request failed (attempt {attempt + 1}/10): {e}")
            if attempt == 9:
                raise
            time.sleep(5 * (attempt + 1))

    num_found = payload["response"]["numFound"]
    label = search_name.replace("_", " ").title()
    if chunk_idx > 1 or True:  # always show chunk index for clarity
        label = f"{label} (chunk {chunk_idx})"
    progress.log(f"* Chunk {chunk_idx} Num found: {num_found}")
    task = progress.add_task(f"[white]{label}: ", total=num_found, completed=total_downloaded)

    pending_docs = []
    pending_ids = []

    while True:
        params = {
            "df": "paragraph",
            "indent": "true",
            "q.op": "OR",
            "q": query_text,
            "rows": rows,
            "sort": "id asc",  # replace if needed
            "cursorMark": cursor_mark,
            "useParams": "",
        }
        if filter_query:
            params["fq"] = filter_query

        try:
            r = session.post(TITANV_SELECT_URL, data=params, timeout=300)
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

        new_docs = []
        new_ids = []
        for doc in docs:
            if "corpus_id" not in doc:
                continue
            cid = str(doc["corpus_id"][0])
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            new_docs.append(doc)
            new_ids.append(cid)
        pending_docs.extend(new_docs)
        pending_ids.extend(new_ids)

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
@click.option("--all-weather", "-a", is_flag=True)
@click.option("--all-utility", "-u", is_flag=True)
@click.option(
    "--output-dir",
    "-o",
    nargs=1,
    type=click.Path(path_type=Path),
    default=None,
    help="Optional existing or new output directory.",
)
def get_from_titanv(source: Path, all_weather: bool, all_utility: bool, output_dir: Path | None):
    """Provide an input dataset containing corpus IDs OR perform a pre-defined search.

    Use one of the options, not multiple.
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

    async def finish_main(source, all_weather, all_utility, output_dir=None):
        if output_dir is not None:
            path = Path(output_dir)
            path.mkdir(parents=True, exist_ok=True)
        elif all_weather:
            path = _prep_output_dir("titanv_all_weather_results")
        elif all_utility:
            path = _prep_output_dir("titanv_all_utility_results")
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

        elif all_weather or all_utility:
            search_name = "all_weather" if all_weather else "all_utility"

            if all_weather:
                queries = [q]
                not_filter = None
            else:
                queries = q2_chunks
                # Use a cached filter query for the NOT block instead of
                # embedding it in every q param — dramatically faster on Solr.
                not_filter = f"-({Q2_NOT_BLOCK})"

            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                seen_ids: set = set()

                # Preload already-downloaded IDs for cross-chunk deduplication on resume
                ids_path = path / search_name / "ids.txt"
                if ids_path.exists():
                    with ids_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                seen_ids.add(line)
                    if seen_ids:
                        progress.log(f"* Loaded {len(seen_ids)} previously downloaded IDs for deduplication.")

                total = 0
                for chunk_idx, query_text in enumerate(queries, start=1):
                    if len(queries) > 1:
                        progress.log(f"* Running sub-query {chunk_idx}/{len(queries)} ...")
                    chunk_total = await asyncio.to_thread(
                        _complete_all_terms_cursor,
                        path,
                        progress,
                        query_text,
                        search_name,
                        200,  # rows
                        50,  # flush_every_pages
                        seen_ids,
                        chunk_idx,
                        not_filter,
                    )
                    total += chunk_total
                progress.log(f"\n* Found {total} unique documents across {len(queries)} sub-queries.")
            return

        output_checkpoint_data = []
        output_checkpoint_data += sum(checkpoint_chunks, [])
        progress.log(f"\n* Found {len(output_checkpoint_data)} documents.")
        with checkpoint.open("w") as f:
            f.write(json.dumps(output_checkpoint_data))

    asyncio.run(finish_main(source, all_weather, all_utility, output_dir))
