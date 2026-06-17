import gzip
import json
import os
import re
from pathlib import Path

import click
from joblib import Parallel, delayed
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from .sectionize_report import (
    CorpusReport,
    CorpusReportPartial,
    DocReport,
    append_gz_file,
    open_per_doc_writer,
    write_doc_row,
    write_summary_json,
)
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


def _compile_exclude_patterns(patterns_str: str | None = None, pattern_file: Path | None = None) -> list[re.Pattern]:
    """Parse comma-separated string and/or pattern file into compiled regexes (IGNORECASE)."""
    patterns: list[str] = []
    if patterns_str:
        patterns.extend([p.strip() for p in patterns_str.split(",") if p.strip()])
    if pattern_file:
        patterns.extend(
            [
                line.strip()
                for line in pattern_file.read_text().splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )
    return [re.compile(p, re.IGNORECASE) for p in patterns]


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
    """Decode an annotation JSON string into a sorted list of span dicts.

    Some legacy s2orc v1 variants encode ``start``/``end`` as strings (e.g.
    ``"2675"``) rather than integers.  Coerce them here so downstream slicing
    of ``body.text`` always sees ints.  Spans whose offsets cannot be coerced
    are dropped rather than crashing the whole document.
    """
    if not annotation_json:
        return []
    try:
        spans = json.loads(annotation_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(spans, list):
        return []
    normalized: list[dict] = []
    for s in spans:
        if not isinstance(s, dict):
            continue
        try:
            s["start"] = int(s.get("start", 0))
            s["end"] = int(s.get("end", 0))
        except (TypeError, ValueError):
            continue
        normalized.append(s)
    return sorted(normalized, key=lambda s: s["start"])


def _normalize_to_v2(doc: dict) -> dict:
    """Coerce legacy s2orc v1 records into the v2 shape this sectionizer expects.

    v1 records nest text + annotations under ``content`` rather than ``body``,
    and use the key ``sectionheader`` (no underscore) instead of
    ``section_header``.  Annotation values themselves are JSON-encoded strings
    in both versions, so no further span-level conversion is needed.

    Records that are already v2 (have a dict ``body`` field) are returned
    unchanged.
    """
    if isinstance(doc.get("body"), dict):
        return doc
    content = doc.get("content")
    if not isinstance(content, dict):
        return doc
    ann = content.get("annotations") or {}
    if isinstance(ann, dict) and "sectionheader" in ann and "section_header" not in ann:
        ann = {**ann, "section_header": ann["sectionheader"]}
    normalized = dict(doc)
    normalized["body"] = {"text": content.get("text") or "", "annotations": ann}

    # v1 has no top-level ``title``.  Try, in order:
    #   1. Any known annotation key whose span(s) point into content.text
    #      ("title", "papertitle", "paper_title", "doctitle").
    #   2. The first non-empty line of content.text (Grobid-style PDFs put the
    #      paper title on the first line of the body).
    if not normalized.get("title"):
        text = content.get("text") or ""
        title_text = ""

        if isinstance(ann, dict):
            for key in ("title", "papertitle", "paper_title", "doctitle"):
                raw = ann.get(key)
                if not raw:
                    continue
                for span in _parse_spans(raw):
                    candidate = text[span["start"] : span["end"]].strip()  # noqa
                    if candidate:
                        title_text = candidate
                        break
                if title_text:
                    break

        if not title_text and text:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    title_text = stripped
                    break

        if title_text:
            normalized["title"] = title_text

    return normalized


def _sectionize_item_s2orc_v2(
    doc: dict,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Sectionize one s2orc_v2 document using span annotations.

    Parameters
    ----------
    doc:
        A single record from an s2orc_v2 JSONL shard (or a JSON file written
        by get-from-local-s2orc).
    capture_section_detail:
        When True, populate `DocReport.sections` with one `SectionDetail` row
        per section observed (canonical header, char/paragraph counts, and
        per-section outcome: "kept" or one of `DROP_REASONS`). Default False
        keeps the per-doc memory profile unchanged for production runs.
    exclude_patterns:
        Optional list of compiled regex patterns. If any pattern matches the
        document's title or body text, the document is excluded before
        sectionization.

    Returns
    -------
    (success: bool, sectioned_text: dict, error: str | None, report: DocReport)
        *sectioned_text* maps canonical header strings to paragraph text, plus
        optional "title" and "abstract" keys. *report* tracks per-section
        accounting (kept/dropped chars, paragraphs, sections, with drop reasons).
    """
    # Sentinel used internally for paragraphs that precede the first
    # section_header span.  These are later promoted to the "abstract" field
    # since s2orc_v2 has no standalone abstract annotation.
    _PRE_HEADER_KEY = "__pre_header__"

    corpus_id = str(doc.get("corpusid", "unknown"))
    report = DocReport(corpus_id=corpus_id, outcome="structural_failure")

    def _hdr(name: str) -> str | None:
        # Only pass header= into record_kept/record_dropped when detail capture
        # is on; otherwise the report skips appending a SectionDetail row.
        return name if capture_section_detail else None

    # ---- title ----
    title = _normalize_text(doc.get("title") or "")

    # ---- body text and annotations ----
    body = doc.get("body") or {}
    text: str = body.get("text") or ""
    annotations: dict = body.get("annotations") or {}

    if not text:
        report.error = f"[{corpus_id}] Empty body text"
        report.finalize()
        return (False, {}, report.error, report)

    # ---- exclude-pattern filter ----
    if exclude_patterns:
        full_text = " ".join(filter(None, [title, text]))
        if any(p.search(full_text) for p in exclude_patterns):
            report.outcome = "excluded_by_pattern"
            report.error = f"[{corpus_id}] Excluded by pattern match"
            report.finalize()
            return (False, {}, report.error, report)

    # total_chars: count all paragraph-span content the document offered (not
    # body text length, which can include arbitrary inter-paragraph noise).
    # We populate it during the span walk below.

    paragraph_spans = _parse_spans(annotations.get("paragraph"))
    header_spans = _parse_spans(annotations.get("section_header"))

    if not paragraph_spans:
        report.error = f"[{corpus_id}] No paragraph annotations"
        report.finalize()
        return (False, {}, report.error, report)

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
    abstract_para_count = 0
    remaining_sections: list[tuple[str, list[str]]] = []
    for hdr, paras in sections:
        if hdr == _PRE_HEADER_KEY:
            joined = " ".join(paras).strip()
            if joined:
                # If a previous PRE_HEADER block already accumulated abstract
                # text (shouldn't happen in practice — there is only ever one
                # pre-header region), append rather than overwrite.
                abstract = (abstract + " " + joined).strip() if abstract else joined
                abstract_para_count += len(paras)
        else:
            remaining_sections.append((hdr, paras))

    # ---- build sectioned_text dict applying existing quality filters ----
    sectioned_text: dict[str, str] = {}
    if title:
        sectioned_text["title"] = title
    if abstract:
        sectioned_text["abstract"] = abstract
        # The abstract counts as kept content, but it isn't subject to the
        # per-section filter loop, so record it directly.
        report.record_kept(
            chars=len(abstract),
            paragraphs=abstract_para_count,
            header=_hdr("abstract"),
        )

    actual_headers_count = 0

    def _content_chars_for(para_list: list[str]) -> int:
        # Mirror how `content` would be assembled below so the accounting
        # matches what would have been written.
        return len(" ".join(para_list))

    def _record_truncated_tail(start_idx: int) -> None:
        """Bucket every section the loop would have visited after a break."""
        for hdr, paras in remaining_sections[start_idx:]:
            report.record_dropped(
                "post_break_truncated",
                chars=_content_chars_for(paras),
                paragraphs=len(paras),
                header=_hdr(hdr),
            )

    for i, (header, para_list) in enumerate(remaining_sections):
        section_chars = _content_chars_for(para_list)
        section_paras = len(para_list)

        if _header_is_noise(header):
            report.record_dropped(
                "noise_header",
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )
            continue

        compare_header = "".join(header.split()).lower()

        if any(j in compare_header for j in unneeded_sections_skip_remaining):
            report.record_dropped(
                "unneeded_skip_truncation",
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )
            _record_truncated_tail(i + 1)
            break

        should_stop_after = any(j in compare_header for j in needed_sections_but_skip_remaining)

        if any(j in compare_header for j in unneeded_sections_no_skip_remaining):
            report.record_dropped(
                "unneeded_no_skip",
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )
            if should_stop_after:
                _record_truncated_tail(i + 1)
                break
            continue

        # Concatenate all paragraphs under this header.
        content = " ".join(para_list)

        if not _content_is_substantive(content):
            report.record_dropped(
                "non_substantive",
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )
            if should_stop_after:
                _record_truncated_tail(i + 1)
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
            report.record_kept(
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )
        else:
            report.record_dropped(
                "non_english_or_invalid",
                chars=section_chars,
                paragraphs=section_paras,
                header=_hdr(header),
            )

        if should_stop_after:
            # The conclusion-style section we just processed is genuinely
            # kept; everything past it gets bucketed as conclusion-driven
            # truncation so it's distinguishable from the unneeded-skip case.
            for hdr, paras in remaining_sections[i + 1 :]:  # noqa
                report.record_dropped(
                    "post_conclusion_truncation",
                    chars=_content_chars_for(paras),
                    paragraphs=len(paras),
                    header=_hdr(hdr),
                )
            break

    # Total chars seen = kept + dropped + (anything not in either bucket).
    # In this pipeline, every section that enters the loop is bucketed, so the
    # default `finalize()` behavior (kept+dropped) is correct.
    report.finalize()

    content_keys = [k for k in sectioned_text if k not in ("title", "abstract")]
    if not content_keys and actual_headers_count == 0:
        # Distinguish "all sections were filtered out" from "no sections to
        # begin with" — the latter would have been caught above as a
        # structural_failure. Here, we know at least one section reached the
        # loop, so this is a fully-filtered outcome.
        if report.total_sections > 0:
            report.outcome = "fully_filtered"
        else:
            report.outcome = "structural_failure"
        report.error = f"[{corpus_id}] No valid content sections found"
        return (False, sectioned_text, report.error, report)

    report.outcome = "unfiltered" if report.dropped_sections == 0 else "partially_filtered"
    return (True, sectioned_text, None, report)


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


def _sectionize_item_v2(
    item,
    corpus_id: str | None = None,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Legacy v2 (TitanV/Solr) sectionizer.

    Returns (success, sectioned_text, error, report). `corpus_id` is taken
    from the caller; if not supplied, falls back to "unknown" for the
    accounting record.

    `capture_section_detail`, when True, populates `DocReport.sections` with
    one `SectionDetail` row per (header, paragraph) pair observed. See
    `_sectionize_item_s2orc_v2` for the same flag.

    `exclude_patterns`: Optional list of compiled regex patterns. If any pattern
    matches the document's title, abstract, or body text, the document is
    excluded before sectionization.
    """
    cid = corpus_id if corpus_id is not None else _get_corpus_id(item)
    report = DocReport(corpus_id=cid, outcome="structural_failure")

    def _hdr(name: str) -> str | None:
        return name if capture_section_detail else None

    title = _normalize_text(_get_first(item, "title"))
    abstract = _normalize_text(_get_first(item, "abstract"))
    paragraphs = [_normalize_text(p) for p in _get_list(item, "paragraph")]

    # 6/1
    section_headers = [apply_synonyms(_normalize_header(h)) for h in _get_list(item, "sectionheader")]

    if not paragraphs or not section_headers:
        report.error = "Missing paragraph/sectionheader fields required for v2"
        report.finalize()
        return (False, {}, report.error, report)

    sectioned_text = {}
    if title:
        sectioned_text["title"] = title
    if abstract:
        sectioned_text["abstract"] = abstract

    # 6/1
    if len(abstract) < MIN_CONTENT_CHARS:
        report.error = "Abstract missing or too short."
        report.finalize()
        return (False, {}, report.error, report)

    # ---- exclude-pattern filter ----
    if exclude_patterns:
        body_text = " ".join(paragraphs)
        full_text = " ".join(filter(None, [title, abstract, body_text]))
        if any(p.search(full_text) for p in exclude_patterns):
            report.outcome = "excluded_by_pattern"
            report.error = f"[{cid}] Excluded by pattern match"
            report.finalize()
            return (False, {}, report.error, report)

    # Abstract counts as kept content (it bypasses the per-section filter loop).
    if abstract:
        report.record_kept(chars=len(abstract), paragraphs=1, header=_hdr("abstract"))

    actual_headers_count = 0
    paired = list(zip(section_headers, paragraphs))

    def _record_tail(start_idx: int) -> None:
        for hdr, content in paired[start_idx:]:
            report.record_dropped(
                "post_break_truncated",
                chars=len(content),
                paragraphs=1,
                header=_hdr(hdr),
            )

    for i, (header, content) in enumerate(paired):
        chars = len(content)
        paras = 1  # legacy schema is 1 paragraph per (header, content) pair

        if _header_is_noise(header):
            report.record_dropped("noise_header", chars=chars, paragraphs=paras, header=_hdr(header))
            continue

        compare_header = "".join(header.split()).lower()

        if any(j in compare_header for j in unneeded_sections_skip_remaining):
            report.record_dropped(
                "unneeded_skip_truncation",
                chars=chars,
                paragraphs=paras,
                header=_hdr(header),
            )
            _record_tail(i + 1)
            break

        should_stop_after = any(j in compare_header for j in needed_sections_but_skip_remaining)

        if any(j in compare_header for j in unneeded_sections_no_skip_remaining):
            report.record_dropped(
                "unneeded_no_skip",
                chars=chars,
                paragraphs=paras,
                header=_hdr(header),
            )
            continue

        if not _content_is_substantive(content):
            report.record_dropped(
                "non_substantive",
                chars=chars,
                paragraphs=paras,
                header=_hdr(header),
            )
            if should_stop_after:  # noqa
                _record_tail(i + 1)
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
            report.record_kept(chars=chars, paragraphs=paras, header=_hdr(header))
        else:
            report.record_dropped(
                "non_english_or_invalid",
                chars=chars,
                paragraphs=paras,
                header=_hdr(header),
            )

        if should_stop_after:
            for hdr, c in paired[i + 1 :]:  # noqa
                report.record_dropped(
                    "post_conclusion_truncation",
                    chars=len(c),
                    paragraphs=1,
                    header=_hdr(hdr),
                )
            break

    report.finalize()

    content_keys = [k for k in sectioned_text.keys() if k not in ["title", "abstract"]]
    if not content_keys and actual_headers_count == 0:
        if report.total_sections > 0:
            report.outcome = "fully_filtered"
        else:
            report.outcome = "structural_failure"
        report.error = "No valid content sections found"
        return (False, sectioned_text, report.error, report)

    report.outcome = "unfiltered" if report.dropped_sections == 0 else "partially_filtered"
    return (True, sectioned_text, None, report)


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


def _sectionize_one_file(
    input_path: Path,
    output_dir: Path,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Sectionize one legacy v2 per-document JSON file.

    Returns (success, corpus_id, error, status, report). `report` is None
    for `skipped_existing` and for hard exceptions where we never got to run
    the sectionizer.
    """
    try:
        with open(input_path, "r") as f:
            doc = json.load(f)

        item = _extract_item_from_doc(doc)
        corpus_id = _get_corpus_id(item, fallback_stem=input_path.stem)
        output_file = _sharded_output_file(output_dir, corpus_id)

        if output_file.exists():
            return (True, corpus_id, None, "skipped_existing", None)

        success, sectioned_text, error, report = _sectionize_item_v2(
            item,
            corpus_id=corpus_id,
            capture_section_detail=capture_section_detail,
            exclude_patterns=exclude_patterns,
        )
        if not success:
            return (False, corpus_id, error, "failed", report)

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        return (True, corpus_id, None, "written", report)

    except Exception as e:
        # Exception before the sectionizer ran: synthesize a structural_failure
        # report so the corpus stats still see this document.
        report = DocReport(corpus_id=input_path.stem, outcome="structural_failure", error=str(e))
        report.finalize()
        return (False, input_path.stem, str(e), "failed", report)


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


def _sectionize_batch_file(
    batch_file: Path,
    output_dir: Path,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    batch_successes = 0
    batch_failures = []
    skipped_existing = 0
    partial = CorpusReportPartial()

    # Per-doc rows stream to a per-batch temp gz file inside output_dir so the
    # worker never holds more than one DocReport in memory at a time. The
    # parent process concatenates these temp files into the corpus-wide
    # sectionization_report.jsonl.gz after each batch.
    tmp_report_path = output_dir / f".report_{batch_file.stem}.{os.getpid()}.jsonl.gz"
    tmp_handle = open_per_doc_writer(tmp_report_path, append=False)

    def _add_report(report: DocReport) -> None:
        partial.add(report)
        write_doc_row(tmp_handle, report)

    try:
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

                    success, sectioned_text, error, report = _sectionize_item_v2(
                        item,
                        corpus_id=corpus_id,
                        capture_section_detail=capture_section_detail,
                        exclude_patterns=exclude_patterns,
                    )
                    _add_report(report)
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
                    exc_report = DocReport(corpus_id=corpus_id, outcome="structural_failure", error=str(e))
                    exc_report.finalize()
                    _add_report(exc_report)
    finally:
        tmp_handle.close()

    return {
        "batch_file": str(batch_file),
        "successes": batch_successes,
        "failures": batch_failures,
        "skipped_existing": skipped_existing,
        "partial": partial,
        "report_tmp": str(tmp_report_path),
    }


def _sectionize_batches_parallel(
    batch_files,
    output_dir: Path,
    progress: Progress,
    source: Path,
    pipeline: str,
    batch_fn,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Drive sectionization of a list of batch files in parallel.

    `batch_fn` is the per-batch worker (e.g. `_sectionize_batch_file_s2orc_v2`).
    Each worker streams its per-doc report rows into a per-batch temp gz file
    under `output_dir`; this driver concatenates each completed temp file
    onto the corpus-wide `sectionization_report.jsonl.gz` and folds the
    worker's aggregate counts into the corpus `CorpusReport`. This keeps
    both worker memory and parent memory bounded to one DocReport at a time.

    When ``capture_section_detail`` is True, each per-doc report row in the
    JSONL.GZ also carries a `sections` array with one entry per section
    observed (header, chars, paragraphs, outcome). This roughly doubles the
    per-doc row size and is opt-in.
    """
    checkpoint_path = output_dir / "batch_checkpoint.json"
    checkpoint_data = _load_batch_checkpoint(checkpoint_path)
    completed_batches = set(checkpoint_data.get("completed_batches", []))

    files_to_process = [bf for bf in batch_files if str(bf) not in completed_batches]

    summary_path = output_dir / "sectionization_report.json"
    per_doc_path = output_dir / "sectionization_report.jsonl.gz"
    corpus_report = CorpusReport(pipeline=pipeline, source=str(source))

    task = progress.add_task("[green]Sectionizing batches", total=len(batch_files))
    already_completed = len(batch_files) - len(files_to_process)
    if already_completed:
        progress.update(task, advance=already_completed)

    if not files_to_process:
        # Nothing to do — preserve whatever the previous run produced.
        progress.log("\n* Sectionization:")
        progress.log("* Batch files completed: " + str(len(completed_batches)))
        progress.log("* Documents written: 0")
        progress.log("* Existing outputs skipped: 0")
        progress.log("* Failures: " + str(len(checkpoint_data.get("failures", []))))
        if summary_path.exists():
            progress.log(f"* Existing summary preserved at {summary_path.name}.")
        return

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(batch_fn)(batch_file, output_dir, capture_section_detail, exclude_patterns)
        for batch_file in files_to_process
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

        # Merge worker aggregate into corpus report, then concat the per-batch
        # JSONL.GZ onto the corpus-wide one and remove the temp.
        partial = result.get("partial")
        if partial is not None:
            corpus_report.merge_partial(partial)
        tmp_str = result.get("report_tmp")
        if tmp_str:
            tmp_path = Path(tmp_str)
            if tmp_path.exists():
                try:
                    append_gz_file(per_doc_path, tmp_path)
                finally:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
        corpus_report.previously_written += result["skipped_existing"]

        checkpoint_data["completed_batches"].append(result["batch_file"])
        _write_batch_checkpoint(checkpoint_path, checkpoint_data)
        write_summary_json(summary_path, corpus_report)
        progress.update(task, advance=1)

    progress.log("\n* Sectionization:")
    progress.log("* Batch files completed: " + str(len(checkpoint_data["completed_batches"])))
    progress.log("* Documents written: " + str(success_count))
    progress.log("* Existing outputs skipped: " + str(skipped_existing_count))
    progress.log("* Failures: " + str(len(checkpoint_data["failures"])))
    _render_report_tables(progress, corpus_report)


def _render_report_tables(progress: Progress, corpus_report: CorpusReport) -> None:
    """Print the corpus_report tables to the rich console attached to `progress`."""
    progress.log("")  # blank line for separation
    for table in corpus_report.render_tables():
        progress.console.print(table)


def _sectionize_workflow(
    source: Path,
    progress: Progress,
    v2: bool = False,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    output_dir = Path(str(source) + "_sectionized")
    output_dir.mkdir(exist_ok=True, parents=True)

    pipeline = "v2" if v2 else "v1"

    if v2:
        batch_files = _discover_batch_files(Path(source))
    else:
        batch_files = []

    if v2 and batch_files:
        progress.log("* Detected batch input format (.jsonl.gz).")
        progress.log("* Found " + str(len(batch_files)) + " batch files.")
        _sectionize_batches_parallel(
            batch_files,
            output_dir,
            progress,
            source=Path(source),
            pipeline=pipeline,
            batch_fn=_sectionize_batch_file,
            capture_section_detail=capture_section_detail,
            exclude_patterns=exclude_patterns,
        )
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

    # Report setup. Append onto an existing JSONL only if one is actually
    # present on disk (i.e. this is a resume). For a fresh run, truncate so
    # the JSONL starts empty.
    #
    # Caveat: if the user partially deletes existing outputs and reruns, the
    # JSONL will gain new rows for the re-done docs in addition to the prior
    # complete-corpus rows — i.e. duplicates by corpus_id are possible. The
    # summary JSON, by contrast, reflects only the current run's work.
    summary_path = output_dir / "sectionization_report.json"
    per_doc_path = output_dir / "sectionization_report.jsonl.gz"
    corpus_report = CorpusReport(pipeline=pipeline, source=str(source))
    corpus_report.previously_written = skipped_existing_count
    per_doc_handle = open_per_doc_writer(per_doc_path, append=per_doc_path.exists())

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_one_file)(i, output_dir, capture_section_detail, exclude_patterns) for i in files_to_process
    )

    success_count = 0
    fail_count = 0

    try:
        for success, corpus_id, error, status, report in results:
            progress.update(task, advance=1)
            if report is not None:
                corpus_report.add(report)
                write_doc_row(per_doc_handle, report)
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
    finally:
        per_doc_handle.close()

    if failures:
        with open(failures_json, "w") as f:
            json.dump(failures, f, indent=2)

    write_summary_json(summary_path, corpus_report)

    progress.log("\n* Sectionization:")
    progress.log("* Documents written: " + str(success_count))
    progress.log("* Existing outputs skipped: " + str(skipped_existing_count))
    progress.log("* Previously failed inputs skipped: " + str(skipped_previous_failures))
    progress.log("* Failures: " + str(fail_count))
    _render_report_tables(progress, corpus_report)


@click.command()
@click.argument("source", nargs=1)
@click.option(
    "--detailed-report",
    is_flag=True,
    default=False,
    help=(
        "Capture per-section detail (header, chars, paragraphs, outcome) in "
        "every row of sectionization_report.jsonl.gz. Default off — adds ~2x "
        "to the per-doc row size."
    ),
)
def section_dataset(source: Path, detailed_report: bool):
    """Preprocess full-text files in s2orc/pes2o format into headers and subsections.

    NOTE: Each file is assumed to contain one result.
    """
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(source, progress, False, capture_section_detail=detailed_report)


@click.command()
@click.argument("source", nargs=1)
@click.option(
    "--detailed-report",
    is_flag=True,
    default=False,
    help=(
        "Capture per-section detail (header, chars, paragraphs, outcome) in "
        "every row of sectionization_report.jsonl.gz. Default off — adds ~2x "
        "to the per-doc row size."
    ),
)
@click.option(
    "--exclude-patterns",
    default="",
    help=(
        "Comma-separated regex patterns. Documents matching ANY pattern in "
        "title, abstract, or body text are excluded before sectionization."
    ),
)
@click.option(
    "--exclude-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to .txt file with one regex pattern per line. Empty lines and lines starting with # are ignored.",
)
def section_dataset_v2(source: Path, detailed_report: bool, exclude_patterns: str, exclude_file: Path | None):
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
    exclude_patterns_compiled = _compile_exclude_patterns(exclude_patterns or None, exclude_file)
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow(
            source, progress, True, capture_section_detail=detailed_report, exclude_patterns=exclude_patterns_compiled
        )


# ---------------------------------------------------------------------------
# section-dataset-s2orc  (span-annotation format from s2orc_v2)
# ---------------------------------------------------------------------------


def _sectionize_one_file_s2orc_v2(
    input_path: Path,
    output_dir: Path,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Sectionize a single per-document JSON file in s2orc_v2 format.

    Returns (success, corpus_id, error, status, report). `report` is None
    only when the output file already existed (skipped_existing).
    """
    try:
        with open(input_path) as f:
            doc = json.load(f)

        corpus_id = str(doc.get("corpusid", input_path.stem))
        output_file = _sharded_output_file(output_dir, corpus_id)
        if output_file.exists():
            return (True, corpus_id, None, "skipped_existing", None)

        doc = _normalize_to_v2(doc)
        success, sectioned_text, error, report = _sectionize_item_s2orc_v2(
            doc, capture_section_detail=capture_section_detail, exclude_patterns=exclude_patterns
        )
        if not success:
            return (False, corpus_id, error, "failed", report)

        with open(output_file, "w") as f:
            json.dump(sectioned_text, f, indent=4)

        return (True, corpus_id, None, "written", report)
    except Exception as e:
        report = DocReport(corpus_id=input_path.stem, outcome="structural_failure", error=str(e))
        report.finalize()
        return (False, input_path.stem, str(e), "failed", report)


def _sectionize_batch_file_s2orc_v2(
    batch_file: Path,
    output_dir: Path,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
    """Stream one .gz JSONL shard and sectionize each document.

    Per-doc rows are streamed to a per-batch temp gz file (concatenated by
    the parent) so memory stays bounded even on huge shards.
    """
    batch_successes = 0
    batch_failures = []
    skipped_existing = 0
    partial = CorpusReportPartial()

    tmp_report_path = output_dir / f".report_{batch_file.stem}.{os.getpid()}.jsonl.gz"
    tmp_handle = open_per_doc_writer(tmp_report_path, append=False)

    def _add_report(report: DocReport) -> None:
        partial.add(report)
        write_doc_row(tmp_handle, report)

    opener = gzip.open if batch_file.suffix == ".gz" else open
    try:
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

                    doc = _normalize_to_v2(doc)
                    success, sectioned_text, error, report = _sectionize_item_s2orc_v2(
                        doc,
                        capture_section_detail=capture_section_detail,
                        exclude_patterns=exclude_patterns,
                    )
                    _add_report(report)
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
                    exc_report = DocReport(corpus_id=corpus_id, outcome="structural_failure", error=str(e))
                    exc_report.finalize()
                    _add_report(exc_report)
    finally:
        tmp_handle.close()

    return {
        "batch_file": str(batch_file),
        "successes": batch_successes,
        "failures": batch_failures,
        "skipped_existing": skipped_existing,
        "partial": partial,
        "report_tmp": str(tmp_report_path),
    }


def _sectionize_workflow_s2orc_v2(
    source: Path,
    progress: Progress,
    capture_section_detail: bool = False,
    exclude_patterns: list[re.Pattern] | None = None,
):
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
        _sectionize_batches_parallel(
            gz_files,
            output_dir,
            progress,
            source=source,
            pipeline="s2orc_v2",
            batch_fn=_sectionize_batch_file_s2orc_v2,
            capture_section_detail=capture_section_detail,
            exclude_patterns=exclude_patterns,
        )
        return

    # Fall back to per-document JSON files.
    json_files = [p for p in _collect_from_path(source) if p is not None and p.suffix.lower() == ".json"]
    progress.log(f"* Found {len(json_files)} per-document JSON file(s).")
    task = progress.add_task("[green]Sectionizing", total=len(json_files))

    summary_path = output_dir / "sectionization_report.json"
    per_doc_path = output_dir / "sectionization_report.jsonl.gz"
    corpus_report = CorpusReport(pipeline="s2orc_v2", source=str(source))
    # Append on resume (per-doc JSONL exists from a prior run), truncate fresh.
    per_doc_handle = open_per_doc_writer(per_doc_path, append=per_doc_path.exists())

    results = Parallel(n_jobs=-1, return_as="generator")(
        delayed(_sectionize_one_file_s2orc_v2)(p, output_dir, capture_section_detail, exclude_patterns)
        for p in json_files
    )

    success_count = fail_count = skipped_count = 0
    failures = []
    try:
        for success, corpus_id, error, status, report in results:
            progress.update(task, advance=1)
            if report is not None:
                corpus_report.add(report)
                write_doc_row(per_doc_handle, report)
            if success and status == "written":
                success_count += 1
            elif status == "skipped_existing":
                skipped_count += 1
            else:
                fail_count += 1
                failures.append({"corpus_id": corpus_id, "error": error})
                progress.log(f"* Error {corpus_id}: {error}")
    finally:
        per_doc_handle.close()

    corpus_report.previously_written = skipped_count
    write_summary_json(summary_path, corpus_report)

    if failures:
        (output_dir / "failures.json").write_text(json.dumps(failures, indent=2))

    progress.log("\n* Sectionization complete.")
    progress.log(f"* Documents written: {success_count}")
    progress.log(f"* Existing skipped: {skipped_count}")
    progress.log(f"* Failures: {fail_count}")
    _render_report_tables(progress, corpus_report)


@click.command("section-dataset-s2orc")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--detailed-report",
    is_flag=True,
    default=False,
    help=(
        "Capture per-section detail (header, chars, paragraphs, outcome) in "
        "every row of sectionization_report.jsonl.gz. Default off — adds ~2x "
        "to the per-doc row size."
    ),
)
@click.option(
    "--exclude-patterns",
    default="",
    help=(
        "Comma-separated regex patterns. Documents matching ANY pattern in "
        "title or body text are excluded before sectionization."
    ),
)
@click.option(
    "--exclude-file",
    type=click.Path(exists=True, path_type=Path),
    help="Path to .txt file with one regex pattern per line. Empty lines and lines starting with # are ignored.",
)
def section_dataset_s2orc(source: Path, detailed_report: bool, exclude_patterns: str, exclude_file: Path | None):
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
    exclude_patterns_compiled = _compile_exclude_patterns(exclude_patterns or None, exclude_file)
    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        _sectionize_workflow_s2orc_v2(
            source, progress, capture_section_detail=detailed_report, exclude_patterns=exclude_patterns_compiled
        )
