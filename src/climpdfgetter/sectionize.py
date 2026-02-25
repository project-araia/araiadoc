import html
import json
import re
import unicodedata
from pathlib import Path

import click
from joblib import Parallel, delayed
from langdetect import LangDetectException, detect
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .utils import _collect_from_path

NUMERIC_SPECIAL_THRESHOLD = 30


unneeded_sections_no_skip_remaining = [
    # "abstract",
    "caption",
    "figure",
    "table",
    "authorcontribution",
    "authoraffiliation",
    "keyword",
    "disclaimer",
    "fig",
    "deleted",
    "http",
]

needed_sections_but_skip_remaining = ["conclusion"]

unneeded_sections_skip_remaining = [
    "acknowledgment",
    "acknowledgement",
    "reference",
    "bibliography",
    "dataavailability",
    "codeavailability",
    "funding",
    "pre-publicationhistory",
    "ethicstatement",
    "ethicsstatement",
    "grantinformation",
    "competinginterests",
    "conflictsofinterest",
    "supplementarymaterial",
    "disclosurestatement",
    "abbreviation",
    "appendix",
    "howtoreference",
    "cited",
    "contributionstatement",
    "modelavailability",
    "codeavailability",
    "supportinginformation",
    "declarationofinterest",
    "citationinformation",
    "orcid",
    "notesoncontributors",
    "forpeerreview",
    "appendice",
    "nomenclature",
    "glossary",
    "notation",
    "symbol",
    "openaccess",
]


def is_english(text):
    """
    Returns True if the text is detected as English, False otherwise.
    Handles exceptions for numeric/symbol-only strings or empty text: returns False in those cases.
    """
    if not text or text.strip() == "":
        return False
    try:
        return detect(text) == "en"
    except LangDetectException:
        return False


def is_string_valid(string):
    # Check if the string contains at least one digit
    if re.search(r"\d", string):
        # Count the number of digits in the string
        digit_count = len(re.findall(r"\d", string))
        # Count the total number of characters in the string
        total_count = len(string)
        # Calculate the percentage of numeric characters
        numeric_percentage = (digit_count / total_count) * 100

        # Check if the percentage of numeric characters is more than NUMERIC_SPECIAL_THRESHOLD%
        if numeric_percentage > NUMERIC_SPECIAL_THRESHOLD:
            return False

        # Count the number of special characters in the string
        special_count = len(re.findall(r"[^a-zA-Z0-9]", string))
        # Calculate the percentage of special characters
        special_percentage = (special_count / total_count) * 100

        # Check if the percentage of special characters is more than NUMERIC_SPECIAL_THRESHOLD%
        if special_percentage > NUMERIC_SPECIAL_THRESHOLD:
            return False

    # If the string doesn't have any digits or special characters, return True
    return True


def _line_spacing_resembles_header(line, splitlines, index):
    if index < 2 or index >= len(splitlines) - 1:
        return False
    if (
        len(line.split()) >= 1
        and len(line.split()) < 15
        and not len(splitlines[index - 1])
        and not len(splitlines[index - 2])
        and not len(splitlines[index + 1])
    ):
        return True
    elif (
        len(line.split()) >= 1
        and not len(splitlines[index - 1])
        and not len(splitlines[index - 2])
        and "abstract" in line.lower()
    ):
        return True
    return False


def _get_valid_sections(section):
    return [j for j in section if is_english(j) and is_string_valid(j)]


def _get_invalid_sections(section):
    return [j for j in section if not is_english(j) or not is_string_valid(j)]


def _sectionize_one_file(
    input_path: Path,
    output_dir: Path,
    rejected: bool = False,
    v2: bool = False,
):
    output_file = output_dir / Path(input_path.stem + ".json")
    if rejected:
        output_rejected_file = output_dir / Path(input_path.stem + "_rejected.json")

    try:
        with open(input_path, "r") as f:
            doc = json.load(f)

        # Handle Solr response format vs flat format
        if "response" in doc and "docs" in doc["response"] and doc["response"]["docs"]:
            item = doc["response"]["docs"][0]
        else:
            item = doc

        def get_first(field):
            val = item.get(field, [""])
            if isinstance(val, list) and len(val) > 0:
                return val[0]
            return val if isinstance(val, str) else ""

        title = get_first("title")
        abstract = get_first("abstract")
        raw_text = get_first("text")
        paragraphs = item.get("paragraph", [])
        section_headers = item.get("sectionheader", [])

        # If no raw text but we have paragraphs, join them for extraction if needed
        if not raw_text and paragraphs:
            raw_text = "\n\n".join(paragraphs)

        sectioned_text = {}
        if title:
            sectioned_text["title"] = title
        if abstract:
            sectioned_text["abstract"] = abstract

        rejected_paragraphs = []
        actual_headers_count = 0

        def process_content(header, content):
            nonlocal actual_headers_count
            compare_header = "".join(header.split()).lower()

            if any([j in compare_header for j in unneeded_sections_skip_remaining]):
                return "STOP_ALL"

            should_stop_after = any([j in compare_header for j in needed_sections_but_skip_remaining])

            if should_stop_after or not any([j in compare_header for j in unneeded_sections_no_skip_remaining]):
                if isinstance(content, list):
                    content = "\n\n".join(content)

                # Normalize and clean
                content = unicodedata.normalize("NFD", content)
                content = html.unescape(content).replace("  ", " ")

                if is_english(content) and is_string_valid(content):
                    sectioned_text[header] = content
                    actual_headers_count += 1
                else:
                    rejected_paragraphs.append(content)

                return "STOP_AFTER" if should_stop_after else "CONTINUE"
            else:
                rejected_paragraphs.append(content)
                return "CONTINUE"

        if v2 and section_headers and paragraphs:
            # v2 logic: use provided headers and paragraphs
            for header, content in zip(section_headers, paragraphs):
                res = process_content(header, content)
                if res == "STOP_ALL" or res == "STOP_AFTER":
                    break
        else:
            # v1 logic: extract headers from raw_text
            if not raw_text:
                return (False, input_path.stem, "No text found to sectionize")

            splitlines = raw_text.splitlines()
            indexes = []
            headers = []

            for index, line in enumerate(splitlines):
                if _line_spacing_resembles_header(line, splitlines, index):
                    indexes.append(index)
                    headers.append(line)

            # skip everything before abstract
            for i, header in enumerate(headers):
                if "abstract" in header.lower():
                    headers = headers[i + 1 :]  # noqa
                    indexes = indexes[i + 1 :]  # noqa
                    break

            # Process ranges between headers
            for i, start in enumerate(indexes):
                end = indexes[i + 1] if i + 1 < len(indexes) else len(splitlines)
                header = headers[i]
                section_content = [lines for lines in splitlines[start:end] if lines not in [header, "", " ", "  "]]
                res = process_content(header, section_content)
                if res == "STOP_ALL" or res == "STOP_AFTER":
                    break

        # Check if we found anything useful besides title/abstract
        content_keys = [k for k in sectioned_text.keys() if k not in ["title", "abstract"]]
        if not content_keys and actual_headers_count == 0:
            return (False, input_path.stem, "No valid content sections found")

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        if rejected:
            with open(output_rejected_file, "w") as f:
                json.dump(rejected_paragraphs, f, indent=4)

        return (True, input_path.stem, None)

    except Exception as e:
        return (False, input_path.stem, str(e))


def _sectionize_workflow(source: Path, progress: Progress, rejected: bool = False, v2: bool = False):

    collected_input_files = _collect_from_path(Path(source))
    success_count = 0
    fail_count = 0
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    task = progress.add_task("[green]Sectionizing", total=len(collected_input_files))
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    output_dir = Path(str(source) + "_sectionized")
    output_dir.mkdir(exist_ok=True, parents=True)

    failures_json = output_dir / Path("failures.json")
    if failures_json.exists():
        failures = json.loads(failures_json.read_text())
    else:
        failures = []

    # Filter out already processed or failed files
    files_to_process = []
    for i in collected_input_files:
        if i.stem in failures:
            success_count += 1
            progress.update(task, advance=1)
            continue
        files_to_process.append(i)

    # Run in parallel
    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_one_file)(i, output_dir, rejected, v2) for i in files_to_process
    )

    for success, stem, error in results:
        progress.update(task, advance=1)
        if success:
            success_count += 1
        else:
            fail_count += 1
            failures.append(stem)
            progress.log(f"* Error on: {stem}: {error}")

    # Save failures
    if failures:
        with open(failures_json, "w") as f:
            json.dump(failures, f)

    progress.log("\n* Sectionization:")
    progress.log("* Successes: " + str(success_count))
    progress.log("* Failures: " + str(len(failures)))
    progress.log("* Failures: " + str(failures))


@click.command()
@click.argument("source", nargs=1)
@click.option("--dump_rejected", "rejected", is_flag=True, default=False)
def section_dataset(source: Path, rejected: bool = False):
    """Preprocess full-text files in s2orc/pes2o format into headers and subsections.

    NOTE: Each file is assumed to contain one result.
    """

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress, rejected, False)


@click.command()
@click.argument("source", nargs=1)
@click.option("--dump_rejected", "rejected", is_flag=True, default=False)
def section_dataset_v2(source: Path, rejected: bool = False):
    """Preprocess full-text files in s2orc/pes2o format into headers and subsections.

    Unlike v1, the input files are assumed to contain an "abstract" field,
    a "paragraph" field containing a list of paragraphs, a "title" field, and a
    "sectionheader" field containing a list of section headers. The section headers
    are assumed to be in the same order as the paragraphs, and they'll be compared against a
    a similar heuristic as v1. The main difference is that the section headers are
    provided, so we don't have to extract them from the text.

    NOTE: Each file is assumed to contain one result.
    """

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress, rejected, True)
