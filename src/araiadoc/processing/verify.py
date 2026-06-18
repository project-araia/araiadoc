"""Round-trip audit of the sectionization pipeline.

For each sampled document we:

  1. Read the raw s2orc document (v1 or v2 shape — normalized via the same
     helper the production sectionizer uses).
  2. Reconstruct ground-truth sections directly from the header/paragraph
     span annotations, *independent* of the production sectionizer's
     paragraph→header walking logic.
  3. Read the *written* sectionized JSON from disk.
  4. For each ground-truth section, check whether the first 50 characters of
     its first paragraph appear as a substring in the joined sectionized
     output values. This catches a class of bugs that no internal
     accounting can see: silent overwrites on duplicate canonical headers,
     `_normalize_text` over-stripping, output-file truncation, and any
     drift between what the sectionizer *records* as kept vs. what actually
     hits disk.
  5. Attribute each missing section to a drop reason by re-running the same
     filter helpers the production loop uses, and bucket the rest as
     `unknown_after_break` (likely truncated by an earlier skip).

Sample size is bounded and reproducible (`--sample`, `--seed`). Output is a
Rich table on stdout plus an optional JSON report.

This is a *correctness* tool. It does not modify any data and reads only
sectionized outputs that already exist on disk.
"""

from __future__ import annotations

import gzip
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from rich.table import Table

from araiadoc.sectionize import _compile_exclude_patterns, _normalize_to_v2, _parse_spans
from araiadoc.text_quality.content_assessment import (
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
from araiadoc.text_quality.text_validation import is_english

# Substring length used to test whether a ground-truth section's first
# paragraph survived into the written output. 50 chars is enough to avoid
# false positives from boilerplate while tolerating leading-whitespace and
# punctuation normalization differences.
_PRESENCE_PROBE_LEN = 50


# ---------------------------------------------------------------------------
# Per-document audit
# ---------------------------------------------------------------------------


@dataclass
class AuditedSection:
    header: str
    chars: int
    paragraphs: int
    present: bool
    # Drop reason if not present. One of: noise_header, unneeded_no_skip,
    # unneeded_skip_remaining, post_conclusion_truncation, non_substantive,
    # non_english_or_invalid, unknown_after_break, or "" if present.
    reason: str = ""


@dataclass
class DocAudit:
    corpus_id: str
    raw_path: str
    sect_path: str
    title: str = ""
    sections_total: int = 0
    sections_present: int = 0
    sections_missing: int = 0
    raw_chars: int = 0
    sect_chars: int = 0
    missing_chars: int = 0
    missing_by_reason: dict[str, int] = field(default_factory=dict)
    sections: list[AuditedSection] = field(default_factory=list)
    error: str | None = None

    @property
    def loss_pct(self) -> float:
        if self.raw_chars <= 0:
            return 0.0
        return 100.0 * self.missing_chars / self.raw_chars


def _build_ground_truth_sections(doc: dict) -> list[dict]:
    """Reconstruct (header, paragraphs[]) from raw span annotations.

    Each ground-truth section runs from header[i].end to header[i+1].start
    (or to end-of-body for the last header). Paragraphs whose span falls
    entirely within that window are assigned to the section.

    Returns a list of dicts with keys: raw_header, norm_header, paragraphs,
    total_chars. Paragraphs that precede the first header (the abstract /
    pre-header region) are returned as a leading entry with raw_header="".
    """
    body = doc.get("body") or {}
    text = body.get("text") or ""
    annotations = body.get("annotations") or {}
    header_spans = _parse_spans(annotations.get("section_header"))
    para_spans = _parse_spans(annotations.get("paragraph"))

    sections: list[dict] = []

    # Pre-header (abstract-equivalent) region.
    if header_spans:
        first_h_start = header_spans[0]["start"]
        pre_paras = [text[p["start"] : p["end"]] for p in para_spans if p["end"] <= first_h_start]  # noqa
    else:
        # No headers at all — treat the whole body as one synthetic section.
        pre_paras = [text[p["start"] : p["end"]] for p in para_spans]  # noqa

    if pre_paras:
        sections.append(
            {
                "raw_header": "",
                "norm_header": "abstract",
                "paragraphs": pre_paras,
                "total_chars": sum(len(p) for p in pre_paras),
            }
        )

    for i, hs in enumerate(header_spans):
        h_text = text[hs["start"] : hs["end"]]  # noqa
        h_norm = apply_synonyms(_normalize_header(h_text))
        h_end = header_spans[i + 1]["start"] if i + 1 < len(header_spans) else len(text)
        paras = [
            text[p["start"] : p["end"]] for p in para_spans if p["start"] >= hs["end"] and p["end"] <= h_end  # noqa
        ]
        sections.append(
            {
                "raw_header": h_text,
                "norm_header": h_norm,
                "paragraphs": paras,
                "total_chars": sum(len(p) for p in paras),
            }
        )

    return sections


def _diagnose_missing(raw_header: str, norm_header: str, content: str) -> str:
    """Replay the production filter helpers to attribute a missing section."""
    if _header_is_noise(raw_header):
        return "noise_header"

    compare = "".join(norm_header.split()).lower()

    if any(j in compare for j in unneeded_sections_skip_remaining):
        return "unneeded_skip_remaining"
    if any(j in compare for j in needed_sections_but_skip_remaining):
        # The needed-but-skip-after header itself is kept; if it's missing,
        # the most plausible cause is an upstream issue (output overwrite or
        # encoding). Don't claim a positive reason.
        return "unknown_after_break"
    if any(j in compare for j in unneeded_sections_no_skip_remaining):
        return "unneeded_no_skip"

    if content and not _content_is_substantive(content):
        return "non_substantive"
    if content and (not is_english(content) or not is_string_valid(content)):
        return "non_english_or_invalid"

    return "unknown_after_break"


def _audit_loaded_doc(raw: dict, raw_label: str, sect_path: Path, fallback_corpus_id: str) -> DocAudit:
    """Audit an already-loaded raw document against one sectionized JSON file."""
    audit = DocAudit(
        corpus_id=fallback_corpus_id,
        raw_path=raw_label,
        sect_path=str(sect_path),
    )

    try:
        with open(sect_path) as f:
            sect = json.load(f)
    except Exception as e:
        audit.error = f"failed to read sectionized: {e}"
        return audit

    raw = _normalize_to_v2(raw)
    audit.corpus_id = str(raw.get("corpusid", fallback_corpus_id))
    title = raw.get("title") or ""
    audit.title = title if isinstance(title, str) else str(title)

    try:
        gt_sections = _build_ground_truth_sections(raw)
    except Exception as e:
        audit.error = f"failed to reconstruct ground truth: {e}"
        return audit

    sect_text_values = {k: v for k, v in sect.items() if isinstance(v, str)}
    sect_joined = _normalize_text(" ".join(sect_text_values.values()))
    audit.sect_chars = sum(len(v) for v in sect_text_values.values())

    for gt in gt_sections:
        chars = gt["total_chars"]
        paras = gt["paragraphs"]
        if not paras:
            # No paragraph content under this header — nothing to verify and
            # nothing the sectionizer was expected to keep. Skip silently.
            continue

        first = _normalize_text(paras[0])
        probe = first[:_PRESENCE_PROBE_LEN].strip()
        present = bool(probe) and probe in sect_joined

        sec = AuditedSection(
            header=gt["norm_header"] or "abstract",
            chars=chars,
            paragraphs=len(paras),
            present=present,
        )

        if not present:
            reason = _diagnose_missing(gt["raw_header"], gt["norm_header"], " ".join(paras))
            sec.reason = reason
            audit.sections_missing += 1
            audit.missing_chars += chars
            audit.missing_by_reason[reason] = audit.missing_by_reason.get(reason, 0) + 1
        else:
            audit.sections_present += 1

        audit.sections.append(sec)
        audit.sections_total += 1
        audit.raw_chars += chars

    return audit


def audit_one(raw_path: Path, sect_path: Path) -> DocAudit:
    """Audit a single per-document raw JSON file against one sectionized JSON."""
    try:
        with open(raw_path) as f:
            raw = json.load(f)
    except Exception as e:
        audit = DocAudit(
            corpus_id=raw_path.stem,
            raw_path=str(raw_path),
            sect_path=str(sect_path),
        )
        audit.error = f"failed to read raw: {e}"
        return audit
    return _audit_loaded_doc(raw, str(raw_path), sect_path, raw_path.stem)


# ---------------------------------------------------------------------------
# Corpus-level aggregation
# ---------------------------------------------------------------------------


@dataclass
class CorpusAudit:
    raw_dir: str
    sect_dir: str
    sampled: int = 0
    audited: int = 0
    skipped_missing_sect: int = 0
    excluded_by_pattern: int = 0
    excluded_by_pattern_reasons: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    sections_total: int = 0
    sections_present: int = 0
    sections_missing: int = 0
    raw_chars: int = 0
    missing_chars: int = 0
    missing_by_reason: dict[str, int] = field(default_factory=dict)
    docs: list[DocAudit] = field(default_factory=list)

    def add(self, doc: DocAudit) -> None:
        self.docs.append(doc)
        if doc.error:
            self.errors += 1
            return
        self.audited += 1
        self.sections_total += doc.sections_total
        self.sections_present += doc.sections_present
        self.sections_missing += doc.sections_missing
        self.raw_chars += doc.raw_chars
        self.missing_chars += doc.missing_chars
        for reason, count in doc.missing_by_reason.items():
            self.missing_by_reason[reason] = self.missing_by_reason.get(reason, 0) + count

    @property
    def loss_pct(self) -> float:
        if self.raw_chars <= 0:
            return 0.0
        return 100.0 * self.missing_chars / self.raw_chars

    @property
    def section_loss_pct(self) -> float:
        if self.sections_total <= 0:
            return 0.0
        return 100.0 * self.sections_missing / self.sections_total

    def to_dict(self, include_docs: bool = False) -> dict:
        out = {
            "raw_dir": self.raw_dir,
            "sect_dir": self.sect_dir,
            "sampled": self.sampled,
            "audited": self.audited,
            "skipped_missing_sect": self.skipped_missing_sect,
            "excluded_by_pattern": self.excluded_by_pattern,
            "errors": self.errors,
            "sections_total": self.sections_total,
            "sections_present": self.sections_present,
            "sections_missing": self.sections_missing,
            "raw_chars": self.raw_chars,
            "missing_chars": self.missing_chars,
            "loss_pct": self.loss_pct,
            "section_loss_pct": self.section_loss_pct,
            "missing_by_reason": self.missing_by_reason,
            "excluded_by_pattern_reasons": dict(sorted(self.excluded_by_pattern_reasons.items(), key=lambda x: -x[1])),
        }
        if include_docs:
            out["docs"] = [asdict(d) for d in self.docs]
        return out


# ---------------------------------------------------------------------------
# File discovery + CLI
# ---------------------------------------------------------------------------


def _sharded_path(base: Path, corpus_id: str) -> Path:
    """Pure version of `_sharded_output_file` — never creates directories.

    Mirrors the sharding rule in `sectionize._sharded_output_file`: the last
    two characters of the corpus_id (or the whole id if shorter) name the
    bucket directory.
    """
    shard = corpus_id[-2:] if len(corpus_id) >= 2 else corpus_id
    return base / shard / f"{corpus_id}.json"


def _iter_raw_json_docs(raw_dir: Path):
    """Yield every per-document .json path under a raw directory."""
    for path in sorted(raw_dir.rglob("*.json")):
        if path.is_file():
            yield path


def _iter_raw_gz_files(raw_dir: Path) -> list[Path]:
    """Return raw JSONL(.gz) shards under a raw directory."""
    return [p for p in sorted(raw_dir.rglob("*.gz")) if p.is_file()]


def _iter_gz_docs(gz_files: list[Path]):
    """Yield (doc, raw_label, corpus_id) from JSONL.GZ shard files."""
    for gz_path in gz_files:
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                corpus_id = str(doc.get("corpusid", f"{gz_path.stem}_line_{line_number}"))
                yield doc, f"{gz_path}:{line_number}", corpus_id


def _reservoir_sample_gz_docs(gz_files: list[Path], sample: int, seed: int):
    """Sample documents from gz shards without materializing the corpus."""
    rng = random.Random(seed)
    reservoir: list[tuple[dict, str, str]] = []
    seen = 0
    for item in _iter_gz_docs(gz_files):
        seen += 1
        if len(reservoir) < sample:
            reservoir.append(item)
            continue
        idx = rng.randrange(seen)
        if idx < sample:
            reservoir[idx] = item
    return reservoir, seen


def _render_summary_table(audit: CorpusAudit) -> Table:
    t = Table(title="Sectionization audit (sampled)")
    t.add_column("Metric", style="bold")
    t.add_column("Value", justify="right")
    t.add_row("Sampled docs", f"{audit.sampled:,}")
    t.add_row("Audited (sect file found)", f"{audit.audited:,}")
    t.add_row("Skipped (no sect file)", f"{audit.skipped_missing_sect:,}")
    t.add_row("Excluded by pattern", f"{audit.excluded_by_pattern:,}")
    t.add_row("Errors", f"{audit.errors:,}")
    t.add_section()
    t.add_row("Sections (raw)", f"{audit.sections_total:,}")
    t.add_row("Sections present", f"{audit.sections_present:,}")
    t.add_row("Sections missing", f"{audit.sections_missing:,}")
    t.add_row("Section loss %", f"{audit.section_loss_pct:.2f}")
    t.add_section()
    t.add_row("Raw content chars", f"{audit.raw_chars:,}")
    t.add_row("Missing content chars", f"{audit.missing_chars:,}")
    t.add_row("Content loss %", f"{audit.loss_pct:.2f}")
    return t


def _render_reasons_table(audit: CorpusAudit) -> Table:
    t = Table(title="Missing sections by attributed reason")
    t.add_column("Reason", style="bold")
    t.add_column("Count", justify="right")
    t.add_column("% of missing", justify="right")
    total = audit.sections_missing
    for reason in sorted(audit.missing_by_reason, key=lambda k: -audit.missing_by_reason[k]):
        count = audit.missing_by_reason[reason]
        pct = 100.0 * count / total if total else 0.0
        t.add_row(reason, f"{count:,}", f"{pct:.2f}")
    if not audit.missing_by_reason:
        t.add_row("(none)", "0", "0.00")
    return t


def _render_exclude_table(audit: CorpusAudit) -> Table | None:
    if not audit.excluded_by_pattern_reasons:
        return None
    t = Table(title="Excluded-by-pattern breakdown")
    t.add_column("Pattern", style="bold")
    t.add_column("Docs excluded", justify="right")
    for pattern, count in audit.excluded_by_pattern_reasons.items():
        t.add_row(pattern, f"{count:,}")
    return t


def _doc_full_text(raw: dict) -> str:
    """Build the same combined text the sectionizer uses for pattern matching."""
    title = raw.get("title") or ""
    body = raw.get("body") or {}
    text = body.get("text") or ""
    if not text:
        content = raw.get("content") or {}
        text = content.get("text") or ""
    return " ".join(filter(None, [title, text]))


@click.command("verify-sectionization")
@click.argument("raw_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("sect_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--sample",
    "-n",
    type=int,
    default=1000,
    show_default=True,
    help="Sample size. Use 0 to audit every document.",
)
@click.option(
    "--seed",
    type=int,
    default=0,
    show_default=True,
    help="RNG seed for reproducible sampling.",
)
@click.option(
    "--report-json",
    type=click.Path(path_type=Path),
    default=None,
    help="If set, write a JSON audit report to this path.",
)
@click.option(
    "--include-docs",
    is_flag=True,
    default=False,
    help="Include per-document detail in --report-json output. Off by default.",
)
@click.option(
    "--fail-threshold",
    type=float,
    default=None,
    help=("If set, exit nonzero when corpus-wide content loss % exceeds this " "threshold. Useful in CI."),
)
@click.option(
    "--exclude-patterns",
    default="",
    help="Comma-separated regex patterns that were used to exclude documents.",
)
@click.option(
    "--exclude-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to .txt file with one regex pattern per line.",
)
def verify_sectionization(
    raw_dir: Path,
    sect_dir: Path,
    sample: int,
    seed: int,
    report_json: Path | None,
    include_docs: bool,
    fail_threshold: float | None,
    exclude_patterns: str,
    exclude_file: Path | None,
):
    """Audit a sectionized corpus against its raw input.

    RAW_DIR is either a directory of raw s2orc JSONL.GZ shards (for the
    normal `section-dataset-s2orc` streaming workflow) or a directory of raw
    per-document JSON files (typically sharded as <bucket>/<corpus_id>.json).

    SECT_DIR is the corresponding sectionized output directory (typically
    `<raw>_sectionized`, sharded as <bucket>/<corpus_id>.json).

    For each sampled document, the auditor walks the raw header/paragraph
    span annotations to reconstruct ground-truth sections, then verifies
    that each section's first paragraph survives into the written
    sectionized JSON. Missing sections are attributed to the same filter
    reasons the production sectionizer would have used.
    """
    console = Console()
    gz_files = _iter_raw_gz_files(raw_dir)
    json_paths = list(_iter_raw_json_docs(raw_dir)) if not gz_files else []

    if not gz_files and not json_paths:
        console.print(f"[red]No raw .json or .gz documents found under {raw_dir}[/red]")
        raise click.exceptions.Exit(code=2)

    audit = CorpusAudit(raw_dir=str(raw_dir), sect_dir=str(sect_dir))
    compiled_patterns = _compile_exclude_patterns(exclude_patterns or None, exclude_file)

    if gz_files:
        if sample > 0:
            sampled_docs, docs_seen = _reservoir_sample_gz_docs(gz_files, sample, seed)
            audit.sampled = len(sampled_docs)
            console.print(f"Sampled {len(sampled_docs):,} document(s) from {docs_seen:,} raw shard rows.")
            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                task = progress.add_task("[cyan]Auditing", total=len(sampled_docs))
                for raw_doc, raw_label, corpus_id in sampled_docs:
                    sect_path = _sharded_path(sect_dir, corpus_id)
                    if not sect_path.exists():
                        if compiled_patterns:
                            ft = _doc_full_text(raw_doc)
                            matched = [p.pattern for p in compiled_patterns if p.search(ft)]
                            if matched:
                                audit.excluded_by_pattern += 1
                                for p in matched:
                                    audit.excluded_by_pattern_reasons[p] = (
                                        audit.excluded_by_pattern_reasons.get(p, 0) + 1
                                    )
                                progress.update(task, advance=1)
                                continue
                        audit.skipped_missing_sect += 1
                        progress.update(task, advance=1)
                        continue
                    audit.add(_audit_loaded_doc(raw_doc, raw_label, sect_path, corpus_id))
                    progress.update(task, advance=1)
        else:
            with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
                task = progress.add_task("[cyan]Auditing", total=None)
                for raw_doc, raw_label, corpus_id in _iter_gz_docs(gz_files):
                    audit.sampled += 1
                    sect_path = _sharded_path(sect_dir, corpus_id)
                    if not sect_path.exists():
                        if compiled_patterns:
                            ft = _doc_full_text(raw_doc)
                            matched = [p.pattern for p in compiled_patterns if p.search(ft)]
                            if matched:
                                audit.excluded_by_pattern += 1
                                for p in matched:
                                    audit.excluded_by_pattern_reasons[p] = (
                                        audit.excluded_by_pattern_reasons.get(p, 0) + 1
                                    )
                                progress.update(task, advance=1)
                                continue
                        audit.skipped_missing_sect += 1
                        progress.update(task, advance=1)
                        continue
                    audit.add(_audit_loaded_doc(raw_doc, raw_label, sect_path, corpus_id))
                    progress.update(task, advance=1)
    else:
        rng = random.Random(seed)
        if sample > 0 and sample < len(json_paths):
            sampled_paths = rng.sample(json_paths, sample)
        else:
            sampled_paths = list(json_paths)
            rng.shuffle(sampled_paths)
        audit.sampled = len(sampled_paths)

        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            task = progress.add_task("[cyan]Auditing", total=len(sampled_paths))
            for raw_path in sampled_paths:
                corpus_id = raw_path.stem
                sect_path = _sharded_path(sect_dir, corpus_id)
                if not sect_path.exists():
                    if compiled_patterns:
                        try:
                            with open(raw_path) as f:
                                raw_doc = json.load(f)
                            ft = _doc_full_text(raw_doc)
                            matched = [p.pattern for p in compiled_patterns if p.search(ft)]
                            if matched:
                                audit.excluded_by_pattern += 1
                                for p in matched:
                                    audit.excluded_by_pattern_reasons[p] = (
                                        audit.excluded_by_pattern_reasons.get(p, 0) + 1
                                    )
                                progress.update(task, advance=1)
                                continue
                        except Exception:
                            pass
                    audit.skipped_missing_sect += 1
                    progress.update(task, advance=1)
                    continue
                audit.add(audit_one(raw_path, sect_path))
                progress.update(task, advance=1)

    console.print()
    console.print(_render_summary_table(audit))
    console.print(_render_reasons_table(audit))
    exclude_table = _render_exclude_table(audit)
    if exclude_table:
        console.print(exclude_table)

    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(audit.to_dict(include_docs=include_docs), indent=2))
        console.print(f"\n[green]Audit JSON written to {report_json}[/green]")

    if fail_threshold is not None and audit.loss_pct > fail_threshold:
        console.print(f"\n[red]Content loss {audit.loss_pct:.2f}% exceeds threshold " f"{fail_threshold:.2f}%[/red]")
        raise click.exceptions.Exit(code=1)
