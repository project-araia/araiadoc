import asyncio
import csv
import json
import random
from pathlib import Path

import click
import requests
from ratelimit import limits, sleep_and_retry
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.searches import RESILIENCE_SEARCHES
from climpdfgetter.utils import _prep_output_dir

REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=paragraph&"
    + "indent=true&q.op=OR&q={}&rows=250&start={}&useParams="
)

SINGLE_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&" + "indent=true&q.op=OR&q={}&useParams="
)


# def main():
#     for search in RESILIENCE_SEARCHES:
#         path = _prep_output_dir("titanv_" + search + "_results")
#         r = requests.get(REQUESTS_QUERY.format(search, 0), stream=True, timeout=100)
#         num_found = r.json()["response"]["numFound"]

#         r.raise_for_status()
#         path_to_json = path / f"titanv_{search}.json"
#         with path_to_json.open("wb") as f:
#             f.write(r.content)


@click.command()
@click.option("--source", "-s", nargs=1)
def fetch_metadata(source: Path):
    """
    Provide an input dataset containing s2orc-style search results, fetch metadata for each document, dump
    together in schema.
    """


@click.command()
@click.option("--source", "-s", nargs=1)
@click.option("--search-term", "-t", multiple=True)
def get_from_titanv(source: Path, search_term: tuple[str]):
    """Provide an input dataset containing corpus IDs. OR load search terms.

    Use one or the other, not both.

    Args:
        source (Path): Path to input dataset.
        search_term (tuple[str]): Specific search terms to look for.
    """

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    @sleep_and_retry
    @limits(calls=180, period=1)
    def _do_request(corpus_id):
        return session.get(SINGLE_REQUESTS_QUERY.format(corpus_id), stream=True, timeout=5)

    @sleep_and_retry
    @limits(calls=15, period=1)
    def _do_search_request(search_term, start):
        return session.get(REQUESTS_QUERY.format(search_term, start), stream=True, timeout=100)

    def _complete_semantic_scholar_search_terms(search_term, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path(search_term)
        subdir.mkdir(exist_ok=True)
        first_request = _do_search_request(search_term, 0)
        num_found = first_request.json()["response"]["numFound"]
        random_color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
        task = progress.add_task(f"[{random_color}] {search_term}: ", total=num_found)

        num_rejected = 0
        all_ids = []
        for doc in first_request.json()["response"]["docs"]:
            corpus_id = str(doc["corpus_id"][0])
            if corpus_id not in checkpoint_data:
                with open(subdir / Path(corpus_id + ".json"), "w") as f:
                    json.dump(doc, f)
                all_ids.append(corpus_id)
            else:
                num_rejected += 1

        progress.update(task, advance=250)
        if num_rejected > 0:
            progress.log(f"{search_term}: Rejected {num_rejected} docs for first search.")

        for i in range(250, num_found, 250):
            r = _do_search_request(search_term, i)
            try:
                r.raise_for_status()

                num_rejected = 0
                for doc in r.json()["response"]["docs"]:
                    corpus_id = str(doc["corpus_id"][0])
                    if corpus_id not in checkpoint_data:
                        with open(subdir / Path(corpus_id + ".json"), "w") as f:
                            json.dump(doc, f)
                        all_ids.append(corpus_id)
                    else:
                        num_rejected += 1

                progress.update(task, advance=100)
                if num_rejected > 0:
                    progress.log(f"{search_term}: Rejected {num_rejected} docs for search iteration {i // 100}.")
            except Exception as e:
                progress.log(f"\n* Error with {search_term} iteration {i // 100}. Error: {e}")
                progress.update(task, advance=100)
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
                if corpus_id in checkpoint_data:
                    progress.update(task, advance=1)
                    continue
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

    async def finish_main(source, search_term):
        if not search_term:
            path = _prep_output_dir("600k_titanv_results_v2")
        else:
            path = _prep_output_dir("titanv_search_results_v2")
        checkpoint = path.parent / Path("600k_titanv_checkpoint.json")
        if not checkpoint.exists():
            checkpoint.touch()
            checkpoint_data = []
        else:
            try:
                checkpoint_data = checkpoint.read_text()
                checkpoint_data = json.loads(checkpoint_data)
            except json.decoder.JSONDecodeError:
                checkpoint_data = []

        nchunks = 4
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

        output_checkpoint_data = []
        output_checkpoint_data += sum(checkpoint_chunks, [])
        progress.log(f"\n* Found {len(output_checkpoint_data)} documents.")
        with checkpoint.open("w") as f:
            f.write(json.dumps(output_checkpoint_data))

    asyncio.run(finish_main(source, search_term))


@click.command()
@click.option("--source", "-s", nargs=1)
def build_checkpoint(source: Path):
    """Build a checkpoint file from a results directory - useful for resuming a download."""
    ids = []
    for path in source.iterdir():
        if path.is_dir() and path.name.startswith("chunk_"):
            for f in path.iterdir():
                if f.is_file() and f.suffix == ".json":
                    ids.append(f.stem)

    with open(source.parent / "titanv_checkpoint.json", "w") as f:
        json.dump(ids, f)


@click.group()
def click_main():
    pass


click_main.add_command(get_from_titanv)
click_main.add_command(fetch_metadata)

if __name__ == "__main__":
    click_main()
