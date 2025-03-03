import datetime
import re
from pathlib import Path

# regex from https://www.geeksforgeeks.org/python-check-url-string/ - cant answer any questions about it :)
URL_RE = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"  # noqa


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
