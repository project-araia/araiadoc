import json
import random
import re
import signal
import sys
from pathlib import Path

import click
import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from climpdfgetter.convert import convert, epa_ocr_to_json
from climpdfgetter.searches import RESILIENCE_SEARCHES
from climpdfgetter.sources import source_mapping
from climpdfgetter.utils import (  # _checkpoint,; _download_document,; _get_result_links,
    _find_project_root,
    _get_configs,
    _get_dispatcher,
    _get_max_results,
    _prep_output_dir,
    count_local,
)


def timeout_handler(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, timeout_handler)


@click.command()
@click.argument("start_idx", nargs=1, type=click.INT)
@click.argument("stop_idx", nargs=1, type=click.INT)
@click.option("--search-term", "-t", multiple=True)
def crawl_epa(start_idx: int, stop_idx: int, search_term: list[str]):
    """Asynchronously crawl EPA result pages:

    `climpdf crawl-epa 0 2000 -t "Heat Waves" -t Flooding`

    """
    import asyncio

    from crawl4ai import BrowserConfig, CrawlerRunConfig

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

    async def main_epa(stop_idx: int, start_idx: int, search_term: str):

        assert stop_idx > start_idx

        path = _prep_output_dir("EPA_" + str(start_idx) + "_" + str(stop_idx) + "_" + search_term)

        click.echo("* Crawling EPA")
        click.echo("* Searching for: " + search_term)
        click.echo("* Document indexes: " + str(start_idx) + " to " + str(stop_idx))

        n_successful_crawls = 0
        n_failed_crawls = 0
        collected_exceptions = []

        click.echo("* Beginning document crawl.")

        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:

            n_of_pages_crawled = start_idx  # STARTING INDEX FOR RESULTS ALSO

            url_base = source_mapping["EPA"].search_base.split("/Exe")[0]  # 'https://nepis.epa.gov'

            while n_of_pages_crawled < stop_idx:

                source = source_mapping["EPA"].search_base + str(n_of_pages_crawled)
                source = source.format(search_term)

                try:

                    main_result_page = await crawler.arun(url=source, config=run_config)

                    search_result_links = [
                        i
                        for i in main_result_page.links["internal"]
                        if i["href"].startswith("https://nepis.epa.gov/Exe/ZyNET.exe/P")
                    ]

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

                except Exception as e:
                    click.echo(f"* Failed to crawl page {source}: {e}")
                    n_failed_crawls += 1
                    collected_exceptions.append(str(e))

        click.echo(
            f"* Finished crawling EPA. {n_successful_crawls} successful crawls and {n_failed_crawls} failed crawls."
        )

    # Run the async main function
    async def main_multiple_epa(search_terms: list[str], start_idx: int, stop_idx: int):
        await asyncio.gather(*[main_epa(search_term, start_idx, stop_idx) for search_term in search_terms])

    if len(search_term) == 1:
        asyncio.run(main_epa(search_term[0], start_idx, stop_idx))
    else:
        asyncio.run(main_multiple_epa(search_term, start_idx, stop_idx))


def _conversion_process(path):
    pass


def _conversion(path):
    pass


@click.command()
@click.argument("start_year", nargs=1, type=click.INT)
@click.argument("stop_year", nargs=1, type=click.INT)
@click.option("--search-term", "-t", multiple=True)
@click.option("--convert", "-c", is_flag=True, default=False, help="Convert PDFs to text.", type=click.BOOL)
def crawl_osti(start_year: int, stop_year: int, search_term: list[str], convert: bool):
    """Asynchronously crawl OSTI result pages:

    `climpdf crawl-osti 2000 2005 -t "Heat Waves" -t Flooding --convert`

    """
    import asyncio

    async def main_osti(search_term: str, start_year: int, stop_year: int, convert: bool, progress):

        assert start_year <= stop_year
        assert stop_year <= 2025
        assert start_year >= 2000

        path = _prep_output_dir("OSTI_" + str(start_year) + "_" + str(stop_year) + "_" + search_term)

        browser_config, run_config, metadata_config = _get_configs(path)

        progress.log("\n* Crawling OSTI")
        progress.log("* Searching for: " + search_term)
        progress.log("* Documents from " + str(start_year) + " to " + str(stop_year))

        n_successful_crawls = 0
        n_known_crawls = 0
        n_failed_crawls = 0

        # TODO: Start conversion subprocess. User won't need to run `climpdf convert` on output
        if convert:
            progress.log("* Converting PDFs to text.")
            _conversion_process(path)

        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:

            progress.log("* Calculating starting URL")

            # search_base = source_mapping["OSTI"].search_base
            api_base = source_mapping["OSTI"].api_base
            api_payload = source_mapping["OSTI"].api_payload
            api_payload["q"] = search_term
            api_payload["publication_start_date"] = "01/01/" + str(start_year)
            api_payload["publication_end_date"] = "12/31/" + str(stop_year)
            api_payload["fulltext"] = search_term

            # formatted_search_base_init = search_base.format(search_term, stop_year, start_year, 0)
            # url_base = "https://www.osti.gov/servlets/purl/"

            progress.log("* Performing first search")

            # first_result_page = await crawler.arun(url=formatted_search_base_init, config=metadata_config)

            bytes_search_results = requests.get(api_base, params=api_payload).content
            search_results = json.loads(bytes_search_results)
            with open(path / "OSTI.GOV-metadata.json", "w") as f:
                json.dump(search_results, f, indent=4)

            # if first_result_page.downloaded_files:
            #     progress.log("* Metadata collected.")
            # else:
            #     progress.log("* Unable to collect metadata.")

            # first_soup = BeautifulSoup(first_result_page.html, "html.parser")

            # first_result_page_links = _get_result_links(first_result_page, url_base)

            # result_page_links = _get_api_result_links(search_results)
            max_results = len(search_results)
            # max_pages, max_results = _get_max_results(first_soup, counting=False)
            dispatcher = _get_dispatcher(max_results)

            color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
            task = progress.add_task(f"[{color}]" + search_term, total=max_results)

            collected_exceptions = []
            progress.log("* Expecting " + str(max_results) + " documents. Beginning document crawl.")

            # TODO: This should be generated automatically. Currently from `count-local`.
            try:
                known_documents = json.load(open(path.parent / "OSTI_doc_ids.json", "r"))
            except FileNotFoundError:
                known_documents = []

            # for doc_page in first_result_page_links:
            #     if doc_page["href"].split(url_base)[-1] in known_documents:
            #         n_known_crawls += 1
            # first_result_page_links = [
            #     i["href"] for i in first_result_page_links if i["href"].split(url_base)[-1] not in known_documents
            # ]

            for entry in search_results:
                if entry["osti_id"] in known_documents:
                    n_known_crawls += 1
            search_results = [i for i in search_results if i["osti_id"] not in known_documents]

            for result in search_results:
                signal.alarm(60)
                
                fulltext_link = [i["href"] for i in result["links"] if i["rel"] == "fulltext"][0]
                
                try:
                    r = requests.get(fulltext_link, stream=True, timeout=10)
                    r.raise_for_status()
                    token = result.url.split("/")[-1]
                    path_to_doc = path / f"{token}.pdf"
                    with path_to_doc.open("wb") as f:
                        f.write(r.content)
                    progress.update(task, advance=1)
                except:
                    n_failed_crawls += 1
                progress.update(task, advance=1)




            # grouped_search_results = [search_results[i : i + 10] for i in range(0, len(search_results), 10)]

            # for group in grouped_search_results:
            #     signal.alarm(660)  # 11 minutes for each 10 documents, way more time than needed presumably

            #     group_links = [i["links"] for i in group]
            #     fulltext_links = [j["href"] for i in group_links for j in i if j["rel"] == "fulltext"]

            #     results = await crawler.arun_many(urls=fulltext_links, dispatcher=dispatcher, config=run_config)

            #     for result in results:
            #         if result.success and result.pdf:
            #             n_successful_crawls += 1
            #             with open(path / "{}.pdf".format(result.url.split("/")[-1]), "wb") as f:
            #                 f.write(result.pdf)
            #         elif result.success and not result.pdf:
            #             n_known_crawls += 1
            #         else:
            #             n_failed_crawls += 1

            #     progress.update(task, advance=len(results))
            #     sys.exit(0)

            # for doc_page in first_result_page_links:
            #     signal.alarm(60)

            #     # TODO: Does a known-document constitute a failed crawl?
            #     if doc_page["href"].split(url_base)[-1] in known_documents:
            #         n_known_crawls += 1
            #         progress.update(task, advance=1)
            #         continue

            #     try:
            #         _download_document(doc_page, url_base, path, progress, task)
            #         n_successful_crawls += 1

            #     except TimeoutError:
            #         progress.log("Timeout while collecting: " + str(doc_page) + ". Skipping.")
            #         n_failed_crawls += 1
            #         progress.update(task, advance=1)
            #         continue

            #     except Exception as e:
            #         collected_exceptions.append([doc_page["href"], str(e)])
            #         n_failed_crawls += 1
            #         progress.update(task, advance=1)
            #         continue

            # _checkpoint(path, search_term, start_year, stop_year, 0, 0, max_results)

            # progress.log("* Performing subsequent searches")
            # for result_page in range(1, max_pages):
            #     signal.alarm(660)  # 11 minutes - one minute a page, since there's 10 pages max
            #     try:
            #         formatted_search_base = search_base.format(search_term, stop_year, start_year, result_page)
            #         main_result_page = await crawler.arun(url=formatted_search_base, config=run_config)

            #         search_result_links = _get_result_links(main_result_page, url_base)

            #         for doc_page in search_result_links:
            #             if doc_page["href"].split(url_base)[-1] in known_documents:
            #                 n_known_crawls += 1
            #         search_result_links = [
            #             i["href"] for i in search_result_links if i["href"].split(url_base)[-1] not in known_documents
            #         ]

            #         results = await crawler.arun_many(
            #             urls=search_result_links, dispatcher=dispatcher, config=run_config
            #         )

            #         for result in results:
            #             if result.success and result.downloaded_files:
            #                 n_successful_crawls += 1
            #             elif result.success and not result.downloaded_files:
            #                 n_known_crawls += 1
            #             else:
            #                 n_failed_crawls += 1

            #         progress.update(task, advance=len(results))

            # for doc_page in search_result_links:
            #     signal.alarm(60)

            #     if doc_page["href"].split(url_base)[-1] in known_documents:
            #         n_known_crawls += 1
            #         progress.update(task, advance=1)
            #         continue

            #     try:
            #         _download_document(doc_page, url_base, path, progress, task)
            #         n_successful_crawls += 1

            #     except TimeoutError:
            #         progress.log("Timeout while collecting: " + str(doc_page) + ". Skipping.")
            #         n_failed_crawls += 1
            #         progress.update(task, advance=1)
            #         continue

            #     except Exception as e:
            #         collected_exceptions.append([doc_page["href"], str(e)])
            #         n_failed_crawls += 1
            #         progress.update(task, advance=1)

            # except TimeoutError:
            #     progress.log("Timeout on result page: " + str(result_page) + ". Skipping.")
            #     n_failed_crawls += 10
            #     progress.update(task, advance=10)
            #     continue

            # except Exception as e:
            #     collected_exceptions.append([formatted_search_base, str(e)])
            #     n_failed_crawls += 10
            #     progress.update(task, advance=10)
            #     continue

            # _checkpoint(
            #     path,
            #     search_term,
            #     start_year,
            #     stop_year,
            #     result_page,
            #     max_pages,
            #     max_results,
            # )

            progress.log("\n* Successes: " + str(n_successful_crawls))
            progress.log("* Known documents skipped: " + str(n_known_crawls))
            progress.log("* Failures: " + str(n_failed_crawls))
            progress.log("* Exceptions: ")
            for i in collected_exceptions:
                progress.log("* " + str(i[0]) + ": " + str(i[1]) + "\n")

    async def main_multiple_osti(search_terms: list[str], start_year: int, stop_year: int, convert: bool):
        if convert:
            click.echo("* Converting PDFs to text.")

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            await asyncio.gather(
                *[main_osti(search_term, start_year, stop_year, convert, progress) for search_term in search_terms]
            )

    asyncio.run(main_multiple_osti(search_term, start_year, stop_year, convert))


@click.command()
@click.option("--search-term", "-t", multiple=True)
@click.argument("start_year", nargs=1, type=click.INT)
@click.argument("stop_year", nargs=1, type=click.INT)
def count_remote_osti(search_term: list[str], start_year: int = 2000, stop_year: int = 2025):
    """Count potentially downloadable files from OSTI, for any number of search terms. Leave blank for all."""
    import asyncio

    click.echo("* Determining OSTI search result counts.")
    click.echo("* Year range: " + str(start_year) + " to " + str(stop_year))

    async def main_osti(search_term: str, start_year: int, stop_year: int) -> int:

        browser_config, run_config, _ = _get_configs(path)

        async with AsyncWebCrawler(
            config=browser_config,
        ) as crawler:

            search_base = source_mapping["OSTI"].search_base
            formatted_search_base_init = search_base.format(search_term, stop_year, start_year, 0)

            first_result_page = await crawler.arun(url=formatted_search_base_init)

            first_soup = BeautifulSoup(first_result_page.html, "html.parser")

            _, max_results = _get_max_results(first_soup, counting=True)
            click.echo(search_term + ": " + str(max_results))
            return max_results

    async def main_multiple_osti(search_terms: list[str], path: Path, start_year: int, stop_year: int):
        results = await asyncio.gather(*[main_osti(search_term, start_year, stop_year) for search_term in search_terms])
        output = {}
        for i, term in enumerate(search_terms):
            output[term] = results[i]
        with open(path / "osti_counts.json", "w") as f:
            json.dump(output, f)

    path = _prep_output_dir("OSTI_counts")

    if len(search_term) == 1:
        asyncio.run(main_osti(search_term[0], start_year, stop_year))
    elif len(search_term) > 1:
        asyncio.run(main_multiple_osti(search_term, path, start_year, stop_year))
    else:
        asyncio.run(main_multiple_osti(RESILIENCE_SEARCHES, path, start_year, stop_year))


@click.group()
def main():
    pass


main.add_command(crawl_epa)
main.add_command(crawl_osti)
main.add_command(count_local)
main.add_command(convert)
main.add_command(epa_ocr_to_json)
main.add_command(count_remote_osti)

if __name__ == "__main__":
    main()
