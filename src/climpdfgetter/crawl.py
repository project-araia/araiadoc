import re
from pathlib import Path

import click
import requests
import tqdm
from bs4 import BeautifulSoup

from .convert import convert, epa_ocr_to_json

# from .searches import RESILIENCE_SEARCHES, YEAR_RANGES
from .sources import source_mapping
from .utils import _find_project_root, _prep_output_dir


@click.command()
@click.argument("stop_idx", nargs=1, type=click.INT)
@click.argument("start_idx", nargs=1, type=click.INT)
def crawl_epa(stop_idx: int, start_idx: int):
    """Asynchronously crawl EPA result pages"""
    # TODO: Generalize this solution
    import asyncio

    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=False,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
        use_persistent_context=True,
        user_data_dir=str(Path(_find_project_root()) / Path("data/browser_data")),
        headers={"Accept-Language": "en-US"},
        verbose=True,
    )

    run_config = CrawlerRunConfig(
        exclude_external_links=True,
        remove_overlay_elements=True,
        simulate_user=True,
        magic=True,
        wait_for_images=True,
        wait_for="js:() => document.getElementById('results_header').offsetParent !== null",
    )

    async def main_epa():

        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:
            # Run the crawler on EPA search result page

            n_of_pages_crawled = start_idx  # STARTING INDEX FOR RESULTS ALSO

            url_base = source_mapping["EPA"].search_base.split("/Exe")[0]  # 'https://nepis.epa.gov'

            while n_of_pages_crawled < stop_idx:

                source = source_mapping["EPA"].search_base + str(n_of_pages_crawled)

                main_result_page = await crawler.arun(url=source, config=run_config)

                search_result_links = [
                    i
                    for i in main_result_page.links["internal"]
                    if i["href"].startswith("https://nepis.epa.gov/Exe/ZyNET.exe/P")
                ]

                path = _prep_output_dir("EPA")

                for doc_page in search_result_links:
                    doc_page_result = await crawler.arun(url=doc_page["href"], config=run_config)
                    if doc_page_result.success:
                        soup = BeautifulSoup(doc_page_result.html, "html.parser")

                        # We get document as text first, since this contains the most metadata
                        text_link_base = soup.find_all(
                            "a",
                            title=lambda x: x and "Download this document as unformatted OCR text" in x,
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
    asyncio.run(main_epa())


@click.command()
@click.argument("search_term", nargs=1, type=click.STRING)
@click.argument("start_year", nargs=1, type=click.INT)
@click.argument("stop_year", nargs=1, type=click.INT)
def crawl_osti(search_term: str, start_year: int, stop_year: int):
    """Asynchronously crawl OSTI result pages"""
    import asyncio

    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    assert start_year <= stop_year
    assert stop_year <= 2025
    assert start_year >= 2000

    browser_config = BrowserConfig(
        browser_type="firefox",
        headless=True,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
        use_persistent_context=True,
        user_data_dir=str(Path(_find_project_root()) / Path("browser_data")),
        headers={"Accept-Language": "en-US"},
        verbose=True,
    )

    run_config = CrawlerRunConfig(
        exclude_external_links=True,
        remove_overlay_elements=True,
        simulate_user=True,
        magic=True,
        wait_for_images=True,
    )

    click.echo("* Crawling OSTI")
    click.echo("* Searching for: " + search_term)
    click.echo("* Documents from " + str(start_year) + " to " + str(stop_year))

    async def main_osti():

        n_successful_crawls = 0
        n_failed_crawls = 0

        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:

            click.echo("* Calculating starting URL")

            search_base = source_mapping["OSTI"].search_base
            formatted_search_base_init = search_base.format(search_term, start_year, stop_year, 0)
            url_base = "https://www.osti.gov/servlets/purl/"

            click.echo("* Performing first search")
            first_result_page = await crawler.arun(url=formatted_search_base_init, config=run_config)

            first_soup = BeautifulSoup(first_result_page.html, "html.parser")
            # will be searching for num docs, num pages

            first_result_page_links = [i for i in first_result_page.links["internal"] if i["href"].startswith(url_base)]
            print(first_result_page_links)

            max_pages = int(first_soup.find_all("select")[0].find_all("option")[-1].get("value"))  # TODO: incorrect

            n_of_result_pages_crawled = 1

            path = _prep_output_dir("OSTI_" + start_year + "_" + stop_year + "_" + search_term)

            while n_of_result_pages_crawled < max_pages:

                source = source_mapping["OSTI"].search_base + str(n_of_result_pages_crawled)

                main_result_page = await crawler.arun(url=source, config=run_config)

                search_result_links = [i for i in main_result_page.links["internal"] if i["href"].startswith(url_base)]

                path = _prep_output_dir("OSTI")

                for doc_page in tqdm(search_result_links):
                    doc_page_result = await crawler.arun(url=doc_page["href"], config=run_config)
                    if doc_page_result.success:
                        soup = BeautifulSoup(doc_page_result.html, "html.parser")

                        internal_titles = soup.find_all(
                            "a",
                            title=lambda x: x and "View Technical Report" or "View Accepted Manuscript (DOE)" in x,
                        )[0]

                        external_titles = soup.find_all("a", title=lambda x: x and "View Journal Article" in x)[0]

                        skip_titles = soup.find_all("a", title=lambda x: x and "View Dataset" in x)[0]

                        if len(skip_titles):
                            n_failed_crawls += 1
                            continue

                        token = doc_page["href"].split(url_base)[0]  # https://www.osti.gov/pages/biblio/2387003

                        if len(internal_titles):
                            # reliably grab internal download
                            text_link = internal_titles.get("href")
                            r = requests.get(text_link, stream=True)
                            path_to_doc = path / f"{token}.pdf"
                            with path_to_doc.open("wb") as f:
                                f.write(r.content)
                            n_successful_crawls += 1
                        elif len(external_titles):
                            # do our best to download pdfs from external link - if those links end in .pdf
                            text_link = external_titles.get("href")
                            external_page = await crawler.arun(url=text_link, config=run_config)
                            if external_page.success:
                                soup = BeautifulSoup(external_page.html, "html.parser")
                                pdf_links = soup.find_all("a", title=lambda x: x and x.endswith(".pdf"))
                                for i, link in enumerate(pdf_links):
                                    r = requests.get(link.get("href"), stream=True)
                                    path_to_doc = path / f"{token}_{i}.pdf"
                                    with path_to_doc.open("wb") as f:
                                        f.write(r.content)
                                n_successful_crawls += 1
                            else:
                                n_failed_crawls += 1
                                continue
                        else:
                            n_failed_crawls += 1
                            continue
                    else:
                        n_failed_crawls += 1
                        continue

                n_of_result_pages_crawled += 1

    # Run the async main function
    asyncio.run(main_osti())


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


@click.group()
def main():
    pass


main.add_command(crawl_epa)
main.add_command(crawl_osti)
main.add_command(count)
main.add_command(convert)
main.add_command(epa_ocr_to_json)

if __name__ == "__main__":
    main()
