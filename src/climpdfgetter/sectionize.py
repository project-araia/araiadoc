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
    "abstract",
    "caption",
    "figure",
    "table",
    "author contribution",
    "author affiliation",
    "keyword",
    "disclaimer",
]

needed_sections_but_skip_remaining = ["conclusion"]

unneeded_sections_skip_remaining = [
    "acknowledgment",
    "acknowledgement",
    "reference",
    "bibliography",
    "data availability",
    "code availability",
    "funding",
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
    if (
        len(line.split()) >= 1
        and len(line.split()) < 15
        and not len(splitlines[index - 1])
        and not len(splitlines[index - 2])
        and not len(splitlines[index + 1])
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
):
    output_file = output_dir / Path(input_path.stem + "_processed.json")
    output_rejected_file = output_dir / Path(input_path.stem + "_rejected.json")

    try:
        with open(input_path, "r") as f:
            doc = json.load(f)
        raw_text = doc["response"]["docs"][0]["text"][0]

        indexes = []
        headers = []

        splitlines = raw_text.splitlines()
        for index, line in enumerate(splitlines):
            # single line of text between three newlines before and two newlines after. likely a header
            if _line_spacing_resembles_header(line, splitlines, index):
                indexes.append([index])
                headers.append(line)

        headers_to_lower = [header.lower() for header in headers]
        if "abstract" in headers_to_lower:  # remove all content before abstract, if found
            abstract_index = headers_to_lower.index("abstract")
            headers = headers[abstract_index:]
            indexes = indexes[abstract_index:]

        indexes.append([len(raw_text)])
        index_pairs = [(i[-1], j[0]) for i, j in zip(indexes, indexes[1:])]

        rejected_paragraphs = []
        rejected_whole_subsections = []
        sectioned_text = {}

        actual_headers = 0

        for i, (start, end) in enumerate(index_pairs):
            header = headers[i]
            if len(header.split()) > 2 and not is_string_valid(header):
                continue
            section = splitlines[start:end]
            new_section = [j for j in section if j not in [header, "", [], "  "]]
            validated_new_section = _get_valid_sections(new_section)
            rejected_paragraphs.extend(_get_invalid_sections(new_section))
            combined_validated_new_section = "\n\n".join(validated_new_section).replace("  ", " ")
            validated_new_section = [unicodedata.normalize("NFD", i) for i in combined_validated_new_section]
            validated_new_section = [html.unescape(i) for i in validated_new_section]
            join_validated_new_section = "".join(validated_new_section)

            if (
                is_english(join_validated_new_section)
                and is_string_valid(join_validated_new_section)
                and not any([j in header.lower() for j in unneeded_sections_no_skip_remaining])
            ):
                actual_headers += 1
                sectioned_text[header] = join_validated_new_section

            elif any([j in header.lower() for j in needed_sections_but_skip_remaining]):
                actual_headers += 1
                sectioned_text[header] = join_validated_new_section
                rejected_whole_subsections.extend(index_pairs[i + 1 :])  # noqa
                break

            elif any([j in header.lower() for j in unneeded_sections_skip_remaining]):
                rejected_whole_subsections.extend(index_pairs[i:])
                break

            else:
                rejected_whole_subsections.append(index_pairs[i])

        for section in unneeded_sections_no_skip_remaining + unneeded_sections_skip_remaining:
            if section in headers_to_lower:
                for head in list(sectioned_text.keys()):  # since a key may be in any case
                    if section in head.lower():
                        del sectioned_text[head]

        rejected_paragraphs.extend(rejected_whole_subsections)

        if len(sectioned_text) == 0:
            return (False, input_path.stem, "No valid sections found")

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        with open(output_rejected_file, "w") as f:
            json.dump(rejected_paragraphs, f, indent=4)

        return (True, input_path.stem, None)

    except Exception as e:
        return (False, input_path.stem, str(e))


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
        delayed(_sectionize_one_file)(i, output_dir) for i in files_to_process
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
def section_dataset(source: Path):
    """Preprocess full-text files in s2orc/pes2o format.

    NOTE: Each file is assumed to contain one result.
    """

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress)
