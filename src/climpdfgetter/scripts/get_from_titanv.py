import json
from pathlib import Path

import click
import requests
import tqdm

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
