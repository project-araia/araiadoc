import json
import re
import signal
from pathlib import Path

import chardet
import click
import langdetect
import pymupdf
from bs4 import BeautifulSoup
from PIL import Image
from rich.progress import Progress

from .schema import ParsedDocumentSchema
from .utils import (
    _collect_from_path,
    _is_url_dominant,
    _strip_phone_numbers,
    _strip_sequential_nonalphanumeric,
    _strip_urls,
)


def timeout_handler(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, timeout_handler)


def _convert(source: Path, progress):
    # import this here since it's a heavy dependency - we don't want to import it if we don't need to
    from text_processing.pdf_to_text import text2json  # noqa

    org = source.split("_")[0]
    collected_input_files = _collect_from_path(Path(source))

    click.echo("* Document Source: " + org)
    click.echo("* Found " + str(len(collected_input_files)) + " input pdf files. Cleaning ineligible ones.")

    files_to_convert_to_pdf = [
        i for i in collected_input_files if i is not None and i.suffix.lower() not in [".pdf", ".json"]
    ]  # skip pdfs, checkpoints, metadata

    if len(files_to_convert_to_pdf):

        click.echo("* Found " + str(len(files_to_convert_to_pdf)) + " files that must first be converted to PDF.")

        success_count = 0
        fail_count = 0

        task1 = progress.add_task("[green]Converting to PDF", total=len(files_to_convert_to_pdf))

        for i in files_to_convert_to_pdf:
            try:
                Image.open(i).save(i.with_suffix(".pdf"), "PDF", save_all=True, resolution=100)
                collected_input_files.append(i.with_suffix(".pdf"))
                success_count += 1
            except ValueError:
                fail_count += 1
            progress.update(task1, advance=1)

        click.echo("\n* Conversion of files to PDF:")
        click.echo("* Successes: " + str(success_count))
        click.echo("* Failures: " + str(fail_count))

    success_count = 0
    fail_count = 0

    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".pdf"]

    output_files = []

    task2 = progress.add_task("[bright_green]Converting to text", total=len(collected_input_files))

    # TODO: Try pymupdf first, then if that doesn't work try pdf2text

    for i in collected_input_files:
        signal.alarm(300)
        try:
            try:
                with pymupdf.open(i) as doc:  # open document
                    text = [page.get_text() for page in doc]
                if any([langdetect.detect(i) != "en" for i in text]):
                    raise ValueError("Document is unintelligible.")

            except Exception as e:
                click.echo("\nFailure with default PDF conversion of " + str(i) + ": " + str(e))
                click.echo("Trying AI converter...")
                from text_processing.pdf_to_text import pdf2text

                try:
                    text = pdf2text(str(i))
                except TimeoutError:
                    click.echo("Timeout with AI converstion of " + str(i) + ". Skipping.")
                    fail_count += 1
                    progress.update(task2, advance=1)
                    continue
                except Exception as e:
                    click.echo("Failure with AI conversion of " + str(i) + ": " + str(e))
                    fail_count += 1
                    progress.update(task2, advance=1)
                    continue

            else:
                output_dir = Path(str(i.parent) + "_json")
                output_file = output_dir / i.stem
                output_file.parent.mkdir(parents=True, exist_ok=True)
                text2json(text, str(output_file))
                output_files.append(output_file)
                progress.update(task2, advance=1)
                success_count += 1

        except TimeoutError:
            click.echo("Timeout while converting: " + str(i) + ". Skipping.")
            fail_count += 1
            progress.update(task2, advance=1)
            continue

    click.echo("\n* Conversion of PDFs to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))
    click.echo("* Entering json postprocessing step")
    output_files = [i.with_suffix(".json") for i in output_files if i.is_file()]

    success_count = 0
    fail_count = 0

    task3 = progress.add_task("[bright_green]Postprocessing json", total=len(output_files))

    # TODO: Why wasn't this postprocessing hit during OSTI conversion?
    for i in output_files:
        try:
            with open(i, "rw") as f:
                json_data = json.load(f)
                base_text_list = [instance["text"] for instance in json_data["instances"]]
                representation = ParsedDocumentSchema(
                    source=org,
                    text=base_text_list,
                )
                json.dump(representation.model_dump(mode="json"), f)
            success_count += 1
            progress.update(task3, advance=1)
        except Exception as e:
            click.echo("Failure while postprocessing " + str(i) + ": " + str(e))
            fail_count += 1
            progress.update(task3, advance=1)
            continue

    click.echo("\n* Postprocessing of json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))
    click.echo("* Entering metadata matching step")

    success_count = 0
    fail_count = 0

    metadata_file = [i for i in Path(source).glob("*metadata.json")][0]
    metadata = json.load(metadata_file.open("r"))  # noqa

    task4 = progress.add_task("[bright_green]Matching metadata", total=len(output_files))

    for i in output_files:
        try:
            with open(i, "rw") as f:
                json_data = json.load(f)
                text = json_data["text"]  # noqa
                # TODO: Update representation with metadata
                json.dump(representation.model_dump(mode="json"), f)
            success_count += 1
            progress.update(task4, advance=1)
        except Exception as e:
            click.echo("Failure while postprocessing " + str(i) + ": " + str(e))
            fail_count += 1
            progress.update(task4, advance=1)
            continue


@click.command()
@click.argument("source", nargs=1)
def convert(source: Path):
    """
    Convert PDFs in a given directory ``source`` to json. If the input files are of a different format,
    they'll first be converted to PDF.
    """
    with Progress() as progress:
        _convert(source, progress)


@click.command()
@click.argument("source", nargs=1)
def epa_ocr_to_json(source: Path):
    """Convert EPA's OCR fulltext to similar json format as output from pdf2json"""

    collected_input_files = _collect_from_path(Path(source))

    click.echo("* Found " + str(len(collected_input_files)) + " input text files.")

    success_count = 0
    fail_count = 0

    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".txt"]

    click.echo("* Beginning Conversion:")

    for i in collected_input_files:
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

            cleaned_subsections.append(cleaned)  # append last section, since it doesn't have a continuation

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
