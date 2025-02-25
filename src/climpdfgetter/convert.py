# import json
from pathlib import Path

import re
import click
from tqdm import tqdm
import json
import chardet

from .schema import ParsedDocumentSchema

# regex from https://www.geeksforgeeks.org/python-check-url-string/ - cant answer any questions about it :)
URL_RE = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"


def _prep_path(item: Path):
    if item.is_file() and not item.name.startswith(
        "."
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


@click.command()
@click.argument("source", nargs=1)
def convert(source: Path):
    """
    Convert PDFs in a given directory ``source`` to json. If the input files are of a different format,
    they'll first be converted to PDF.
    """

    from PIL import Image
    from text_processing.pdf_to_text import pdf2text, text2json

    collected_input_files = _collect_from_path(Path(source))

    click.echo(
        "* Found "
        + str(len(collected_input_files))
        + " input pdf files. Cleaning ineligible ones."
    )

    files_to_convert_to_pdf = [
        i for i in collected_input_files if i is not None and i.suffix.lower() != ".pdf"
    ]

    if len(files_to_convert_to_pdf):

        click.echo(
            "* Found "
            + str(len(files_to_convert_to_pdf))
            + " files that must first be converted to PDF."
        )

        success_count = 0
        fail_count = 0

        for i in tqdm(files_to_convert_to_pdf):
            try:
                Image.open(i).save(
                    i.with_suffix(".pdf"), "PDF", save_all=True, resolution=100
                )
                collected_input_files.append(i.with_suffix(".pdf"))
                success_count += 1
            except ValueError:
                fail_count += 1

        click.echo("* Conversion of files to PDF:")
        click.echo("* Successes: " + str(success_count))
        click.echo("* Failures: " + str(fail_count))

    success_count = 0
    fail_count = 0

    collected_input_files = [
        i for i in collected_input_files if i is not None and i.suffix.lower() == ".pdf"
    ]

    output_files = []

    for i in tqdm(collected_input_files):
        try:
            output_text = pdf2text(str(i))
            output_dir = Path(str(i.parent) + "_json")
            output_file = output_dir / i.stem
            output_file.parent.mkdir(parents=True, exist_ok=True)
            text2json(output_text, str(output_file))
            output_files.append(output_file)
            success_count += 1
        except Exception as e:
            click.echo("Failure while converting " + str(i) + ": " + str(e))
            fail_count += 1
            continue

    click.echo("* Conversion of PDFs to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))
    click.echo("* Entering json postprocessing step")

    output_files = [i.with_suffix(".json") for i in output_files if i.is_file()]

    success_count = 0
    fail_count = 0

    for i in tqdm(output_files):
        try:
            with open(i, "rw") as f:
                json_data = json.load(f)
                base_text_list = [
                    instance["text"] for instance in json_data["instances"]
                ]
                representation = ParsedDocumentSchema(
                    source="EPA",
                    text=base_text_list,
                )
                json.dump(representation.model_dump(mode="json"), f)
            success_count += 1
        except Exception as e:
            click.echo("Failure while postprocessing " + str(i) + ": " + str(e))
            fail_count += 1
            continue

    click.echo("* Postprocessing of json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))


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


import signal


def timeout_handler(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, timeout_handler)


@click.command()
@click.argument("source", nargs=1)
def epa_ocr_to_json(source: Path):
    """Convert EPA's OCR fulltext to similar json format as output from pdf2json"""

    from bs4 import BeautifulSoup

    collected_input_files = _collect_from_path(Path(source))

    click.echo("* Found " + str(len(collected_input_files)) + " input text files.")

    success_count = 0
    fail_count = 0

    collected_input_files = [
        i for i in collected_input_files if i is not None and i.suffix.lower() == ".txt"
    ]

    click.echo("* Beginning Conversion:")

    for i in tqdm(collected_input_files):
        signal.alarm(60)
        try:

            with open(i, "rb") as f:
                data = f.read()

            encoding = chardet.detect(data)["encoding"]
            full_text = data.decode(encoding)

            pubnumber = re.findall("<pubnumber>(.*?)</pubnumber>", full_text)[0]
            title = re.findall("<title>(.*?)</title>", full_text)[0]
            year = int(re.findall("<pubyear>(.*?)</pubyear>", full_text)[0])
            authors = re.findall("<author>(.*?)</author>", full_text)
            abstract = re.findall("<abstract>(.*?)</abstract>", full_text)[0]
            origin_format = re.findall("<origin>(.*?)</origin>", full_text)[0]
            publisher = re.findall("<publisher>(.*?)</publisher>", full_text)[0]

            ocr_soup = BeautifulSoup(full_text, "html.parser")
            text = ocr_soup.getText()

            cleaned_subsections = []
            sub_sections = text.split("\n\n\n")

            cached_section = ""

            for section in sub_sections:
                cleaned = "".join([i.strip() for i in section.split("\n") if len(i)])
                if len(cleaned) and not _is_url_dominant(cleaned):
                    cleaned = _strip_urls(cleaned)
                    cleaned = _strip_phone_numbers(cleaned)
                    cleaned = _strip_sequential_nonalphanumeric(cleaned)
                    if not cleaned.endswith(" "):
                        cleaned_subsections.append(cleaned)
                    else:  # want to combine lines that are continuations
                        cached_section += cleaned
                    # once continuation ends, append and reset
                    if not cached_section.endswith(" ") and len(cached_section):
                        cleaned_subsections.append(cached_section)
                        cached_section = ""

            cleaned_subsections.append(
                cleaned
            )  # append last section, since it doesn't have a continuation

            # remove pubnumber from first section
            cleaned_subsections[0] = cleaned_subsections[0].replace(pubnumber, "")

            representation = ParsedDocumentSchema(
                source="EPA",
                title=title,
                text=cleaned_subsections,
                abstract=abstract,
                authors=authors,
                origin_format=origin_format,
                publisher=publisher,
                unique_id=pubnumber,
                year=year,
            )

            output_dir = Path(str(i.parent) + "_json")
            output_file = Path(output_dir / i.stem).with_suffix(".json")
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w") as f:
                json.dump(representation.model_dump(mode="json"), f)
            success_count += 1

        except KeyboardInterrupt:
            click.echo("Skipping current document: " + str(i))
            fail_count += 1
            continue
        except TimeoutError:
            click.echo("Timeout while converting: " + str(i) + ". Skipping.")
            fail_count += 1
            continue
        except Exception as e:
            click.echo("Failure while converting: " + str(i) + ": " + str(e))
            fail_count += 1
            continue
        finally:
            signal.alarm(0)

    click.echo("* Conversion of EPA OCR text to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))
