import html
import json
import re
import signal
import sys
import unicodedata
from pathlib import Path

import click
from langdetect import LangDetectException, detect
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .utils import _collect_from_path


def is_english(text):
    """
    Returns True if the text is detected as English, False otherwise.
    Handles exceptions for numeric/symbol-only strings or empty text: returns False in those cases.
    """
    if not text or text.strip() == "":
        return False
    try:
        # detect() can throw an exception for numeric/symbol-only text
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

        # Check if the percentage of numeric characters is more than 30%
        if numeric_percentage > 30:
            return False

        # Count the number of special characters in the string
        special_count = len(re.findall(r"[^a-zA-Z0-9]", string))
        # Calculate the percentage of special characters
        special_percentage = (special_count / total_count) * 100

        # Check if the percentage of special characters is more than 30%
        if special_percentage > 30:
            return False

    # If the string doesn't have any digits or special characters, return True
    return True


def _sectionize_workflow(source: Path, progress: Progress):

    collected_input_files = _collect_from_path(Path(source))
    success_count = 0
    fail_count = 0
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    task = progress.add_task("[green]Sectionizing", total=len(collected_input_files))
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    output_dir = Path(str(source) + "_json")
    output_dir.mkdir(exist_ok=True, parents=True)

    failures_json = output_dir / Path("failures.json")
    if failures_json.exists():
        failures = json.loads(failures_json.read_text())
    else:
        failures = []

    for i in collected_input_files:

        signal.alarm(60)
        output_file = output_dir / Path(i.stem + "_processed.json")
        if i.stem in failures:  # skip if already converted, or timed out
            success_count += 1
            progress.update(task, advance=1)
            continue
        try:
            progress.log("* Sectionizing: " + str(i))
            with open(i, "r") as f:
                doc = json.load(f)
            raw_text = doc["response"]["docs"][0]["text"][0]

            indexes = []
            headers = []

            splitlines = raw_text.splitlines()
            for index, line in enumerate(splitlines):
                # single line of text between two newlines. likely a header
                if (
                    len(line.split()) > 1
                    and len(line.split()) < 10
                    and not len(splitlines[index - 1])
                    and not len(splitlines[index + 1])
                ):
                    indexes.append([index])
                    headers.append(line)

            headers_to_lower = [header.lower() for header in headers]
            if "abstract" in headers_to_lower:  # remove all content before abstract, if found
                abstract_index = headers_to_lower.index("abstract")
                headers = headers[abstract_index:]
                indexes = indexes[abstract_index:]

            indexes.append([len(raw_text)])
            index_pairs = [(i[-1], j[0]) for i, j in zip(indexes, indexes[1:])]
            sectioned_text = {}

            actual_headers = 0
            for i, (start, end) in enumerate(index_pairs):
                header = headers[i]
                if not is_english(header) or not is_string_valid(header):
                    continue
                section = splitlines[start:end]
                new_section = [j for j in section if j not in [header, "\n", "", [], "  "]]
                combined_new_section = "".join(new_section).replace("  ", " ")
                new_section = [unicodedata.normalize("NFD", i) for i in combined_new_section]
                new_section = [html.unescape(i) for i in new_section]
                if is_english("".join(new_section)) and is_string_valid(
                    "".join(new_section)
                ):  # skip if too much text is numeric
                    actual_headers += 1
                    sectioned_text[header] = "".join(new_section)

            progress.log("Found " + str(actual_headers) + " actual headers.")

            unneeded_sections = [
                "abstract",
                "caption",
                "figure",
                "table",
                "acknowledgments",
                "acknowledgements",
                "references",
                "bibliography",
                "author contributions",
                "author affiliations",
                "keywords",
            ]

            for section in unneeded_sections:
                if section in headers_to_lower:
                    for head in list(sectioned_text.keys()):  # since a key may be in any case
                        if section in head.lower():
                            del sectioned_text[head]

            with open(output_file, "w") as f:
                json.dump(sectioned_text, f, indent=4)

        except TimeoutError:
            progress.log("* Timed out on: " + str(i))
            failures.append(i.stem)
            fail_count += 1
            progress.update(task, advance=1)
            continue

        except KeyboardInterrupt:
            progress.log("* Stopped on: " + str(i))
            with open(failures_json, "w") as f:
                json.dump(failures, f)
            sys.exit()

        except Exception as e:
            progress.log("* Error on: " + str(i))
            progress.log("* Error: " + str(e))
            failures.append(i.stem)
            fail_count += 1
            progress.update(task, advance=1)
            continue

        success_count += 1
        progress.update(task, advance=1)

    progress.log("\n* Sectionization:")
    progress.log("* Successes: " + str(success_count))
    progress.log("* Failures: " + str(len(failures)))
    progress.log("* Failures: " + str(failures))


@click.command()
@click.argument("source", nargs=1)
def process_dataset(source: Path):
    """Preprocess full-text files in s2orc/pes2o format.

    NOTE: Each file is assumed to contain one result.
    """

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress)
