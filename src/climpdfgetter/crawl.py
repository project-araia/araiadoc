import asyncio
import csv
import json
import random
import re
import signal
from pathlib import Path

import click
import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from semanticscholar import AsyncSemanticScholar

from climpdfgetter.convert import convert, epa_ocr_to_json
from climpdfgetter.extract_references import extract_refs
from climpdfgetter.metadata import get_abstracts_from_solr, get_metadata_from_database
from climpdfgetter.schema import ParsedDocumentSchema
from climpdfgetter.searches import RESILIENCE_SEARCHES
from climpdfgetter.sectionize import section_dataset
from climpdfgetter.sources import source_mapping
from climpdfgetter.utils import (
    _collect_from_path,
    _find_project_root,
    _get_configs,
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
@click.option("--search-term", "-t", multiple=True)
def crawl_osti(start_year: int, search_term: list[str]):
    """Asynchronously crawl OSTI result pages:

    `climpdf crawl-osti 2000 2005 -t "Heat Waves" -t Flooding`

    """
    import asyncio

    async def main_osti(search_term: str, start_year: int, progress):

        stop_year = 2025

        path = _prep_output_dir("OSTI_" + str(start_year) + "_" + str(stop_year) + "_" + search_term)

        browser_config, run_config, metadata_config = _get_configs(path)

        progress.log("\n* Crawling OSTI")
        progress.log("* Searching for: " + search_term)
        progress.log("* Documents from " + str(start_year) + " to " + str(stop_year))

        n_successful_crawls = 0
        n_known_crawls = 0
        n_failed_crawls = 0

        api_base = source_mapping["OSTI"].api_base
        api_payload = source_mapping["OSTI"].api_payload
        api_payload["q"] = search_term
        api_payload["publication_start_date"] = "01/01/" + str(start_year)
        api_payload["publication_end_date"] = "12/31/" + str(stop_year)
        api_payload["fulltext"] = search_term

        progress.log("* Performing first search")

        bytes_search_results = requests.get(api_base, params=api_payload).content
        search_results = json.loads(bytes_search_results)
        with open(path / "OSTI.GOV-metadata.json", "w") as f:
            json.dump(search_results, f, indent=4)

        max_results = len(search_results)

        color = random.choice(["red", "green", "blue", "yellow", "magenta", "cyan"])
        task = progress.add_task(f"[{color}]" + search_term, total=max_results)

        collected_exceptions = []
        progress.log("* Expecting " + str(max_results) + " documents. Beginning document crawl.")

        # TODO: This should be generated automatically. Currently from `count-local`.
        try:
            known_documents = json.load(open(path.parent / "OSTI_doc_ids.json", "r"))
        except FileNotFoundError:
            known_documents = []

        for entry in search_results:
            if entry["osti_id"] in known_documents:
                n_known_crawls += 1
        search_results = [i for i in search_results if i["osti_id"] not in known_documents]
        progress.log("* Number Known documents skipping: " + str(n_known_crawls))

        for result in search_results:
            signal.alarm(60)

            fulltext_link = [i["href"] for i in result["links"] if i["rel"] == "fulltext"][0]

            try:
                r = requests.get(fulltext_link, stream=True, timeout=10)
                r.raise_for_status()
                token = fulltext_link.split("/")[-1]
                path_to_doc = path / f"{token}.pdf"
                with path_to_doc.open("wb") as f:
                    f.write(r.content)
                n_successful_crawls += 1
            except Exception as e:
                n_failed_crawls += 1
                collected_exceptions.append([fulltext_link, str(e)])
            progress.update(task, advance=1)

        progress.log("\n* Successes: " + str(n_successful_crawls))
        progress.log("* Failures: " + str(n_failed_crawls))
        progress.log("* Exceptions: ")
        for i in collected_exceptions:
            progress.log("* " + str(i[0]) + ": " + str(i[1]) + "\n")

    async def main_multiple_osti(search_terms: list[str], start_year: int):

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            await asyncio.gather(*[main_osti(search_term, start_year, progress) for search_term in search_terms])

    asyncio.run(main_multiple_osti(search_term, start_year))


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
            await asyncio.sleep(1)
            first_result_page = await crawler.arun(url=formatted_search_base_init, config=run_config)
            await asyncio.sleep(1)

            first_soup = BeautifulSoup(first_result_page.html, "html.parser")

            _, max_results = _get_max_results(first_soup, counting=True)
            click.echo(search_term + ": " + str(max_results))
            return max_results

    async def main_multiple_osti(search_terms: list[str], path: Path, start_year: int, stop_year: int):
        results = await asyncio.gather(*[main_osti(search_term, start_year, stop_year) for search_term in search_terms])
        output = {}
        for i, term in enumerate(search_terms):
            output[term] = results[i]
        while any([output[i] == 1 for i in output]):
            # retry if any of the counts are 1
            retrying_search_terms = [i for i in output if output[i] == 1]
            click.echo("* Retrying: " + str(retrying_search_terms))
            results = await asyncio.gather(
                *[main_osti(search_term, start_year, stop_year) for search_term in retrying_search_terms]
            )
            for i, term in enumerate(retrying_search_terms):
                output[term] = results[i]
        click.echo("Total: " + str(sum(output.values())))
        output["Total"] = sum(output.values())
        with open(path / "osti_counts.json", "w") as f:
            json.dump(output, f)

    path = _prep_output_dir("OSTI_counts")

    if len(search_term) == 1:
        asyncio.run(main_osti(search_term[0], start_year, stop_year))
    elif len(search_term) > 1:
        asyncio.run(main_multiple_osti(search_term, path, start_year, stop_year))
    else:
        asyncio.run(main_multiple_osti(RESILIENCE_SEARCHES, path, start_year, stop_year))


def _chunk_list(data, n):
    if not data:
        return []
    chunk_size = max(1, len(data) // n)
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa


async def _get_document(paper_id, semaphore, asch):
    async with semaphore:
        return await asch.get_paper("CorpusID:" + str(paper_id))


async def _process_combined_chunk(
    data_chunk, metadata_map, checkpoint_data, lock, subdir, progress, task, color, semaphore=None, asch=None
):
    import ast

    for file_path in data_chunk:
        try:
            if file_path is None:
                continue

            stem = file_path.stem
            corpus_id = stem.replace("_processed", "")

            if corpus_id in checkpoint_data:
                progress.update(task, advance=1)
                continue

            meta = None
            paper = None

            # Try to get metadata from CSV map
            if metadata_map and corpus_id in metadata_map:
                meta = metadata_map[corpus_id]

            # If not found, try API if allowed
            if not meta and asch:
                try:
                    async with semaphore:
                        paper = await asch.get_paper("CorpusID:" + str(corpus_id))
                except Exception:
                    # progress.log(f"[{color}]API Error for {corpus_id}: {e}")
                    pass

            if not meta and not paper:
                # progress.log(f"[{color}]ID {corpus_id} not found in metadata or API.")
                progress.update(task, advance=1)
                continue

            # Prepare fields
            title = ""
            abstract = ""
            year = 0
            authors_list = []

            if meta:
                title = meta["title"]
                abstract = meta["abstract"]
                year = meta["year"] if meta["year"] else 0

                try:
                    raw_authors = meta["authors"]
                    if raw_authors:
                        authors_data = ast.literal_eval(raw_authors)
                        for au in authors_data:
                            name = f"{au.get('first', '')} {au.get('last', '')}".strip()
                            if name:
                                authors_list.append(name)
                except Exception:
                    pass
            elif paper:
                title = paper.title
                abstract = paper.abstract
                year = paper.year
                authors_list = [author.name for author in paper.authors]

            # Read text content
            with open(file_path, "r") as f:
                text_content = json.load(f)

            final_text = text_content if isinstance(text_content, dict) else {}

            schema = ParsedDocumentSchema(
                source="Semantic Scholar",
                title=title,
                text=final_text,
                abstract=abstract,
                authors=authors_list,
                publisher="",
                date=year,
                unique_id=corpus_id,
                doi="",
                references="",
            )

            out_path = subdir / f"{corpus_id}.json"
            with open(out_path, "w") as f:
                f.write(json.dumps(schema.model_dump(mode="json", by_alias=True)))

            async with lock:
                checkpoint_data.append(corpus_id)

            progress.update(task, advance=1)

        except Exception as e:
            progress.log(f"[{color}]Error processing {file_path}: {e}")
            progress.update(task, advance=1)


async def _process_api_chunk(
    data_chunk,
    input_format,
    output_format,
    checkpoint_data,
    semaphore,
    subdir,
    progress,
    task,
    color,
):
    asch = AsyncSemanticScholar()

    if input_format == "csv":
        work_tasks = [asyncio.create_task(_get_document(doc[6], semaphore, asch)) for doc in data_chunk]
    elif input_format == "checkpoint":
        work_tasks = [asyncio.create_task(_get_document(doc, semaphore, asch)) for doc in data_chunk]
    elif input_format == "pes2o":
        stems = [i.stem for i in data_chunk]
        work_tasks = [asyncio.create_task(_get_document(stem, semaphore, asch)) for stem in stems]

    for paper_task in asyncio.as_completed(work_tasks):
        try:
            paper = await paper_task

            if paper is None:
                continue

            if output_format == "pdf":
                if not paper["isOpenAccess"]:
                    continue

                if paper["openAccessPdf"]["status"] != "GOLD":  # pdf likely undownloadable
                    continue

                pdf_url = paper["openAccessPdf"]["url"]
                pdf_name = paper["corpusId"]
                pdf_path = subdir / Path(str(pdf_name) + ".pdf")
                if not pdf_path.exists() and pdf_name not in checkpoint_data:
                    r = requests.get(pdf_url, stream=True, timeout=10)
                    r.raise_for_status()
                    with pdf_path.open("wb") as f:
                        f.write(r.content)

            elif output_format == "metadata":

                if input_format == "pes2o":
                    # TODO: Associate metadata from SemanticScholar with input pes2o dataset
                    schema = ParsedDocumentSchema(
                        source="Semantic Scholar",
                        title=paper["title"],
                        text={"abstract": paper["abstract"]} if paper["abstract"] else {},
                        abstract=paper["abstract"],
                        authors=paper["authors"],
                        publisher=paper["publisher"],
                        date=paper["year"],
                        unique_id=paper["corpusId"],
                        doi=paper["doi"],
                        references=paper["references"],
                    )

                    metadata_path = subdir / Path(str(paper["corpusId"]) + ".json")
                    if not metadata_path.exists() and paper["corpusId"] not in checkpoint_data:
                        with metadata_path.open("w") as f:
                            f.write(json.dumps(schema))

                else:
                    schema = ParsedDocumentSchema(
                        source="Semantic Scholar",
                        title=paper.title,
                        text={},
                        abstract=paper.abstract,
                        authors=paper.authors,
                        publisher=paper.journal["name"],
                        date=paper.year,
                        unique_id=paper.corpusId,
                        doi=paper["doi"],
                        references=paper.references,
                    )
                    metadata_path = subdir / Path(str(paper["corpusId"]) + ".json")
                    if not metadata_path.exists():
                        with metadata_path.open("w") as f:
                            f.write(json.dump(schema.model_dump(mode="json", by_alias=True)))

            checkpoint_data.append(paper["corpusId"])

        except KeyboardInterrupt:
            progress.log("KeyboardInterrupt")
            if output_format == "pdf":
                checkpoint_data.extend([doc[6] for doc in data_chunk])
            else:
                checkpoint_data.extend([doc for doc in data_chunk])
            return
        except Exception as e:
            progress.log("Error: " + str(e))
            progress.update(task, advance=1)
            if output_format == "pdf":
                checkpoint_data.extend([doc[6] for doc in data_chunk])
            else:
                checkpoint_data.extend([doc for doc in data_chunk])
            continue
        progress.update(task, advance=1)


@click.command()
@click.argument("input_file", nargs=1, type=click.Path(exists=True))
@click.option(
    "--input_format", "-i", nargs=1, type=click.Choice(["csv", "checkpoint", "pes2o", "combined"]), default="checkpoint"
)
@click.option("--input_metadata_file", "-m", nargs=1, type=click.Path(exists=True))
@click.option("--output_format", "-o", nargs=1, type=click.Choice(["metadata", "pdf", "combined"]), default="combined")
@click.option("-nproc", "-n", nargs=1, type=click.INT, default=1)
def complete_semantic_scholar(
    input_file: Path, input_format: str, input_metadata_file: Path, output_format: str, nproc: int
):
    """
    Given an input file or directory, containing either:
        1. A CSV with the following columns: `lineno,abstract,score,year,field,title,paper_id,authors`
        2. A `.json` file containing a list of semantic scholar corpus IDs
        3. A directory containing multiple subdirectories of pes2o files

    Download either:
        1. PDFs from Semantic Scholar
        2. Metadata from Semantic Scholar

    and match them with the input data.
    """

    async def _complete_semantic_scholar(
        chunk_idx,
        data_chunk,
        output_dir,
        progress,
        checkpoint_data,
        lock,
        semaphore,
        output_format,
        metadata_map=None,
    ):

        subdir = output_dir / Path("chunk_" + str(chunk_idx))
        subdir.mkdir(exist_ok=True)

        color = ["red", "green", "blue", "yellow", "magenta", "cyan"][chunk_idx % 6]
        task = progress.add_task(f"[{color}]Chunk " + str(chunk_idx) + ": ", total=len(data_chunk))

        if output_format == "combined":
            asch = AsyncSemanticScholar() if input_format == "combined" else None

            if not metadata_map and input_format != "combined":
                progress.log(f"[{color}]Error: Metadata map is empty and fallback logic disabled.")
                return

            await _process_combined_chunk(
                data_chunk, metadata_map, checkpoint_data, lock, subdir, progress, task, color, semaphore, asch
            )
        else:
            await _process_api_chunk(
                data_chunk,
                input_format,
                output_format,
                checkpoint_data,
                semaphore,
                subdir,
                progress,
                task,
                color,
            )

    async def main_multiple_ss(input_file, input_format, input_metadata_file, output_format, nproc):

        path = _prep_output_dir("SEMANTIC_SCHOLAR_complete")
        checkpoint = path.parent / Path("SS_checkpoint.json")
        if not checkpoint.exists():
            checkpoint.touch()
            checkpoint_data = []
        else:
            try:
                checkpoint_data = checkpoint.read_text()
                checkpoint_data = json.loads(checkpoint_data)
            except json.decoder.JSONDecodeError:
                checkpoint_data = []
        click.echo(f"Loaded {len(checkpoint_data)} processed IDs from checkpoint.")

        checkpoint_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(nproc)

        # split data into 2 equal chunks

        if input_format == "pes2o" or input_format == "combined":
            data = _collect_from_path(Path(input_file))
            # Ignore rejected files
            data = [f for f in data if not f.name.endswith("_rejected.json")]
            click.echo(f"Found {len(data)} input files.")

            chunk_size = len(data) // nproc
            chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa

        if input_format == "csv" or input_format == "checkpoint":
            with open(input_file, "r") as f:
                if input_format == "csv":
                    reader = csv.reader(f)
                    # data = list(reader)
                    data = list(reader)[1:]  # first line is header
                    chunk_size = len(data) // nproc
                    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]  # noqa
                elif input_format == "checkpoint":
                    try:
                        with open(input_file, "r") as f:
                            checkpoint_data = json.load(f)
                    except json.decoder.JSONDecodeError:
                        checkpoint_data = []
                    chunk_size = len(checkpoint_data) // nproc
                    chunks = [
                        checkpoint_data[i : i + chunk_size] for i in range(0, len(checkpoint_data), chunk_size)  # noqa
                    ]

        metadata_map = {}
        if output_format == "combined":
            if input_metadata_file:  # Only load if provided
                click.echo("Loading metadata map...")
                with open(input_metadata_file, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Assuming paper_id is the key
                        metadata_map[row["paper_id"]] = row
                click.echo(f"Loaded {len(metadata_map)} metadata entries.")
            elif input_format != "combined":
                click.echo(
                    "Error: --input_metadata_file / -m required for combined output unless input_format is 'combined'."
                )
                return

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn(), disable=True) as progress:
            await asyncio.gather(
                *[
                    _complete_semantic_scholar(
                        i,
                        chunk,
                        path,
                        progress,
                        checkpoint_data,
                        checkpoint_lock,
                        semaphore,
                        output_format,
                        metadata_map,
                    )
                    for i, chunk in enumerate(chunks)
                ]
            )

        with open(checkpoint, "w") as f:
            f.write(json.dumps(checkpoint_data))

    asyncio.run(main_multiple_ss(input_file, input_format, input_metadata_file, output_format, nproc))


@click.group()
def main():
    pass


main.add_command(crawl_epa)
main.add_command(crawl_osti)
main.add_command(complete_semantic_scholar)
main.add_command(count_local)
main.add_command(convert)
main.add_command(epa_ocr_to_json)
main.add_command(count_remote_osti)
main.add_command(section_dataset)
main.add_command(get_metadata_from_database)
main.add_command(get_abstracts_from_solr)
main.add_command(extract_refs)

if __name__ == "__main__":
    main()
