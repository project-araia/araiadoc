import datetime
import json
from pathlib import Path

import click
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=20,
        pool_maxsize=20,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["Accept-Encoding"] = "gzip"
    return session


def _count_local(source: str):
    ids = []
    data_root = Path(_find_project_root()) / Path("data/")
    for directory in data_root.iterdir():
        if directory.is_dir() and directory.name.startswith(source):
            for doc in directory.iterdir():
                if doc.stem.isdigit():
                    ids.append(doc.stem)
    ids = sorted(set(ids))
    with open(data_root / f"{source}_doc_ids.json", "w") as f:
        json.dump(ids, f)
    click.echo(len(ids))
    return len(ids)


@click.command()
@click.argument("source", nargs=1)
def count_local(source: str):
    """Count the number of downloaded files from a given source."""
    return _count_local(source)


def _get_max_results(soup, counting: bool) -> tuple[int, int]:
    find = soup.find(class_="breadcrumb-item text-muted active")
    if find is None:
        return 1, 1
    max_pages_soup = find.getText().split()[-1]
    # <span class="breadcrumb-item text-muted active">Page 1 of 54</span></nav>
    max_pages = int("".join(max_pages_soup.split(",")))

    max_results_soup = soup.find("h1").getText().split()[0]
    # <div class="col-12 col-md-5"><h1>535 Search Results</h1></div>
    max_results = int("".join(max_results_soup.split(",")))  # handle results like '1,000'

    if max_results >= 1000 and not counting:
        click.echo("* More than 1000 results found. Due to OSTI limitations only the first 1000 are available.")
        click.echo("* Try adjusting the year range on future crawls.")
    return max_pages, max_results


def _get_configs(path: Path):
    from crawl4ai import BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=True,
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
        headers={"Accept-Language": "en-US"},
        accept_downloads=True,
        downloads_path=path,
    )

    run_config = CrawlerRunConfig(
        # exclude_external_links=True,
        simulate_user=True,
        magic=True,
        pdf=True,
        wait_for_images=True,
        stream=True,
        wait_for="""
            document.readyState === "complete"
        """,
    )

    metadata_config = CrawlerRunConfig(
        # exclude_external_links=True,
        simulate_user=True,
        magic=True,
        # wait_for_images=True,
        # js_code="""
        #     document.querySelector('a.export-link[data-format="json"]').click()
        # """,
        # wait_for="""
        #     document.readyState === "complete"
        # """,
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
    click.echo(f"Output directory: {path}")
    return path


def _prep_path(item: Path):
    if (
        item.is_file() and not item.name.startswith(".") and not item.suffix == ".txt"
    ):  # avoid .DS_store and other files
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
