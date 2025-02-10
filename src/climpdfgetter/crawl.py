import datetime
import re
from pathlib import Path

import click
import requests
from bs4 import BeautifulSoup

from .convert import convert, ocr2json
from .sources import source_mapping
from .utils import _find_project_root


def _prep_output_dir(name: str) -> Path:
    single_crawl_dir = name + "_" + datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    path = Path(_find_project_root()) / Path("data/" + single_crawl_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


@click.command()
@click.argument("stop_idx", nargs=1, type=click.INT)
@click.argument("start_idx", nargs=1, type=click.INT)
def crawl(stop_idx: int, start_idx: int):
    """Asynchronously crawl a website via crawl4ai"""
    # TODO: Generalize this solution
    import asyncio

    from crawl4ai import AsyncWebCrawler, BrowserConfig  # , CrawlerRunConfig

    browser_config = BrowserConfig(
        browser_type="firefox",
        headless=False,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
        use_persistent_context=True,
        user_data_dir=str(Path(_find_project_root()) / Path("data/browser_data")),
        headers={"Accept-Language": "en-US"},
    )

    kwargs = {
        "magic": True,
    }

    async def main():
        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:
            # Run the crawler on EPA search result page

            n_of_pages_crawled = start_idx  # STARTING INDEX FOR RESULTS ALSO

            url_base = source_mapping["EPA"].search_base.split("/Exe")[0]  # 'https://nepis.epa.gov'

            while n_of_pages_crawled < stop_idx:

                source = source_mapping["EPA"].search_base + str(n_of_pages_crawled)

                main_result_page = await crawler.arun(url=source, **kwargs)
                search_result_links = [
                    i
                    for i in main_result_page.links["internal"]
                    if i["href"].startswith("https://nepis.epa.gov/Exe/ZyNET.exe/P")
                ]

                path = _prep_output_dir("EPA")

                for doc_page in search_result_links:
                    doc_page_result = await crawler.arun(url=doc_page["href"], **kwargs)
                    if doc_page_result.success:
                        soup = BeautifulSoup(doc_page_result.html, "html.parser")

                        # We get document as text first, since this contains the most metadata
                        text_link_base = soup.find_all(
                            "a", title=lambda x: x and "Download this document as unformatted OCR text" in x
                        )[0]

                        text_link = text_link_base.get("onclick").split("'")[1]  # necessary link hidden within js
                        main_text_link = url_base + text_link
                        r = requests.get(main_text_link, stream=True)

                        token = re.search(r"P[^.]+\.txt", main_text_link).group().split(".txt")[0]
                        path_to_doc = path / f"{token}.txt"
                        with path_to_doc.open("wb") as f:
                            f.write(r.content)

                        # We try obtaining the document as pdf or tiff, if possible

                    n_of_pages_crawled += 1

    # Run the async main function
    asyncio.run(main())


@click.command()
@click.argument("source", nargs=1)
def count(source: str):
    """Count the number of downloaded files from a given source."""
    total = 0
    data_root = Path(_find_project_root()) / Path("data/")
    for directory in data_root.iterdir():
        if directory.is_dir() and directory.name.startswith(source):
            total += len(list(directory.iterdir()))
    click.echo(total)
    return total


# @click.command()
# @click.argument("source", nargs=1)
# @click.argument("num_docs", nargs=1)
# def resume(source: str, num_docs: int):
#     """Resume a crawl from a given source. Download ``num_docs`` additional documents."""
#     begin_index = count(source)
#     crawl(begin_index + num_docs, begin_index)


@click.group()
def main():
    pass


main.add_command(crawl)
main.add_command(count)
# main.add_command(resume)
main.add_command(convert)
main.add_command(ocr2json)

if __name__ == "__main__":
    main()
