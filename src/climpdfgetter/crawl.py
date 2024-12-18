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

    source = source_mapping[source]

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


@click.command()
@click.argument("num_docs", nargs=1, type=click.INT)
@click.argument("start_idx", nargs=1, type=click.INT)
def advanced(num_docs: int, start_idx: int):
    """Asynchronously crawl a website via crawl4ai"""
    # TODO: Generalize this solution
    import asyncio

    from crawl4ai import AsyncWebCrawler, CacheMode

    headers = {"Accept-Language": "en-US"}

    user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0"

    kwargs = {
        "cache_mode": CacheMode.BYPASS,
        "exclude_external_links": True,
        "exclude_social_media_link": True,
        "magic": True,
    }

    async def main():
        # Create an instance of AsyncWebCrawler
        async with AsyncWebCrawler(
            browser_type="firefox", verbose=True, headers=headers, user_agent=user_agent, simulate_user=True
        ) as crawler:
            # Run the crawler on EPA search result page

            n_of_pages_crawled = start_idx  # STARTING INDEX FOR RESULTS ALSO

            url_base = source_mapping["EPA"].search_base.split("/Exe")[0]  # 'https://nepis.epa.gov'

            while n_of_pages_crawled < num_docs:

                source = source_mapping["EPA"].search_base + str(n_of_pages_crawled)

                main_result_page = await crawler.arun(url=source, **kwargs)
                search_result_links = [
                    i
                    for i in main_result_page.links["internal"]
                    if i["href"].startswith("https://nepis.epa.gov/Exe/ZyNET.exe/P")
                ]

                path = prep_output_dir("EPA")

                for doc_page in search_result_links:
                    doc_page_result = await crawler.arun(url=doc_page["href"], **kwargs)
                    if doc_page_result.success:
                        soup = BeautifulSoup(doc_page_result.html, "html.parser")
                        tiff_link_base = soup.find_all(
                            "a", title=lambda x: x and "Download this document as a multipage tiff" in x
                        )[0]
                        tiff_link = tiff_link_base.get("onclick").split("'")[1]  # necessary link hidden within js
                        main_tif_link = url_base + tiff_link
                        r = requests.get(main_tif_link, stream=True)
                        token = re.search(r"P[^.]+\.TIF", main_tif_link).group().split(".TIF")[0]
                        path_to_doc = path / f"{token}.TIF"
                        with path_to_doc.open("wb") as f:
                            f.write(r.content)
                    n_of_pages_crawled += 1

    # Run the async main function
    asyncio.run(main())


@click.group()
def main():
    pass


main.add_command(crawl)
main.add_command(advanced)

if __name__ == "__main__":
    main()
