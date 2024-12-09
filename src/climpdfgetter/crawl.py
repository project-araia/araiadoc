import datetime
from pathlib import Path

import click
import requests
from bs4 import BeautifulSoup

from .sources import source_mapping


def find_project_root():
    """Find the project root directory."""
    root_dir = Path(__file__).resolve().parents[2]
    return str(root_dir)


def prep_output_dir(name):
    single_crawl_dir = name + "_" + datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    path = Path(find_project_root()) / Path("data/" + single_crawl_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_page_range(search_base):
    pass


@click.command()
@click.argument("source", nargs=1, type=click.Choice(source_mapping.keys()))
def crawl(source: str):
    source = source_mapping[source]
    r = requests.get(source.search_base)
    soup = BeautifulSoup(r.text, "html.parser")
    DOC_IDS = []
    for line in str(soup).splitlines():
        if source.indicator in line:
            DOC_IDS.append(line.split(source.indicator)[-1].split(".txt")[0])

    path = prep_output_dir(source.__name__)

    for doc_id in DOC_IDS:
        r = requests.get(source.pdf_base.format(doc_id, doc_id), stream=True)
        path_to_doc = path / f"{doc_id}.PDF"
        with path_to_doc.open("wb") as f:
            f.write(r.content)


@click.group()
def main():
    pass


main.add_command(crawl)


if __name__ == "__main__":
    main()
