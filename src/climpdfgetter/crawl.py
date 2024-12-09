import datetime
import re
from pathlib import Path

import click
import requests
from bs4 import BeautifulSoup

from .sources import source_mapping


def find_project_root() -> str:
    """Find the project root directory."""
    root_dir = Path(__file__).resolve().parents[2]
    return str(root_dir)


def prep_output_dir(name: str) -> Path:
    single_crawl_dir = name + "_" + datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    path = Path(find_project_root()) / Path("data/" + single_crawl_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def epa_total_entries(soup) -> tuple[int, int, int]:  # start, end, total
    relevant_form = soup.find_all("form")[2].text
    range_search = tuple(re.findall(r"\d+", relevant_form))
    return range_search


def epa_result_page(source, idx) -> str:
    """EPA result page obtained by modifying last url parameter. We won't assume this for other sources"""
    return source.search_base + idx


@click.command()
@click.argument("source", nargs=1, type=click.Choice(source_mapping.keys()))
@click.argument("pages", nargs=1, type=click.INT)
def crawl(source: str, pages: int):
    """Crawl a website for climate PDFs. Options are EPA, NOAA, and OSTI.

    The number of pages to crawl is passed as an argument following the source.
    """

    crawl_idx = 0
    n_of_pages_crawled = 0

    # we start by evaluating the page we are on: lets say we got back (0, 150, 9100)
    while n_of_pages_crawled < pages:
        r = requests.get(epa_result_page(source, str(crawl_idx)))  # Last url parameter is the index of first result
        soup = BeautifulSoup(r.text, "html.parser")
        page_start, page_end, total = epa_total_entries(soup)  # TODO: choose parser based on source
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
            crawl_idx += 1
        n_of_pages_crawled += 1


@click.group()
def main():
    pass


main.add_command(crawl)


if __name__ == "__main__":
    main()
