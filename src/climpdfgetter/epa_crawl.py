from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sources import EPA


def prep_output_dir(name):
    path = Path("../../data/{}".format(name))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_page_range(search_base):
    pass


def crawl(SOURCE):
    r = requests.get(SOURCE.search_base)
    soup = BeautifulSoup(r.text, "html.parser")
    DOC_IDS = []
    for line in str(soup).splitlines():
        if SOURCE.indicator in line:
            DOC_IDS.append(line.split(SOURCE.indicator)[-1].split(".txt")[0])

    path = prep_output_dir(SOURCE.__name__)

    for doc_id in DOC_IDS:
        r = requests.get(SOURCE.pdf_base.format(doc_id, doc_id), stream=True)
        path_to_doc = path / f"{doc_id}.PDF"
        with path_to_doc.open("wb") as f:
            f.write(r.content)


if __name__ == "__main__":
    crawl(EPA)
    # crawl(NOAA)
    # crawl(OSTI)
