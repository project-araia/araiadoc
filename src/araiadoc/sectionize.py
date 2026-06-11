import gzip
import json
from pathlib import Path

import click
from joblib import Parallel, delayed
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .text_quality.content_assessment import (
    _content_is_substantive,
    _header_is_noise,
    _normalize_header,
    _normalize_text,
    apply_synonyms,
    is_string_valid,
    needed_sections_but_skip_remaining,
    unneeded_sections_no_skip_remaining,
    unneeded_sections_skip_remaining,
)
from .text_quality.text_validation import MIN_CONTENT_CHARS, is_english
from .utils import _collect_from_path

# ---------------------------------------------------------------------------
# s2orc_v2 span-annotation sectionizer
# ---------------------------------------------------------------------------
# The s2orc_v2 dataset represents the full paper body as a single string
# (doc["body"]["text"]) with structural elements encoded as character-offset
# span annotations (doc["body"]["annotations"]["paragraph"] and
# doc["body"]["annotations"]["section_header"]).
#
# Each annotation is stored as a JSON-encoded list of objects:
#   {"start": int, "end": int, "attributes": {...} | null}
#
# The correct header→paragraph mapping is recovered positionally: the section
# that owns a paragraph is the section_header whose span most recently *ends*
# before the paragraph's span begins.  Multiple paragraphs sharing the same
# header are concatenated (joined by a single space) before the usual quality
# filters are applied.
# ---------------------------------------------------------------------------


def _parse_spans(annotation_json: str | None) -> list[dict]:
    """Decode an annotation JSON string into a sorted list of span dicts."""
    if not annotation_json:
        return []
    try:
        spans = json.loads(annotation_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return sorted(spans, key=lambda s: s.get("start", 0))


def _sectionize_item_s2orc_v2(doc: dict):
    """Sectionize one s2orc_v2 document using span annotations.

    Parameters
    ----------
    doc:
        A single record from an s2orc_v2 JSONL shard (or a JSON file written
        by get-from-local-s2orc).

    Returns
    -------
    (success: bool, sectioned_text: dict, error: str | None)
        *sectioned_text* maps canonical header strings to paragraph text, plus
        optional "title" and "abstract" keys.
    """
    # Sentinel used internally for paragraphs that precede the first
    # section_header span.  These are later promoted to the "abstract" field
    # since s2orc_v2 has no standalone abstract annotation.
    _PRE_HEADER_KEY = "__pre_header__"

    corpus_id = str(doc.get("corpusid", "unknown"))

    # ---- title ----
    title = _normalize_text(doc.get("title") or "")

    # ---- body text and annotations ----
    body = doc.get("body") or {}
    text: str = body.get("text") or ""
    annotations: dict = body.get("annotations") or {}

    if not text:
        return (False, {}, f"[{corpus_id}] Empty body text")

    paragraph_spans = _parse_spans(annotations.get("paragraph"))
    header_spans = _parse_spans(annotations.get("section_header"))

    if not paragraph_spans:
        return (False, {}, f"[{corpus_id}] No paragraph annotations")

    # ---- map each paragraph to its nearest preceding header ----
    # header_spans are already sorted by start; we walk them alongside
    # paragraphs, advancing the current header whenever its end ≤ paragraph start.
    current_header_text = _PRE_HEADER_KEY  # paragraphs before any header are flagged
    header_idx = 0
    n_headers = len(header_spans)

    # Accumulate paragraphs per header in order.
    sections: list[tuple[str, list[str]]] = []  # [(canonical_header, [para_texts])]
    current_section_paras: list[str] = []

    def _flush(hdr, paras):
        if paras:
            sections.append((hdr, paras))

    for para_span in paragraph_spans:
        para_start = para_span.get("start", 0)
        para_end = para_span.get("end", 0)

        # Advance through headers whose end position is ≤ this paragraph's start.
        while header_idx < n_headers:
            hspan = header_spans[header_idx]
            h_start = hspan.get("start", 0)
            h_end = hspan.get("end", 0)
            if h_end <= para_start:
                _flush(current_header_text, current_section_paras)
                current_section_paras = []
                raw_header = text[h_start:h_end]
                current_header_text = apply_synonyms(_normalize_header(raw_header))
                header_idx += 1
            else:
                break

        para_text = _normalize_text(text[para_start:para_end])
        if para_text:
            current_section_paras.append(para_text)

    _flush(current_header_text, current_section_paras)

    # ---- promote pre-header paragraphs to "abstract" ----
    abstract = ""
    remaining_sections: list[tuple[str, list[str]]] = []
    for hdr, paras in sections:
        if hdr == _PRE_HEADER_KEY:
            joined = " ".join(paras).strip()
            if joined:
                # If a previous PRE_HEADER block already accumulated abstract
                # text (shouldn't happen in practice — there is only ever one
                # pre-header region), append rather than overwrite.
                abstract = (abstract + " " + joined).strip() if abstract else joined
        else:
            remaining_sections.append((hdr, paras))

    # ---- build sectioned_text dict applying existing quality filters ----
    sectioned_text: dict[str, str] = {}
    if title:
        sectioned_text["title"] = title
    if abstract:
        sectioned_text["abstract"] = abstract

    actual_headers_count = 0

    for header, para_list in remaining_sections:
        if _header_is_noise(header):
            continue

        compare_header = "".join(header.split()).lower()

        if any(j in compare_header for j in unneeded_sections_skip_remaining):
            break

        should_stop_after = any(j in compare_header for j in needed_sections_but_skip_remaining)

        if any(j in compare_header for j in unneeded_sections_no_skip_remaining):
            if should_stop_after:
                break
            continue

        # Concatenate all paragraphs under this header.
        content = " ".join(para_list)

        if not _content_is_substantive(content):
            if should_stop_after:
                break
            continue

        if is_english(content) and is_string_valid(content):
            # If the same canonical header appears more than once, append rather
            # than overwrite so no content is silently lost.
            if header in sectioned_text:
                sectioned_text[header] = sectioned_text[header] + " " + content
            else:
                sectioned_text[header] = content
            actual_headers_count += 1

        if should_stop_after:
            break

    content_keys = [k for k in sectioned_text if k not in ("title", "abstract")]
    if not content_keys and actual_headers_count == 0:
        return (False, sectioned_text, f"[{corpus_id}] No valid content sections found")

    return (True, sectioned_text, None)


def _extract_item_from_doc(doc):
    if "response" in doc and "docs" in doc["response"] and doc["response"]["docs"]:
        return doc["response"]["docs"][0]
    return doc


def _get_first(item, field):
    val = item.get(field, [""])
    if isinstance(val, list) and len(val) > 0:
        return val[0]
    return val if isinstance(val, str) else ""


def _get_list(item, field):
    val = item.get(field, [])
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [val]
    return []


def _get_corpus_id(item, fallback_stem=None):
    corpus_id = item.get("corpus_id")
    if isinstance(corpus_id, list) and len(corpus_id) > 0:
        return str(corpus_id[0])
    if corpus_id is not None:
        return str(corpus_id)
    return fallback_stem if fallback_stem is not None else "unknown"


def _sectionize_item_v2(item):
    title = _normalize_text(_get_first(item, "title"))
    abstract = _normalize_text(_get_first(item, "abstract"))
    paragraphs = [_normalize_text(p) for p in _get_list(item, "paragraph")]

    # 6/1
    section_headers = [apply_synonyms(_normalize_header(h)) for h in _get_list(item, "sectionheader")]

    if not paragraphs or not section_headers:
        return (False, {}, "Missing paragraph/sectionheader fields required for v2")

    sectioned_text = {}
    if title:
        sectioned_text["title"] = title
    if abstract:
        sectioned_text["abstract"] = abstract

    # 6/1
    if len(abstract) < MIN_CONTENT_CHARS:
        return (False, {}, "Abstract missing or too short.")

    actual_headers_count = 0

    for header, content in zip(section_headers, paragraphs):
        if _header_is_noise(header):
            continue

        compare_header = "".join(header.split()).lower()

        if any(j in compare_header for j in unneeded_sections_skip_remaining):
            break

        should_stop_after = any(j in compare_header for j in needed_sections_but_skip_remaining)

        if any(j in compare_header for j in unneeded_sections_no_skip_remaining):
            continue

        if not _content_is_substantive(content):
            if should_stop_after:
                break
            continue

        if is_english(content) and is_string_valid(content):
            # If the same canonical header appears more than once, append rather
            # than overwrite so no content is silently lost.
            if header in sectioned_text:
                sectioned_text[header] = sectioned_text[header] + " " + content
            else:
                sectioned_text[header] = content
            actual_headers_count += 1

        if should_stop_after:
            break

    content_keys = [k for k in sectioned_text.keys() if k not in ["title", "abstract"]]
    if not content_keys and actual_headers_count == 0:
        return (False, sectioned_text, "No valid content sections found")

    return (True, sectioned_text, None)


def _sharded_output_file(output_dir: Path, corpus_id: str) -> Path:
    """Return a sharded output path: output_dir/<last-2-digits>/corpus_id.json.

    Sharding by the last two characters of the corpus_id distributes files
    evenly across up to 100 subdirectories for numeric IDs, avoiding
    filesystem degradation from too many files in a single directory.
    """
    shard = corpus_id[-2:] if len(corpus_id) >= 2 else corpus_id
    shard_dir = output_dir / shard
    shard_dir.mkdir(exist_ok=True)
    return shard_dir / f"{corpus_id}.json"


def _sectionize_one_file(input_path: Path, output_dir: Path):
    try:
        with open(input_path, "r") as f:
            doc = json.load(f)

        item = _extract_item_from_doc(doc)
        corpus_id = _get_corpus_id(item, fallback_stem=input_path.stem)
        output_file = _sharded_output_file(output_dir, corpus_id)

        if output_file.exists():
            return (True, corpus_id, None, "skipped_existing")

        success, sectioned_text, error = _sectionize_item_v2(item)
        if not success:
            return (False, corpus_id, error, "failed")

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        return (True, corpus_id, None, "written")

    except Exception as e:
        return (False, input_path.stem, str(e), "failed")


def _discover_batch_files(source: Path):
    batch_files = []

    # Direct batches at the source root
    direct_batches = sorted(source.glob("*.jsonl.gz"))
    if direct_batches:
        batch_files.extend(direct_batches)

    # Batches nested under any subdirectory (covers all_terms/, all_utility/,
    # all_weather/, and any future search_name directories).
    nested_batches = sorted(source.glob("*/batches/*.jsonl.gz"))
    if nested_batches:
        seen = set(batch_files)
        batch_files.extend(i for i in nested_batches if i not in seen)

    return batch_files


def _load_batch_checkpoint(checkpoint_path: Path):
    if checkpoint_path.exists():
        try:
            return json.loads(checkpoint_path.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "completed_batches": [],
        "failures": [],
    }


def _write_batch_checkpoint(checkpoint_path: Path, checkpoint_data: dict):
    checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2))


def _sectionize_batch_file(batch_file: Path, output_dir: Path):
    batch_successes = 0
    batch_failures = []
    skipped_existing = 0

    with gzip.open(batch_file, "rt", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                doc = json.loads(line)
                item = _extract_item_from_doc(doc)
                corpus_id = _get_corpus_id(item, fallback_stem=f"{batch_file.stem}_line_{line_number}")
                output_file = _sharded_output_file(output_dir, corpus_id)

                if output_file.exists():
                    skipped_existing += 1
                    continue

                success, sectioned_text, error = _sectionize_item_v2(item)
                if not success:
                    batch_failures.append(
                        {
                            "corpus_id": corpus_id,
                            "batch_file": str(batch_file),
                            "line_number": line_number,
                            "error": error,
                        }
                    )
                    continue

                with open(output_file, "w") as out_f:
                    json.dump(sectioned_text, out_f, indent=4)

                batch_successes += 1

            except Exception as e:
                corpus_id = f"{batch_file.stem}_line_{line_number}"
                batch_failures.append(
                    {
                        "corpus_id": corpus_id,
                        "batch_file": str(batch_file),
                        "line_number": line_number,
                        "error": str(e),
                    }
                )

    return {
        "batch_file": str(batch_file),
        "successes": batch_successes,
        "failures": batch_failures,
        "skipped_existing": skipped_existing,
    }


def _sectionize_batches_parallel(batch_files, output_dir: Path, progress: Progress):
    checkpoint_path = output_dir / "batch_checkpoint.json"
    checkpoint_data = _load_batch_checkpoint(checkpoint_path)
    completed_batches = set(checkpoint_data.get("completed_batches", []))

    files_to_process = [bf for bf in batch_files if str(bf) not in completed_batches]

    task = progress.add_task("[green]Sectionizing batches", total=len(batch_files))
    already_completed = len(batch_files) - len(files_to_process)
    if already_completed:
        progress.update(task, advance=already_completed)

    if not files_to_process:
        progress.log("\n* Sectionization:")
        progress.log("* Batch files completed: " + str(len(completed_batches)))
        progress.log("* Documents written: 0")
        progress.log("* Existing outputs skipped: 0")
        progress.log("* Failures: " + str(len(checkpoint_data.get("failures", []))))
        return

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_batch_file)(batch_file, output_dir) for batch_file in files_to_process
    )

    success_count = 0
    skipped_existing_count = 0

    for result in results:
        success_count += result["successes"]
        skipped_existing_count += result["skipped_existing"]

        for failure in result["failures"]:
            checkpoint_data["failures"].append(failure)
            progress.log(
                f"* Error on corpus_id={failure['corpus_id']} "
                f"(batch={Path(failure['batch_file']).name}, line={failure['line_number']}): "
                f"{failure['error']}"
            )

        checkpoint_data["completed_batches"].append(result["batch_file"])
        _write_batch_checkpoint(checkpoint_path, checkpoint_data)
        progress.update(task, advance=1)

    progress.log("\n* Sectionization:")
    progress.log("* Batch files completed: " + str(len(checkpoint_data["completed_batches"])))
    progress.log("* Documents written: " + str(success_count))
    progress.log("* Existing outputs skipped: " + str(skipped_existing_count))
    progress.log("* Failures: " + str(len(checkpoint_data["failures"])))


def _sectionize_workflow(source: Path, progress: Progress, v2: bool = False):
    output_dir = Path(str(source) + "_sectionized")
    output_dir.mkdir(exist_ok=True, parents=True)

    if v2:
        batch_files = _discover_batch_files(Path(source))
    else:
        batch_files = []

    if v2 and batch_files:
        progress.log("* Detected batch input format (.jsonl.gz).")
        progress.log("* Found " + str(len(batch_files)) + " batch files.")
        _sectionize_batches_parallel(batch_files, output_dir, progress)
        return

    collected_input_files = _collect_from_path(Path(source))
    collected_input_files = [i for i in collected_input_files if i is not None and i.suffix.lower() == ".json"]

    progress.log("* Detected legacy per-document JSON input format.")
    progress.log("* Found " + str(len(collected_input_files)) + " input files.")
    task = progress.add_task("[green]Sectionizing", total=len(collected_input_files))

    failures_json = output_dir / Path("failures.json")
    if failures_json.exists():
        try:
            failures = json.loads(failures_json.read_text())
        except json.JSONDecodeError:
            failures = []
    else:
        failures = []

    failed_ids = set()
    for failure in failures:
        if isinstance(failure, dict):
            failed_ids.add(failure.get("corpus_id", ""))
        else:
            failed_ids.add(str(failure))

    files_to_process = []
    skipped_existing_count = 0
    skipped_previous_failures = 0

    for i in collected_input_files:
        try:
            with open(i, "r") as f:
                doc = json.load(f)
            item = _extract_item_from_doc(doc)
            corpus_id = _get_corpus_id(item, fallback_stem=i.stem)
        except Exception:
            corpus_id = i.stem

        output_file = _sharded_output_file(output_dir, corpus_id)
        if output_file.exists():
            skipped_existing_count += 1
            progress.update(task, advance=1)
            continue

        if corpus_id in failed_ids or i.stem in failed_ids:
            skipped_previous_failures += 1
            progress.update(task, advance=1)
            continue

        files_to_process.append(i)

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_one_file)(i, output_dir) for i in files_to_process
    )

    success_count = 0
    fail_count = 0

    for success, corpus_id, error, status in results:
        progress.update(task, advance=1)
        if success and status == "written":
            success_count += 1
        elif success and status == "skipped_existing":
            skipped_existing_count += 1
        else:
            fail_count += 1
            failure_record = {
                "corpus_id": corpus_id,
                "batch_file": None,
                "line_number": None,
                "error": error,
            }
            failures.append(failure_record)
            progress.log(f"* Error on: {corpus_id}: {error}")

    if failures:
        with open(failures_json, "w") as f:
            json.dump(failures, f, indent=2)

    progress.log("\n* Sectionization:")
    progress.log("* Documents written: " + str(success_count))
    progress.log("* Existing outputs skipped: " + str(skipped_existing_count))
    progress.log("* Previously failed inputs skipped: " + str(skipped_previous_failures))
    progress.log("* Failures: " + str(fail_count))


@click.command()
@click.argument("source", nargs=1)
def section_dataset(source: Path):
    """Preprocess full-text files in s2orc/pes2o format into headers and subsections.

    NOTE: Each file is assumed to contain one result.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress, False)


@click.command()
@click.argument("source", nargs=1)
def section_dataset_v2(source: Path):
    """Preprocess full-text files into header:paragraph JSON dictionaries.

    Supports both:
    1. Legacy per-document JSON files under the provided source directory.
    2. Batched JSONL.GZ output from _complete_all_terms_cursor, discovered at:
       source/*.jsonl.gz
       source/*/batches/*.jsonl.gz  (all_terms/, all_utility/, all_weather/, etc.)

    For batch input:
    - each gzip file is streamed line-by-line
    - each line is treated as one document
    - one sectionized JSON is written per corpus_id
    - processing resumes at the batch-file level via batch_checkpoint.json
    - existing output files are skipped

    The v2 input structure is assumed to contain:
    - "abstract"
    - "paragraph" as a list of paragraphs
    - "title"
    - "sectionheader" as a list aligned with "paragraph"

    If paragraph and sectionheader lengths differ, extra trailing entries are ignored.

    NOTE: Each file or JSONL line is assumed to contain one result.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress, True)


# ---------------------------------------------------------------------------
# section-dataset-s2orc  (span-annotation format from s2orc_v2)
# ---------------------------------------------------------------------------


def _sectionize_one_file_s2orc_v2(input_path: Path, output_dir: Path):
    """Sectionize a single per-document JSON file in s2orc_v2 format."""
    try:
        with open(input_path) as f:
            doc = json.load(f)

        corpus_id = str(doc.get("corpusid", input_path.stem))
        output_file = _sharded_output_file(output_dir, corpus_id)
        if output_file.exists():
            return (True, corpus_id, None, "skipped_existing")

        success, sectioned_text, error = _sectionize_item_s2orc_v2(doc)
        if not success:
            return (False, corpus_id, error, "failed")

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        return (True, corpus_id, None, "written")
    except Exception as e:
        return (False, input_path.stem, str(e), "failed")


def _sectionize_batch_file_s2orc_v2(batch_file: Path, output_dir: Path):
    """Stream one .gz JSONL shard and sectionize each document."""
    batch_successes = 0
    batch_failures = []
    skipped_existing = 0

    opener = gzip.open if batch_file.suffix == ".gz" else open
    with opener(batch_file, "rt", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                corpus_id = str(doc.get("corpusid", f"{batch_file.stem}_line_{line_number}"))
                output_file = _sharded_output_file(output_dir, corpus_id)

                if output_file.exists():
                    skipped_existing += 1
                    continue

                success, sectioned_text, error = _sectionize_item_s2orc_v2(doc)
                if not success:
                    batch_failures.append(
                        {
                            "corpus_id": corpus_id,
                            "batch_file": str(batch_file),
                            "line_number": line_number,
                            "error": error,
                        }
                    )
                    continue

                with open(output_file, "w") as out_f:
                    json.dump(sectioned_text, out_f, indent=4)

                batch_successes += 1

            except Exception as e:
                batch_failures.append(
                    {
                        "corpus_id": f"{batch_file.stem}_line_{line_number}",
                        "batch_file": str(batch_file),
                        "line_number": line_number,
                        "error": str(e),
                    }
                )

    return {
        "batch_file": str(batch_file),
        "successes": batch_successes,
        "failures": batch_failures,
        "skipped_existing": skipped_existing,
    }


def _sectionize_workflow_s2orc_v2(source: Path, progress: Progress):
    """Orchestrate sectionization of s2orc_v2 data.

    *source* may be:
      - A directory of .gz JSONL shards (from download-s2orc or get-from-local-s2orc)
      - A directory of per-document .json files (from get-from-local-s2orc ID lookups)
    """
    output_dir = Path(str(source) + "_sectionized")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prefer .gz shards if present (direct shard download or keyword-search
    # output).  rglob covers both flat layouts (download-s2orc) and nested
    # ones (source/<name>/batches/*.jsonl.gz from the TitanV pipeline).
    gz_files = sorted(source.rglob("*.gz"))

    if gz_files:
        progress.log(f"* Found {len(gz_files)} .gz shard file(s) — streaming mode.")
        checkpoint_path = output_dir / "batch_checkpoint.json"
        checkpoint_data = _load_batch_checkpoint(checkpoint_path)
        completed = set(checkpoint_data.get("completed_batches", []))
        to_process = [f for f in gz_files if str(f) not in completed]

        task = progress.add_task("[green]Sectionizing shards", total=len(gz_files))
        if len(gz_files) - len(to_process):
            progress.update(task, advance=len(gz_files) - len(to_process))

        results = Parallel(n_jobs=-1, return_as="generator")(
            delayed(_sectionize_batch_file_s2orc_v2)(bf, output_dir) for bf in to_process
        )

        success_count = 0
        skipped_count = 0
        for result in results:
            success_count += result["successes"]
            skipped_count += result["skipped_existing"]
            for failure in result["failures"]:
                checkpoint_data["failures"].append(failure)
                progress.log(f"* Error corpus_id={failure['corpus_id']}: {failure['error']}")
            checkpoint_data["completed_batches"].append(result["batch_file"])
            _write_batch_checkpoint(checkpoint_path, checkpoint_data)
            progress.update(task, advance=1)

        progress.log("\n* Sectionization complete.")
        progress.log(f"* Documents written: {success_count}")
        progress.log(f"* Existing skipped: {skipped_count}")
        progress.log(f"* Failures: {len(checkpoint_data['failures'])}")
        return

    # Fall back to per-document JSON files.
    json_files = [p for p in _collect_from_path(source) if p is not None and p.suffix.lower() == ".json"]
    progress.log(f"* Found {len(json_files)} per-document JSON file(s).")
    task = progress.add_task("[green]Sectionizing", total=len(json_files))

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_one_file_s2orc_v2)(p, output_dir) for p in json_files
    )

    success_count = fail_count = skipped_count = 0
    failures = []
    for success, corpus_id, error, status in results:
        progress.update(task, advance=1)
        if success and status == "written":
            success_count += 1
        elif status == "skipped_existing":
            skipped_count += 1
        else:
            fail_count += 1
            failures.append({"corpus_id": corpus_id, "error": error})
            progress.log(f"* Error {corpus_id}: {error}")

    if failures:
        (output_dir / "failures.json").write_text(json.dumps(failures, indent=2))

    progress.log("\n* Sectionization complete.")
    progress.log(f"* Documents written: {success_count}")
    progress.log(f"* Existing skipped: {skipped_count}")
    progress.log(f"* Failures: {fail_count}")


@click.command("section-dataset-s2orc")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
def section_dataset_s2orc(source: Path):
    """Sectionize s2orc_v2 documents using span-annotation offsets.

    SOURCE may be:

    \b
      - A directory of .gz JSONL shards downloaded by 'download-s2orc'
      - A directory of per-document .json files produced by 'get-from-local-s2orc'

    Each document's body.text is sliced by the paragraph and section_header
    annotation spans to recover the correct header→paragraph mapping.
    Multiple paragraphs under the same section header are concatenated.
    The same quality filters (language detection, content length, noise headers,
    stop-section detection) as section-dataset-v2 are applied.

    Output is written to SOURCE_sectionized/ as sharded JSON files
    (one per corpus ID), resumable via batch_checkpoint.json.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow_s2orc_v2(source, progress)
