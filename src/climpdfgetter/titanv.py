import asyncio
import csv
import gzip
import json
import random
import time
from pathlib import Path

import click
import requests
from ratelimit import limits, sleep_and_retry
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.searches import RESILIENCE_SEARCHES, q
from climpdfgetter.utils import _build_session, _prep_output_dir

REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=paragraph&"
    + "indent=true&q.op=OR&q={}&rows=250&start={}&useParams="
)

SINGLE_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&" + "indent=true&q.op=OR&q={}&useParams="
)

ALL_TERMS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=paragraph"
    + "&indent=true&q.op=OR&start={}&q=%27Extreme%20Heat%20Climate%27%20OR%0A"
    + "%27Extreme%20Cold%20Climate%27%20OR%0A%27Heat%20Wave%20Climate%27%20OR%0A"
    + "Drought%20OR%0A%27Flooding%20Climate%27%20OR%0A%27Tropical%20Cyclone%27%20OR%0AHurricane%"
    + "20OR%0AWildfire%20OR%0A%27Convective%20Storm%27%20OR%0A%27Sea%20Level%20Rise"
    + "%27%20OR%0A%27Permafrost%20Thaw%27%20OR%0A%27Ocean%20Acidification%27%20OR%0A%27"
    + "Carbon%20Dioxide%20Fertilizer%27%20OR%0A%27Rising%20Ocean%20Temperature%27%20OR%0A%27"
    + "Snowmelt%20Timing%27%20OR%0A%27Arctic%20Sea%20Ice%27%20OR%0A%27Ice%20Storm%27%20OR%"
    + "0ADerecho%20OR%0ATornado%20OR%0A%27Extreme%20Wind%27%20OR%0A%27Urban%20Heat%20Island"
    + "%27%20OR%0A%27Coastal%20Flooding%27%20OR%0A%27Extreme%20Rainfall%27%20OR%0ABlizzard&rows=200&useParams="
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
@click.option("--search-term", "-t", multiple=True)
@click.option("--all-terms", "-a", is_flag=True)
def get_from_titanv(source: Path, search_term: tuple[str], all_terms: bool):
    """Provide an input dataset containing corpus IDs. OR load search terms. OR perform an "all terms" search.

    Use one of the options, not multiple.

    Args:
        source (Path): Path to input dataset.
        search_term (tuple[str]): Specific search terms to look for.
        all_terms (bool): Whether to perform the pre-defined "all terms" search.
    """

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    @sleep_and_retry
    @limits(calls=180, period=1)
    def _do_request(corpus_id):
        return session.get(SINGLE_REQUESTS_QUERY.format(corpus_id), timeout=5)

    @sleep_and_retry
    @limits(calls=180, period=1)
    def _do_all_terms_request(start):
        return session.get(ALL_TERMS_QUERY.format(start), timeout=100)

    @sleep_and_retry
    @limits(calls=15, period=1)
    def _do_search_request(search_term, start):
        return session.get(REQUESTS_QUERY.format(search_term, start), stream=True, timeout=100)

    def _complete_semantic_scholar_search_terms(search_term, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path(search_term)
        subdir.mkdir(exist_ok=True)
        try:
            first_request = _do_search_request(search_term, 0)
            first_request.raise_for_status()
            num_found = first_request.json()["response"]["numFound"]
        except Exception as e:
            progress.log(f"* Error starting search for {search_term}: {e}")
            return []

        random_color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
        task = progress.add_task(f"[{random_color}] {search_term}: ", total=num_found)

        all_ids = []
        for doc in first_request.json()["response"]["docs"]:
            corpus_id = str(doc["corpus_id"][0])
            with open(subdir / Path(corpus_id + ".json"), "w") as f:
                json.dump(doc, f)
            all_ids.append(corpus_id)

        progress.update(task, advance=250)

        for i in range(250, num_found, 250):
            r = _do_search_request(search_term, i)
            try:
                r.raise_for_status()

                for doc in r.json()["response"]["docs"]:
                    corpus_id = str(doc["corpus_id"][0])
                    with open(subdir / Path(corpus_id + ".json"), "w") as f:
                        json.dump(doc, f)
                    all_ids.append(corpus_id)

                progress.update(task, advance=250)
            except Exception as e:
                progress.log(f"\n* Error with {search_term} iteration {i // 250}. Error: {e}")
                progress.update(task, advance=250)
                continue
        return all_ids

    def _complete_all_terms(output_dir, progress, checkpoint_data, lock, semaphore):
        subdir = output_dir / "all_terms"
        subdir.mkdir(exist_ok=True)
        try:
            first_request = _do_all_terms_request(0)
            first_request.raise_for_status()
            num_found = first_request.json()["response"]["numFound"]
        except Exception as e:
            progress.log(f"* Error starting all terms search: {e}")
            return []

        task = progress.add_task("[white]All Terms: ", total=num_found)

        all_ids = []
        for doc in first_request.json()["response"]["docs"]:
            corpus_id = str(doc["corpus_id"][0])
            with open(subdir / Path(corpus_id + ".json"), "w") as f:
                json.dump(doc, f)
            all_ids.append(corpus_id)

        progress.update(task, advance=200)

        for i in range(200, num_found, 200):
            r = _do_all_terms_request(i)
            try:
                r.raise_for_status()

                for doc in r.json()["response"]["docs"]:
                    corpus_id = str(doc["corpus_id"][0])
                    with open(subdir / Path(corpus_id + ".json"), "w") as f:
                        json.dump(doc, f)
                    all_ids.append(corpus_id)

                progress.update(task, advance=200)
            except Exception as e:
                progress.log(f"\n* Error with all terms iteration {i // 200}. Error: {e}")
                progress.update(task, advance=200)
                continue
        return all_ids

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

    async def finish_main(source, search_term, all_terms):
        if all_terms:
            path = _prep_output_dir("titanv_all_terms_results_v2")
        elif not search_term:
            path = _prep_output_dir("titanv_id_results_v2")
        else:
            path = _prep_output_dir("titanv_search_term_results_v2")
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
        elif search_term:
            terms = search_term if search_term else RESILIENCE_SEARCHES
            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                checkpoint_chunks = await asyncio.gather(
                    *[
                        asyncio.to_thread(
                            _complete_semantic_scholar_search_terms,
                            term,
                            path,
                            progress,
                            checkpoint_data,
                            checkpoint_lock,
                            semaphore,
                        )
                        for term in terms
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

    asyncio.run(finish_main(source, search_term, all_terms))
