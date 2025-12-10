import copy
import html
import json
import re
import signal
import sys
import unicodedata
from pathlib import Path

import chardet
import click

# import layoutparser as lp
import openparse
import pymupdf
import requests
from bs4 import BeautifulSoup
from langdetect import DetectorFactory, LangDetectException, detect
from PIL import Image
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .schema import ParsedDocumentSchema
from .utils import _clean_subsections, _collect_from_path

DetectorFactory.seed = 0

BOLD_RE = re.compile(r"\*{2,3}([^*]+?)\*{2,3}")  # inside **...** or ***...***


def timeout_handler(signum, frame):
    raise TimeoutError()


signal.signal(signal.SIGALRM, timeout_handler)


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


def convert_html(text):
    """
    Convert HTML entities back to character.
    """
    return html.unescape(text)


def _normalize(text):
    """
    Normalize Unicode strings. Necessary for text which contains non-ASCII characters.
    """
    return unicodedata.normalize("NFD", text)


def _convert_images_to_pdf(files: list, collected_files, progress):
    progress.log("* Found " + str(len(files)) + " files that must first be converted to PDF.")

    task1 = progress.add_task("[green]Converting to PDF", total=len(files))

    success_count = 0
    fail_count = 0
    for i in files:
        try:
            Image.open(i).save(i.with_suffix(".pdf"), "PDF", save_all=True, resolution=100)
            collected_files.append(i.with_suffix(".pdf"))
            success_count += 1
        except ValueError:
            fail_count += 1
        progress.update(task1, advance=1)

    progress.log("\n* Conversion of files to PDF:")
    progress.log("* Successes: " + str(success_count))
    progress.log("* Failures: " + str(fail_count))


def _get_images_tables_from_layoutparser(input_file: Path, output_file: Path):
    from .scrape_images_pdf import scrape_images

    length = len(pymupdf.open(input_file))
    output_file.mkdir(parents=True, exist_ok=True)
    scrape_images(input_file, last_pg=length, output_dir=output_file)


def _get_text_from_openparse(input_file: Path, output_file: Path):
    parser = openparse.DocumentParser()
    openparse.config.set_device("cpu")
    parsed_doc = parser.parse(input_file)
    text = []
    for node in parsed_doc.nodes:
        if "text" in node.variant:
            text.append(node.text)
    text = "\n".join(text)
    return text


def _get_xml_from_grobid(input_path: Path, grobid_service: str = "", output_dir_json: str = ""):
    from grobid_client.grobid_client import GrobidClient

    # move metadata file out of input_path temporarily
    try:
        metadata_file = [i for i in input_path.iterdir() if i.suffix == ".json"][0]
        metadata_file.rename(metadata_file.parent.parent / metadata_file.name)
        moved_metadata = True
    except IndexError:
        moved_metadata = False
    client = GrobidClient(grobid_server=grobid_service)
    client.process(
        service="processFulltextDocument",
        input_path=input_path,
        output=output_dir_json,
        n=10,
    )
    if moved_metadata:
        metadata_file.rename(input_path / metadata_file.name)


def _convert_grobid_xml_to_json(input_file) -> dict:
    keywords = [
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
    pattern = r"\b(?:" + "|".join(keywords) + r")\b"

    if input_file.suffix == ".xml":
        soup = BeautifulSoup(input_file.read_text(), "lxml-xml")

        paragraph_dict = {}

        try:
            abstract = soup.find("abstract").find("p").text.strip()
            paragraph_dict["abstract"] = abstract
        except AttributeError:
            pass
        body_paragraphs = soup.find("body").find_all("div")
        for b in body_paragraphs:
            first_para_text_clipped = None
            head = b.find("head")
            if head and head.text.strip():
                key = head.text.strip()
            else:
                # fallback: use beginning of first paragraph as key
                first_p = b.find("p")
                if first_p and first_p.text.strip():
                    text = first_p.text.strip()
                    # take first sentence
                    m = re.match(r"^(.+?[\.\!\?])\s", text)
                    if m:
                        key = m.group(1)
                        first_para_text_clipped = text[len(key) :].strip()  # noqa
                        # print(f"{key}:{first_para_text_clipped}")
                    else:
                        continue
                else:
                    continue  # skip this block if no head and no para
            key = convert_html(_normalize(key))
            if bool(re.search(pattern, key, re.IGNORECASE)):
                continue
            values = b.find_all("p")
            paras = []
            for idx, val in enumerate(values):
                text = val.text.strip()
                if first_para_text_clipped and idx == 0:
                    text = first_para_text_clipped
                text = convert_html(_normalize(text))
                tlower = text.lower()
                if (
                    tlower.startswith("acknowledgments")
                    or tlower.startswith("acknowledgements")
                    or tlower.startswith("references")
                    or tlower.startswith("bibliography")
                    or tlower.startswith("author contributions")
                ):
                    continue
                if not is_english(text):
                    continue
                if not paras:
                    paras.append(text)
                else:
                    prev = paras[-1].strip()
                    curr = text
                    # rules inspired by pes2o preprocessinng:
                    # Rule 1: if previous paragraph doesn't end with punctuation, merge
                    if not prev.endswith((".", "!", "?")):
                        paras[-1] = prev + " " + curr
                    # Rule 2: if previous ends with '(' and current starts with ')', merge
                    elif prev.endswith("(") and curr.startswith(")"):
                        paras[-1] = prev + curr
                    else:
                        paras.append(curr)
            paras = "\n\n".join(paras)
            paragraph_dict[key] = paras

        return paragraph_dict


def clean_header(h):
    # Remove HTML tags
    h = re.sub(r"<br\s*/?>", " ", h, flags=re.IGNORECASE)
    # Remove Markdown bold/italic markers
    h = re.sub(r"\*+", "", h)
    # Collapse whitespace
    h = re.sub(r"\s+", " ", h)
    return h.strip()


def looks_like_heading(text):
    # Basic cleanup
    t = clean_header(text)

    # Basic rejects
    if not t:
        return False
    if re.match(r"^(table|figure)\b", t, re.IGNORECASE):
        return False
    if len(t.split()) > 12 or len(t) > 100:
        return False
    if len(t) < 3:
        return False
    if re.match(r"^[^\w]", t):  # starts with non-alphanumeric
        return False
    if t.endswith("."):
        return False
    if re.fullmatch(r"[\d\s]+", t):
        return False
    # Reject things that look like "119:", "28:", "11:" etc.
    if re.match(r"^\d+[:.\-]?$", t):
        return False
    # Reject short alphanumeric codes like "A12", "X-23"
    if re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]?", t):
        return False
    # Reject headings that are mostly digits/symbols (e.g., "12.3.4", "3-2", etc.)
    if re.match(r"^[\d\W]+$", t):
        return False

    return True


def _convert(
    source: Path,
    progress,
    images_flag: bool = False,
    output_dir: str = None,
    grobid_service: str = "http://localhost:8070/api",
):

    org = "OSTI"  # TODO: make this configurable
    collected_input_files = _collect_from_path(Path(source))

    success_count = 0
    fail_count = 0

    progress.log("\n* Found " + str(len(collected_input_files)) + " input PDFs.")

    if grobid_service:
        progress.log("* Using Grobid. Checking specified host for Grobid service.")
        try:
            r = requests.get(grobid_service + "/api/isalive")
            r.raise_for_status()
            progress.log("[bright_green]Grobid service found.")
        except (requests.exceptions.RequestException, ConnectionRefusedError):
            progress.log("[red]Grobid service not found. Skipping Grobid conversion.")
            grobid_service = ""

    task2 = progress.add_task("[bright_green]Converting multiple documents to text", total=len(collected_input_files))

    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".pdf"]

    if not output_dir:
        output_dir = Path(str(collected_input_files[0].parent) + "_json")
    else:
        output_dir = Path(output_dir + "_json")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = [i.stem for i in output_dir.iterdir()]

    timeout_json = output_dir / "failures.json"
    if timeout_json.exists():
        with open(timeout_json, "r") as f:
            timeout_files = json.load(f)
    else:
        timeout_files = []

    no_metadata = False
    try:
        metadata = []
        for directory in Path(source).iterdir():
            if directory.is_dir():
                for item in directory.glob("*metadata.json"):
                    with open(item, "r") as f:
                        metadata.extend(json.load(f))
            elif directory.suffix == ".json" and directory.stem.endswith(
                "metadata"
            ):  # load single metadata file from the provided directory
                with open(directory, "r") as f:
                    metadata.extend(json.load(f))
    except IndexError:
        progress.log("[red]No metadata found for " + source + ". Skipping metadata association.")
        no_metadata = True

    if not len(metadata):
        progress.log("[red]No metadata found for " + source + ". Skipping metadata association.")
        no_metadata = True

    if images_flag:
        progress.log("Images and tables: enabled.")
    else:
        progress.log("Images and tables: disabled.")

    if grobid_service:
        _get_xml_from_grobid(Path(source), grobid_service, output_dir)
        collected_input_files = _collect_from_path(output_dir)

    for i in collected_input_files:
        signal.alarm(600)

        output_file = output_dir / i.stem
        if i.stem in output_files or i.stem in timeout_files:  # skip if already converted, or timed out
            success_count += 1
            progress.update(task2, advance=1)
            continue

        try:
            progress.log("Starting conversion for: " + str(i.name))
            if images_flag:
                _get_images_tables_from_layoutparser(i, output_file)
            if grobid_service:
                raw_text = _convert_grobid_xml_to_json(i)
            else:
                raw_text = _get_text_from_openparse(i, output_file)

        except TimeoutError:
            progress.log("Timeout while converting: " + str(i.name) + ". Skipping.")
            fail_count += 1
            progress.update(task2, advance=1)
            timeout_files.append(i.stem)
            continue

        except KeyboardInterrupt:
            progress.log("KeyboardInterrupt while converting: " + str(i.name) + ". Dumping current fails and exiting.")
            with open(timeout_json, "w") as f:
                json.dump(timeout_files, f)
            sys.exit()

        except Exception as e:
            progress.log("Error while converting: " + str(i.name) + ". Skipping.")
            print(e)
            fail_count += 1
            progress.update(task2, advance=1)
            timeout_files.append(i.stem)
            continue

        else:

            text = {}
            cleaned_headers = []
            if not grobid_service:
                raw_text = raw_text.replace("<br>", "\n")
                lines = raw_text.splitlines()

                indexes = []  # store indexes for content underneath headings
                raw_headers = []
                buffer_parts = []  # stores bold text chunks for current heading
                buffer_indexes = []  # stores line indexes for current heading

                for idx, line in enumerate(lines):
                    if line.startswith("**"):  # consecutive bold
                        # Extract all bold chunks from the line
                        chunks = [clean_header(m) for m in BOLD_RE.findall(line)]
                        if chunks:
                            buffer_parts.extend(chunks)
                            buffer_indexes.append(idx)
                            continue

                    # Allow blank lines inside a split heading without flushing
                    if line.strip() == "":
                        continue

                    # Non-blank, non-bold => flush heading
                    if buffer_parts:
                        merged_heading = clean_header(" ".join(buffer_parts))
                        if looks_like_heading(merged_heading):
                            raw_headers.append("".join(buffer_parts))
                            cleaned_headers.append(merged_heading)
                            indexes.append(buffer_indexes.copy())
                        buffer_parts.clear()
                        buffer_indexes.clear()

                # Flush any remaining heading at EOF
                if buffer_parts:
                    merged_heading = clean_header(" ".join(buffer_parts))
                    if looks_like_heading(merged_heading):
                        raw_headers.append("".join(buffer_parts))
                        cleaned_headers.append(merged_heading)
                        indexes.append(buffer_indexes.copy())

            else:
                text = raw_text
                cleaned_headers = list(text.keys())

            # remove any headers and corresponding indexes before the first header called "ABSTRACT"
            headers_to_upper = [header.upper() for header in cleaned_headers]
            if not grobid_service:
                if "ABSTRACT" in headers_to_upper:
                    abstract_index = headers_to_upper.index("ABSTRACT")
                    cleaned_headers = cleaned_headers[abstract_index:]
                    indexes = indexes[abstract_index:]

                indexes.append([len(lines)])
                index_pairs = [(i[-1], j[0]) for i, j in zip(indexes, indexes[1:])]
                progress.log("Found " + str(len(cleaned_headers)) + " possible headers.")
                for i, (start, end) in enumerate(index_pairs):
                    header = cleaned_headers[i]
                    raw_header = raw_headers[i]
                    new_header = clean_header(header)
                    section = lines[start:end]
                    new_section = [j for j in section if j not in [header, raw_header, "\n", "", [], "  "]]
                    combined_new_section = (
                        "".join(new_section).replace("  ", " ").replace("<br>", "\n").replace("<br><br>", "\n")
                    )
                    new_section = [unicodedata.normalize("NFD", i) for i in combined_new_section]
                    new_section = [html.unescape(i) for i in new_section]
                    text[new_header] = "".join(new_section)

            # remove DISCLAIMER and ACKNOWLEDGMENTS
            if "DISCLAIMER" in headers_to_upper:
                del text["DISCLAIMER"]
            if "ACKNOWLEDGMENTS" in headers_to_upper:
                del text["ACKNOWLEDGMENTS"]
            if "FUNDING" in headers_to_upper:
                del text["FUNDING"]

            # remove REFERENCES or WORKS CITED, but save for later
            if "REFERENCES" in headers_to_upper:
                references = copy.deepcopy(text["REFERENCES"])  # copy of value before deleting the source
                del text["REFERENCES"]
            elif "WORKS CITED" in headers_to_upper:
                references = copy.deepcopy(text["WORKS CITED"])
                del text["WORKS CITED"]

            len_subsections = len("".join(list(text.values())))
            if not len(text) or len_subsections / len(raw_text) < 0.90:
                text = {"text": " ".join(lines)}

            output_files.append(output_file)

            if not no_metadata:
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
                        references=references,
                    )
                    output_rep = representation.model_dump(mode="json")
                except Exception as e:
                    progress.log("Failure while postprocessing " + str(output_file) + ": " + str(e))
                    fail_count += 1
                    continue
            else:
                output_rep = text
            with open(output_file.with_suffix(".json"), "w") as f:
                json.dump(output_rep, f)
            progress.update(task2, advance=1)
            success_count += 1

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
@click.option("--images-tables", "-i", is_flag=True)
@click.option("--output-dir", "-o", nargs=1)
@click.option("--grobid_service", "-g", nargs=1)
def convert(source: Path, images_tables: bool, output_dir: str = None, grobid_service: str = ""):
    """
    Convert PDFs in a given directory ``source`` to json. If the input files are of a different format,
    they'll first be converted to PDF.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn(), disable=True) as progress:
        _convert(source, progress, images_tables, output_dir, grobid_service)


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
