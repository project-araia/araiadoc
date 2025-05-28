import json
import re
import signal
from pathlib import Path

import chardet
import click
from bs4 import BeautifulSoup
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from PIL import Image
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .schema import ParsedDocumentSchema
from .utils import _clean_subsections, _collect_from_path, clean_header


def timeout_handler(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, timeout_handler)


def _convert(source: Path, progress):
    # import this here since it's a heavy dependency - we don't want to import it if we don't need to

    org = "OSTI"  # TODO: make this configurable
    collected_input_files = _collect_from_path(Path(source))

    progress.log("\n* Document Source: " + org)
    progress.log("* Found " + str(len(collected_input_files)) + " input files. Discarding ineligible ones.")

    files_to_convert_to_pdf = [
        i for i in collected_input_files if i is not None and i.suffix.lower() not in [".pdf", ".json"]
    ]  # skip pdfs, checkpoints, metadata

    if len(files_to_convert_to_pdf):

        progress.log("* Found " + str(len(files_to_convert_to_pdf)) + " files that must first be converted to PDF.")

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

        progress.log("\n* Conversion of files to PDF:")
        progress.log("* Successes: " + str(success_count))
        progress.log("* Failures: " + str(fail_count))

    success_count = 0
    fail_count = 0

    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".pdf"]
    progress.log("\n* Found " + str(len(collected_input_files)) + " input PDFs.")

    task2 = progress.add_task("[bright_green]Converting multiple documents to text", total=len(collected_input_files))

    # already-completed output files
    output_dir = Path(str(collected_input_files[0].parent) + "_json")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = [i.stem for i in output_dir.iterdir()]

    timeout_json = output_dir / "timeout.json"
    if timeout_json.exists():
        with open(timeout_json, "r") as f:
            timeout_files = json.load(f)
    else:
        timeout_files = []

    metadata_file = [i for i in Path(source).glob("*metadata.json")][0]
    metadata = json.load(metadata_file.open("r"))

    for i in collected_input_files:
        signal.alarm(300)

        output_file = output_dir / i.stem
        if i.stem in output_files or i.stem in timeout_files:  # skip if already converted, or timed out
            success_count += 1
            progress.update(task2, advance=1)
            continue

        try:
            config = {
                "output_dir": output_file.parent / output_file.stem,
                "disable_links": True,
            }

            config_parser = ConfigParser(config)

            converter = PdfConverter(
                config=config_parser.generate_config_dict(),
                artifact_dict=create_model_dict(),
            )

            rendered = converter(str(i))
            text, _, _2 = text_from_rendered(rendered)
            lines = text.splitlines()

            indexes = []
            headers = []
            text = {}

            for idx, line in enumerate(lines):
                if line.startswith("#"):
                    indexes.append(idx)
                    headers.append(line)

            index_pairs = zip(indexes[:-1], indexes[1:])
            for i, (start, end) in enumerate(index_pairs):
                header = headers[i]
                new_header = clean_header(header)
                section = lines[start:end]
                new_section = [i for i in section if i not in [header, "\n"]]
                text[new_header] = new_section

        except TimeoutError:
            progress.log("Timeout while converting: " + str(i.name) + ". Skipping.")
            fail_count += 1
            progress.update(task2, advance=1)
            timeout_files.append(i.stem)
            continue

        else:  # because of the ValueError above, this else doesn't get hit even on AI OCR success
            output_files.append(output_file)
            try:
                matching_metadata = [entry for entry in metadata if output_file.stem == entry["osti_id"]][0]
                base_text_list = [text]
                representation = ParsedDocumentSchema(
                    source=org,
                    title=matching_metadata["title"],
                    text=base_text_list,
                    abstract=matching_metadata.get("description", ""),
                    authors=matching_metadata["authors"],
                    publisher=matching_metadata.get("journal_name", ""),
                    date=matching_metadata["publication_date"],
                    unique_id=matching_metadata["osti_id"],
                    doi=matching_metadata.get("doi", ""),
                )
                with open(output_file.with_suffix(".json"), "w") as f:
                    json.dump(representation.model_dump(mode="json"), f)
                progress.update(task2, advance=1)
                success_count += 1
            except Exception as e:
                progress.log("Failure while postprocessing " + str(output_file) + ": " + str(e))
                fail_count += 1
                progress.update(task2, advance=1)
                continue

    signal.alarm(0)
    with open(timeout_json, "w") as f:
        json.dump(timeout_files, f)

    progress.log("\n* Conversion of PDFs to json:")
    progress.log("* Successes or predetermined-skipped: " + str(success_count))
    progress.log("* Failures: " + str(fail_count))
    progress.log("* Timeout failures: " + str(len(timeout_files)))
    progress.log(
        "Timed out files appended to "
        + str(timeout_json)
        + ". These will be skipped on future conversions."
        + "\nDelete the file if you want to retry them."
    )


@click.command()
@click.argument("source", nargs=1)
def convert(source: Path):
    """
    Convert PDFs in a given directory ``source`` to json. If the input files are of a different format,
    they'll first be converted to PDF.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
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

            sub_sections = text.split("\n\n\n")
            cleaned_subsections = _clean_subsections(sub_sections)
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
