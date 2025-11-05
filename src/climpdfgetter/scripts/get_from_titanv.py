import asyncio
import csv
import json
from pathlib import Path

import click
import requests
import tqdm
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.utils import _prep_output_dir

SOLR_QUERY = """
("extreme heat" AND climate) OR
("extreme cold" AND climate) OR
("heat wave" AND climate) OR
(drought AND climate) OR
(flood AND climate) OR
("tropical cyclone" AND climate) OR
(hurricane AND climate) OR
(wildfire AND climate) OR
("convective storm" AND climate) OR
("sea level rise" AND climate) OR
("permafrost thaw" AND climate) OR
("ocean acidification" AND climate) OR
("carbon dioxide fertilizer" AND climate) OR
("rising ocean temperature" AND climate) OR
("snowmelt timing" AND climate) OR
("arctic sea ice" AND climate) OR
("ice storm" AND climate) OR
(derecho AND climate) OR
(tornado AND climate) OR
("extreme wind" AND climate) OR
("urban heat island" AND climate) OR
("coastal flooding" AND climate) OR
("extreme rainfall" AND climate) OR
(blizzard AND climate)
"""

REQUESTS_QUERY = ""
SINGLE_REQUESTS_QUERY = (
    "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select?df=corpus_id&indent=true&q.op=OR&q={}&useParams="
)


def main():
    path = _prep_output_dir("titanv")
    idx = 0
    for i in tqdm.tqdm(range(0, 250000, 500)):
        r = requests.get(REQUESTS_QUERY.format(i), stream=True, timeout=100)
        r.raise_for_status()
        path_to_json = path / f"titanv_{idx}.json"
        idx += 1
        with path_to_json.open("wb") as f:
            f.write(r.content)


@click.command()
@click.option("--source", "-s", nargs=1)
def get_from_titanv(source: Path):
    """Provide an input dataset containing corpus IDs. Check TitanV for matching docs."""

    from ratelimit import limits, sleep_and_retry

    @sleep_and_retry
    @limits(calls=1, period=1)
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
                r = requests.get(SINGLE_REQUESTS_QUERY.format(corpus_id), stream=True, timeout=10)
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

    async def finish_main(source):
        path = _prep_output_dir("600k_titanv_results")
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

        output_checkpoint_data = []
        output_checkpoint_data += sum(checkpoint_chunks, [])
        progress.log(f"\n* Found {len(output_checkpoint_data)} documents.")
        with checkpoint.open("w") as f:
            f.write(json.dumps(output_checkpoint_data))

    asyncio.run(finish_main(source))


@click.group()
def click_main():
    pass


click_main.add_command(get_from_titanv)

if __name__ == "__main__":
    click_main()
