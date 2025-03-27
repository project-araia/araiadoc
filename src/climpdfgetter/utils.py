import datetime
import json
import re
from pathlib import Path

import click
import requests

# regex from https://www.geeksforgeeks.org/python-check-url-string/ - cant answer any questions about it :)
URL_RE = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"  # noqa


def _get_downloaded_source_doc_ids(source: str):
    ids = []
    data_root = Path(_find_project_root()) / Path("data/")
    for directory in data_root.iterdir():
        if directory.is_dir() and directory.name.startswith(source):
            for doc in directory.iterdir():
                ids.append(doc.stem)
    with open(data_root / f"{source}_doc_ids.json", "w") as f:
        json.dump(ids, f)


def _count_local(source: str):
    total = 0
    data_root = Path(_find_project_root()) / Path("data/")
    for directory in data_root.iterdir():
        if directory.is_dir() and directory.name.startswith(source):
            total += len(list(directory.iterdir()))
    click.echo(total)
    return total


@click.command()
@click.argument("source", nargs=1)
def count_local(source: str):
    """Count the number of downloaded files from a given source."""
    return _count_local(source)


def _checkpoint(
    path,
    search_term: str,
    start_year: int,
    stop_year: int,
    result_page: int,
    max_pages: int,
    max_results: int,
):

    with open(path / "checkpoint.json", "w") as f:
        json.dump(
            {
                "search_term": search_term,
                "start_year": start_year,
                "stop_year": stop_year,
                "last_result_page": result_page,
                "max_pages": max_pages,
                "max_results": max_results,
            },
            f,
        )


def _get_result_links(result_page: dict, url_base: str):
    return [i for i in result_page.links["internal"] if i["href"].startswith(url_base)]


def _get_max_results(soup, counting: bool) -> tuple[int, int]:
    max_pages_soup = soup.find(class_="breadcrumb-item text-muted active").getText().split()[-1]
    # <span class="breadcrumb-item text-muted active">Page 1 of 54</span></nav>
    max_pages = int("".join(max_pages_soup.split(",")))

    max_results_soup = soup.find("h1").getText().split()[0]
    # <div class="col-12 col-md-5"><h1>535 Search Results</h1></div>
    max_results = int("".join(max_results_soup.split(",")))  # handle results like '1,000'

    if max_results >= 1000 and not counting:
        click.echo("* More than 1000 results found. Due to OSTI limitations only the first 1000 are available.")
        click.echo("* Try adjusting the year range on future crawls.")
    return max_pages, max_results


def _download_document(doc_page: dict, url_base: str, path: Path, t):
    token = doc_page["href"].split(url_base)[-1]  # https://www.osti.gov/servlets/purl/1514957
    r = requests.get(doc_page["href"], stream=True)
    path_to_doc = path / f"{token}.pdf"
    with path_to_doc.open("wb") as f:
        f.write(r.content)
    t.update(1)


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


def _find_project_root() -> str:
    """Find the project root directory."""
    root_dir = Path(__file__).resolve().parents[2]
    return str(root_dir)


def _prep_output_dir(name: str) -> Path:
    single_crawl_dir = name + "_" + datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    path = Path(_find_project_root()) / Path("data/" + single_crawl_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_url_dominant(text: str):
    """if more than a third of the characters in the subsection belong to URLs, return True"""
    all_urls = re.findall(URL_RE, text)
    all_urls_chars = "".join([i[0] for i in all_urls])
    if len(all_urls_chars) > len(text) / 3:
        return True
    return False


def _strip_urls(text: str):
    """remove URLs from text"""
    all_urls = re.findall(URL_RE, text)
    all_urls = [i[0] for i in all_urls]
    for i in all_urls:
        text = text.replace(i, "")
    return text


def _strip_phone_numbers(text: str):
    """remove phone numbers from text"""
    all_phone_numbers = re.findall(
        r"(\d{3}[-.]?\d{3}[-.]?\d{4}|\(\d{3}\)\s*\d{3}[-.]?\d{4}|\d{3}[-.]?\d{4})",
        text,
    )
    for i in all_phone_numbers:
        text = text.replace(i, "")
    return text


def _strip_sequential_nonalphanumeric(text: str):
    """remove groups of 3+ consecutive non-alphanumeric characters from text"""
    all_groups = re.findall("[^a-zA-Z0-9]{3,}", text)
    for i in all_groups:
        text = text.replace(i, " ")
    return text


def _prep_path(item: Path):
    if item.is_file() and not item.name.startswith("."):  # avoid .DS_store and other files
        return Path(item)


def _collect_from_path(path: Path):

    collected_input_files = []

    for directory in path.iterdir():
        if directory.is_dir():
            for item in directory.iterdir():
                collected_input_files.append(_prep_path(item))
        else:
            collected_input_files.append(_prep_path(directory))

    return collected_input_files
