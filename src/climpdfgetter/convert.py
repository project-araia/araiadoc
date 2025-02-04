# import json
from pathlib import Path

import click

# from .utils import _find_project_root


def _prep_path(item: Path):
    if item.is_file() and not item.name.startswith("."):  # avoid .DS_store and other files
        return Path(item)


@click.command()
@click.argument("source", nargs=1)
def convert(source: Path):
    """
    Convert PDFs in a given directory ``source`` to json. If the input files are of a different format,
    they'll first be converted to PDF.
    """

    from PIL import Image
    from text_processing.pdf_to_text import pdf2text, text2json
    from tqdm import tqdm

    data_root = Path(source)

    collected_input_files = []

    for directory in data_root.iterdir():
        if directory.is_dir():
            for item in directory.iterdir():
                collected_input_files.append(_prep_path(item))
        else:
            collected_input_files.append(_prep_path(directory))

    click.echo("* Found " + str(len(collected_input_files)) + " input files. Cleaning ineligible ones.")

    files_to_convert_to_pdf = [i for i in collected_input_files if i is not None and i.suffix.lower() != ".pdf"]

    if len(files_to_convert_to_pdf):

        click.echo("* Found " + str(len(files_to_convert_to_pdf)) + " files that must first be converted to PDF.")

        success_count = 0
        fail_count = 0

        for i in tqdm(files_to_convert_to_pdf):
            try:
                Image.open(i).save(i.with_suffix(".pdf"), "PDF", save_all=True, resolution=100)
                collected_input_files.append(i.with_suffix(".pdf"))
                success_count += 1
            except ValueError:
                fail_count += 1

        click.echo("* Conversion of files to PDF:")
        click.echo("* Successes: " + str(success_count))
        click.echo("* Failures: " + str(fail_count))

    success_count = 0
    fail_count = 0

    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".pdf"]

    for i in tqdm(collected_input_files):
        try:
            output_text = pdf2text(str(i))
            output_dir = Path(str(i.parent) + "_json")
            output_file = output_dir / i.stem
            output_file.parent.mkdir(parents=True, exist_ok=True)
            text2json(output_text, str(output_file))
            success_count += 1
        except Exception as e:
            click.echo("Failure while converting " + str(i) + ": " + e)
            fail_count += 1
            continue

    click.echo("* Conversion of PDFs to json:")
    click.echo("* Successes: " + str(success_count))
    click.echo("* Failures: " + str(fail_count))
