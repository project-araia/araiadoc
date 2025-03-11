import re
from pathlib import Path

import click
import requests
import tqdm
from bs4 import BeautifulSoup
from tqdm import auto

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


def _get_configs(path: Path):
    from crawl4ai import BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(
        browser_type="firefox",
        headless=True,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
        headers={"Accept-Language": "en-US"},
        accept_downloads=True,
        downloads_path=path,
    )

    run_config = CrawlerRunConfig(
        exclude_external_links=True,
        simulate_user=True,
        magic=True,
        wait_for_images=True,
    )

    metadata_config = CrawlerRunConfig(
        exclude_external_links=True,
        simulate_user=True,
        magic=True,
        wait_for_images=True,
        js_code="""
            document.querySelector('a.export-link[data-format="json"]').click()
        """,
        wait_for="""
            document.readyState === "complete"
        """,
    )

    return browser_config, run_config, metadata_config


def _download_document(doc_page: dict, url_base: str, path: Path, n_successful_crawls: int, t: tqdm):
    token = doc_page["href"].split(url_base)[-1]  # https://www.osti.gov/servlets/purl/1514957
    r = requests.get(doc_page["href"], stream=True)
    path_to_doc = path / f"{token}.pdf"
    with path_to_doc.open("wb") as f:
        f.write(r.content)
    n_successful_crawls += 1
    t.update(1)


def _get_result_links(result_page: dict, url_base: str):
    return [i for i in result_page.links["internal"] if i["href"].startswith(url_base)]


def _get_max_results(soup):
    max_pages = int(
        soup.find(class_="breadcrumb-item text-muted active").getText().split()[-1]
    )  # <span class="breadcrumb-item text-muted active">Page 1 of 54</span></nav>

    max_results_soup = soup.find("h1").getText().split()[0]
    # <div class="col-12 col-md-5"><h1>535 Search Results</h1></div>

    max_results = int("".join(max_results_soup.split(",")))  # handle results like '1,000'

    if max_results >= 1000:
        click.echo("* More than 1000 results found. Due to OSTI limitations only the first 1000 are available.")
        click.echo("* Try adjusting the year range on future crawls.")
    return max_pages, max_results


def _checkpoint(
    path, search_term: str, start_year: int, stop_year: int, result_page: int, max_pages: int, max_results: int
):
    import json

    with open(path / "checkpoint.json", "w") as f:
        json.dump(
            {
                "search_term": search_term,
                "start_year": start_year,
                "stop_year": stop_year,
                "result_page": result_page,
                "max_pages": max_pages,
                "max_results": max_results,
            },
            f,
        )


@click.command()
@click.argument("search_term", nargs=1, type=click.STRING)
@click.argument("start_year", nargs=1, type=click.INT)
@click.argument("stop_year", nargs=1, type=click.INT)
def crawl_osti(search_term: str, start_year: int, stop_year: int):
    """Asynchronously crawl OSTI result pages"""
    import asyncio

    from crawl4ai import AsyncWebCrawler

    assert start_year <= stop_year
    assert stop_year <= 2025
    assert start_year >= 2000

    path = _prep_output_dir("OSTI_" + str(start_year) + "_" + str(stop_year) + "_" + search_term)

    browser_config, run_config, metadata_config = _get_configs(path)

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
            formatted_search_base_init = search_base.format(search_term, stop_year, start_year, 0)
            url_base = "https://www.osti.gov/servlets/purl/"

            click.echo("* Performing first search")

            first_result_page = await crawler.arun(url=formatted_search_base_init, config=metadata_config)

            if first_result_page.downloaded_files:
                click.echo("* Metadata collected.")
            else:
                click.echo("* Unable to collect metadata.")

            first_soup = BeautifulSoup(first_result_page.html, "html.parser")

            first_result_page_links = _get_result_links(first_result_page, url_base)
            max_pages, max_results = _get_max_results(first_soup)

            collected_exceptions = []
            click.echo("* Beginning document crawl.")

            t = auto.tqdm(total=max_results)

            for doc_page in first_result_page_links:
                try:
                    _download_document(doc_page, url_base, path, n_successful_crawls, t)

                except Exception as e:
                    collected_exceptions.append([doc_page["href"], str(e)])
                    n_failed_crawls += 1
                    t.update(1)
            _checkpoint(path, search_term, start_year, stop_year, 0, max_pages, max_results)

            click.echo("* Performing subsequent searches")
            for result_page in range(1, max_pages):
                try:
                    formatted_search_base = search_base.format(search_term, stop_year, start_year, result_page)
                    main_result_page = await crawler.arun(url=formatted_search_base, config=run_config)

                    search_result_links = _get_result_links(main_result_page, url_base)

                    for doc_page in search_result_links:
                        try:
                            _download_document(doc_page, url_base, path, n_successful_crawls, t)

                        except Exception as e:
                            collected_exceptions.append([doc_page["href"], str(e)])
                            n_failed_crawls += 1
                            t.update(1)

                except Exception as e:
                    collected_exceptions.append([formatted_search_base, str(e)])
                    n_failed_crawls += 10
                    t.update(10)
                _checkpoint(path, search_term, start_year, stop_year, result_page, max_pages, max_results)

            t.close()
            click.echo("* Successes: " + str(n_successful_crawls))
            click.echo("* Failures: " + str(n_failed_crawls))
            click.echo("* Exceptions: ")
            for i in collected_exceptions:
                click.echo("* " + str(i[0]) + ": " + str(i[1]) + "\n")

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
