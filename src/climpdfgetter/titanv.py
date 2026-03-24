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


@click.command()
@click.option("--source", "-s", nargs=1, type=click.Path(exists=True))
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
        try:
            first_request = _do_search_request(search_term, 0)
            first_request.raise_for_status()
            num_found = first_request.json()["response"]["numFound"]
        except Exception as e:
            progress.log(f"* Error starting search for {search_term}: {e}")
            return []

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

                progress.update(task, advance=250)
                if num_rejected > 0:
                    progress.log(f"{search_term}: Rejected {num_rejected} docs for search iteration {i // 250}.")
            except Exception as e:
                progress.log(f"\n* Error with {search_term} iteration {i // 250}. Error: {e}")
                progress.update(task, advance=250)
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

    async def finish_main(source, search_term):
        if not search_term:
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
