# import json
from pathlib import Path

import re
import click
from tqdm import tqdm
import json

from .schema import ParsedDocumentSchema


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

    for i in tqdm(collected_input_files):
        try:
            output_text = pdf2text(str(i))
            output_dir = Path(str(i.parent) + "_json")
            output_file = output_dir / i.stem
            output_file.parent.mkdir(parents=True, exist_ok=True)
            text2json(output_text, str(output_file))
            success_count += 1
        except Exception as e:
            click.echo("Failure while converting " + str(i) + ": " + str(e))
            fail_count += 1
            continue

    click.echo("* Conversion of PDFs to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))


def _doesnt_contain_url(text: str):
    return not re.match(".*http[s]?://", text) and not re.match(".*www.?", text)


@click.command()
@click.argument("source", nargs=1)
def epaocr2json(source: Path):
    """Convert EPA's OCR fulltext to similar json format as output from pdf2json"""

    from text_processing.pdf_to_text import text2json
    from bs4 import BeautifulSoup

    collected_input_files = _collect_from_path(Path(source))

    click.echo(
        "* Found "
        + str(len(collected_input_files))
        + " input text files. Cleaning ineligible ones."
    )

    success_count = 0
    fail_count = 0

    collected_input_files = [
        i for i in collected_input_files if i is not None and i.suffix.lower() == ".txt"
    ]

    for i in tqdm(collected_input_files):

        try:

            with open(i, "rb") as f:
                full_text = f.read().decode(errors='ignore')

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
                if len(cleaned) and _doesnt_contain_url(cleaned):
                    if not cleaned.endswith(" "):
                        cleaned_subsections.append(cleaned)
                    else:  # want to combine lines that are continuations
                        cached_section += cleaned
                    # once continuation ends, append and reset
                    if not cached_section.endswith(" ") and len(cached_section):
                        cleaned_subsections.append(cached_section)
                        cached_section = ""

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

        except Exception as e:
            click.echo("Failure while converting " + str(i) + ": " + str(e))
            fail_count += 1
            continue

    click.echo("* Conversion of EPA OCR text to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))


def init_pdf2json_to_parsed_doc(pdf2json: dict) -> ParsedDocumentSchema:

    base_text_list = [instance["text"] for instance in pdf2json["instances"]]

    return ParsedDocumentSchema(
        text=base_text_list,
    )
