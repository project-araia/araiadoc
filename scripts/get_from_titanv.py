import asyncio
import csv
import json
import random
from pathlib import Path

import click
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.searches import RESILIENCE_SEARCHES
from climpdfgetter.utils import _prep_output_dir

REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=text&"
    + "indent=true&q.op=OR&q={}&rows=100&start={}&useParams="
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
@click.option("--search-terms", "-t", is_flag=True)
def get_from_titanv(source: Path, search_terms: bool):
    """Provide an input dataset containing corpus IDs. OR load search terms.

    Use one or the other, not both.

    Args:
        source (Path): Path to input dataset.
        search_terms (bool): Whether to search for terms or not.
    """

    from ratelimit import limits, sleep_and_retry

    @sleep_and_retry
    @limits(calls=60, period=1)
    def _do_request(corpus_id):
        return requests.get(SINGLE_REQUESTS_QUERY.format(corpus_id), stream=True, timeout=10)

    @sleep_and_retry
    @limits(calls=15, period=1)
    def _do_search_request(search_term, start):
        return requests.get(REQUESTS_QUERY.format(search_term, start), stream=True, timeout=100)

    def _complete_semantic_scholar_search_terms(search_term, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path(search_term)
        subdir.mkdir(exist_ok=True)
        first_request = _do_search_request(search_term, 0)
        num_found = first_request.json()["response"]["numFound"]
        random_color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
        task = progress.add_task(f"[{random_color}] {search_term}: ", total=num_found)

        num_rejected = 0
        results = []
        for doc in first_request.json()["response"]["docs"]:
            if str(doc["corpus_id"]) not in checkpoint_data:
                results.append(doc)
            else:
                num_rejected += 1

        with open(subdir / Path("search_term_0.json"), "w") as f:
            json.dump(results, f)
        progress.update(task, advance=len(results))
        if num_rejected > 0:
            progress.log(f"{search_term}: Rejected {num_rejected} docs for first search.")

        for i in range(100, num_found, 100):
            r = _do_search_request(search_term, i)
            try:
                r.raise_for_status()

                results = []
                num_rejected = 0
                for doc in r.json()["response"]["docs"]:
                    if str(doc["corpus_id"]) not in checkpoint_data:
                        results.append(doc)
                    else:
                        num_rejected += 1

                progress.update(task, advance=len(results))
                if num_rejected > 0:
                    progress.log(f"{search_term}: Rejected {num_rejected} docs for search iteration {i // 100}.")
                with open(subdir / Path("search_term_" + str(i // 100) + ".json"), "w") as f:
                    json.dump(results, f)
            except Exception as e:
                progress.log(f"\n* Error with {search_term} iteration {i // 100}. Error: {e}")
                progress.update(task, advance=100)
                continue

    def _complete_semantic_scholar(chunk_idx, data_chunk, output_dir, progress, checkpoint_data, lock, semaphore):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        for doc in data_chunk:
            try:
                corpus_id = doc[6]
                if corpus_id in checkpoint_data:
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

    async def finish_main(source, search_terms):
        if not search_terms:
            path = _prep_output_dir("600k_titanv_results")
        else:
            path = _prep_output_dir("titanv_search_results")
        checkpoint = path.parent / Path("combined_titanv_checkpoint.json")
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
            with open(source, "r") as f:
                reader = csv.reader(f)
                data = list(reader)[1:]  # first line is header
                chunk_size = len(data) // nchunks
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
        elif search_terms:
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
                        for term in RESILIENCE_SEARCHES
                    ]
                )

        output_checkpoint_data = []
        output_checkpoint_data += sum(checkpoint_chunks, [])
        progress.log(f"\n* Found {len(output_checkpoint_data)} documents.")
        with checkpoint.open("w") as f:
            f.write(json.dumps(output_checkpoint_data))

    asyncio.run(finish_main(source, search_terms))


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

if __name__ == "__main__":
    click_main()
