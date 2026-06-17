"""Sectionization reporting.

Per-document and corpus-level accounting for the section-dataset-* pipelines.

The item-level sectionizers (`_sectionize_item_s2orc_v2`, `_sectionize_item_v2`)
emit a `DocReport` describing the outcome of each document and how much of the
input was kept vs. dropped, bucketed by drop reason. The workflow layer feeds
those into a `CorpusReport` which:

  * writes one `sectionization_report.jsonl.gz` row per processed document
    (incrementally, so memory stays bounded even on huge corpora);
  * rewrites `sectionization_report.json` after each completed batch with
    aggregate corpus-wide statistics;
  * renders Rich tables for the end-of-run CLI summary.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO

from rich.table import Table

# ---------------------------------------------------------------------------
# Drop-reason vocabulary
# ---------------------------------------------------------------------------
# Reasons emitted by the per-section loop in the item-level sectionizers.
# Keep this list in sync with the bookkeeping in
# `_sectionize_item_s2orc_v2` and `_sectionize_item_v2`.

DROP_REASONS: tuple[str, ...] = (
    "noise_header",
    "unneeded_no_skip",
    "unneeded_skip_truncation",
    "post_conclusion_truncation",
    "non_substantive",
    "non_english_or_invalid",
    "post_break_truncated",
)

# Document-level outcomes.
OUTCOMES: tuple[str, ...] = (
    "unfiltered",  # kept, zero sections dropped
    "partially_filtered",  # kept, ≥1 section dropped
    "fully_filtered",  # failed because every section was dropped
    "structural_failure",  # failed for non-filter reasons (empty body, etc.)
)


# ---------------------------------------------------------------------------
# Per-section detail (opt-in)
# ---------------------------------------------------------------------------


@dataclass
class SectionDetail:
    """One row per section observed by the sectionizer for a single document.

    Populated only when the caller passes ``capture_section_detail=True`` to
    the item-level sectionizers. Default behavior is to leave `DocReport.sections`
    empty so the memory profile of a large run is unchanged.

    `outcome` is either the literal string ``"kept"`` or one of the values in
    `DROP_REASONS`. `header` is the normalized canonical header string at the
    point it would have entered the filter loop (after `_normalize_header` and
    `apply_synonyms`).
    """

    header: str
    chars: int
    paragraphs: int
    outcome: str  # "kept" or one of DROP_REASONS


# ---------------------------------------------------------------------------
# Per-document report
# ---------------------------------------------------------------------------


@dataclass
class DocReport:
    """Accounting record for a single sectionized document.

    All char / paragraph / section counts refer to *content* (not headers).
    `total_*` denominators reflect everything the sectionizer *saw*, including
    structural elements it later dropped. Pre-pipeline filtering (e.g. things
    dropped before the doc reached this code) is not visible here.
    """

    corpus_id: str
    outcome: str  # one of OUTCOMES
    error: str | None = None

    # Section-level
    kept_sections: int = 0
    dropped_sections: int = 0  # = sum(dropped_sections_by_reason.values())
    total_sections: int = 0  # kept + dropped

    # Paragraph-level
    kept_paragraphs: int = 0
    dropped_paragraphs: int = 0
    total_paragraphs: int = 0

    # Character-level (content only — headers excluded)
    kept_chars: int = 0
    dropped_chars: int = 0
    total_chars: int = 0  # total content chars seen (kept + dropped)

    # Per-reason breakdowns. Each value is a {sections, paragraphs, chars} dict.
    dropped_sections_by_reason: dict[str, dict[str, int]] = field(default_factory=dict)

    # Optional per-section detail rows. Populated only when the sectionizer is
    # invoked with `capture_section_detail=True`. Default empty list keeps the
    # default memory profile unchanged.
    sections: list[SectionDetail] = field(default_factory=list)

    def record_kept(self, *, chars: int, paragraphs: int, header: str | None = None) -> None:
        self.kept_sections += 1
        self.kept_chars += chars
        self.kept_paragraphs += paragraphs
        if header is not None:
            self.sections.append(SectionDetail(header=header, chars=chars, paragraphs=paragraphs, outcome="kept"))

    def record_dropped(
        self,
        reason: str,
        *,
        chars: int,
        paragraphs: int,
        header: str | None = None,
    ) -> None:
        # Caller is responsible for passing a known reason; unknown values
        # land in dropped_sections_by_reason as-is but will NOT show in the
        # rendered Rich table (which iterates DROP_REASONS), so they're
        # functionally invisible in the CLI. This is intentional: we want
        # added reasons to require an explicit DROP_REASONS entry.
        bucket = self.dropped_sections_by_reason.setdefault(reason, {"sections": 0, "paragraphs": 0, "chars": 0})
        bucket["sections"] += 1
        bucket["paragraphs"] += paragraphs
        bucket["chars"] += chars
        self.dropped_sections += 1
        self.dropped_paragraphs += paragraphs
        self.dropped_chars += chars
        if header is not None:
            self.sections.append(SectionDetail(header=header, chars=chars, paragraphs=paragraphs, outcome=reason))

    def finalize(self) -> None:
        """Compute denominators from the kept/dropped sides."""
        self.total_sections = self.kept_sections + self.dropped_sections
        self.total_paragraphs = self.kept_paragraphs + self.dropped_paragraphs
        # total_chars: prefer an externally set value (e.g. len(body.text))
        # if it was already populated; otherwise fall back to kept+dropped.
        if not self.total_chars:
            self.total_chars = self.kept_chars + self.dropped_chars


# ---------------------------------------------------------------------------
# Corpus-wide accumulator
# ---------------------------------------------------------------------------


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return 100.0 * numerator / denominator


def empty_outcomes() -> dict[str, int]:
    return {o: 0 for o in OUTCOMES}


def empty_drops() -> dict[str, dict[str, int]]:
    return {r: {"sections": 0, "paragraphs": 0, "chars": 0} for r in DROP_REASONS}


@dataclass
class CorpusReport:
    pipeline: str
    source: str
    previously_written: int = 0  # docs whose outputs already existed (skipped)

    documents_processed: int = 0
    outcomes: dict[str, int] = field(default_factory=empty_outcomes)

    # Aggregate kept/dropped/total
    kept_sections: int = 0
    dropped_sections: int = 0
    total_sections: int = 0
    kept_paragraphs: int = 0
    dropped_paragraphs: int = 0
    total_paragraphs: int = 0
    kept_chars: int = 0
    dropped_chars: int = 0
    total_chars: int = 0

    drops_by_reason: dict[str, dict[str, int]] = field(default_factory=empty_drops)

    def merge_partial(self, other: "CorpusReportPartial") -> None:
        """Fold a worker-side aggregate into this corpus report.

        Used to keep memory bounded: workers stream per-doc rows to a temp
        file and return only an aggregate (`CorpusReportPartial`) for the
        parent to merge. Avoids shipping per-document records over the joblib
        pipe.
        """
        self.documents_processed += other.documents_processed
        for outcome, count in other.outcomes.items():
            self.outcomes[outcome] = self.outcomes.get(outcome, 0) + count
        self.kept_sections += other.kept_sections
        self.dropped_sections += other.dropped_sections
        self.total_sections += other.total_sections
        self.kept_paragraphs += other.kept_paragraphs
        self.dropped_paragraphs += other.dropped_paragraphs
        self.total_paragraphs += other.total_paragraphs
        self.kept_chars += other.kept_chars
        self.dropped_chars += other.dropped_chars
        self.total_chars += other.total_chars
        for reason, bucket in other.drops_by_reason.items():
            agg = self.drops_by_reason.setdefault(reason, {"sections": 0, "paragraphs": 0, "chars": 0})
            agg["sections"] += bucket["sections"]
            agg["paragraphs"] += bucket["paragraphs"]
            agg["chars"] += bucket["chars"]

    def add(self, doc: DocReport) -> None:
        self.documents_processed += 1
        if doc.outcome in self.outcomes:
            self.outcomes[doc.outcome] += 1
        else:
            self.outcomes.setdefault(doc.outcome, 0)
            self.outcomes[doc.outcome] += 1

        self.kept_sections += doc.kept_sections
        self.dropped_sections += doc.dropped_sections
        self.total_sections += doc.total_sections
        self.kept_paragraphs += doc.kept_paragraphs
        self.dropped_paragraphs += doc.dropped_paragraphs
        self.total_paragraphs += doc.total_paragraphs
        self.kept_chars += doc.kept_chars
        self.dropped_chars += doc.dropped_chars
        self.total_chars += doc.total_chars

        for reason, bucket in doc.dropped_sections_by_reason.items():
            agg = self.drops_by_reason.setdefault(reason, {"sections": 0, "paragraphs": 0, "chars": 0})
            agg["sections"] += bucket["sections"]
            agg["paragraphs"] += bucket["paragraphs"]
            agg["chars"] += bucket["chars"]

    def to_summary_dict(self) -> dict:
        n = self.documents_processed
        return {
            "pipeline": self.pipeline,
            "source": self.source,
            "totals": {
                "documents_processed": n,
                "previously_written": self.previously_written,
                "outcomes": {name: {"count": count, "pct": _pct(count, n)} for name, count in self.outcomes.items()},
                "content_stripped": {
                    "chars": {
                        "kept": self.kept_chars,
                        "dropped": self.dropped_chars,
                        "total": self.total_chars,
                        "pct_dropped": _pct(self.dropped_chars, self.total_chars),
                    },
                    "paragraphs": {
                        "kept": self.kept_paragraphs,
                        "dropped": self.dropped_paragraphs,
                        "total": self.total_paragraphs,
                        "pct_dropped": _pct(self.dropped_paragraphs, self.total_paragraphs),
                    },
                    "sections": {
                        "kept": self.kept_sections,
                        "dropped": self.dropped_sections,
                        "total": self.total_sections,
                        "pct_dropped": _pct(self.dropped_sections, self.total_sections),
                    },
                },
                "drops_by_reason": self.drops_by_reason,
            },
        }

    # -- rendering ----------------------------------------------------------

    def render_tables(self) -> list[Table]:
        return [
            self._render_outcomes_table(),
            self._render_content_stripped_table(),
            self._render_drops_table(),
        ]

    def _render_outcomes_table(self) -> Table:
        n = self.documents_processed
        t = Table(title="Document outcomes", show_lines=False)
        t.add_column("Outcome", style="bold")
        t.add_column("Count", justify="right")
        t.add_column("%", justify="right")
        for outcome in OUTCOMES:
            count = self.outcomes.get(outcome, 0)
            t.add_row(outcome, f"{count:,}", f"{_pct(count, n):.2f}")
        # Surface any unexpected outcome labels (defensive)
        for outcome, count in self.outcomes.items():
            if outcome not in OUTCOMES:
                t.add_row(outcome, f"{count:,}", f"{_pct(count, n):.2f}")
        t.add_section()
        t.add_row(
            "previously_written (skipped this run)",
            f"{self.previously_written:,}",
            "-",
        )
        t.add_row("documents_processed", f"{n:,}", "100.00" if n else "0.00")
        return t

    def _render_content_stripped_table(self) -> Table:
        t = Table(title="Content stripped", show_lines=False)
        t.add_column("Metric", style="bold")
        t.add_column("Kept", justify="right")
        t.add_column("Dropped", justify="right")
        t.add_column("Total", justify="right")
        t.add_column("% Dropped", justify="right")
        rows = [
            ("chars", self.kept_chars, self.dropped_chars, self.total_chars),
            (
                "paragraphs",
                self.kept_paragraphs,
                self.dropped_paragraphs,
                self.total_paragraphs,
            ),
            (
                "sections",
                self.kept_sections,
                self.dropped_sections,
                self.total_sections,
            ),
        ]
        for name, kept, dropped, total in rows:
            t.add_row(
                name,
                f"{kept:,}",
                f"{dropped:,}",
                f"{total:,}",
                f"{_pct(dropped, total):.2f}",
            )
        return t

    def _render_drops_table(self) -> Table:
        t = Table(title="Drops by reason", show_lines=False)
        t.add_column("Reason", style="bold")
        t.add_column("Sections", justify="right")
        t.add_column("Paragraphs", justify="right")
        t.add_column("Chars", justify="right")
        t.add_column("% of dropped sections", justify="right")
        total_dropped_sections = self.dropped_sections
        for reason in DROP_REASONS:
            bucket = self.drops_by_reason.get(reason, {"sections": 0, "paragraphs": 0, "chars": 0})
            t.add_row(
                reason,
                f"{bucket['sections']:,}",
                f"{bucket['paragraphs']:,}",
                f"{bucket['chars']:,}",
                f"{_pct(bucket['sections'], total_dropped_sections):.2f}",
            )
        return t


# ---------------------------------------------------------------------------
# Worker-side aggregate (bounded memory)
# ---------------------------------------------------------------------------


@dataclass
class CorpusReportPartial:
    """A lightweight, picklable subset of CorpusReport for batch workers.

    Workers tally counts here and stream per-doc rows to disk; only this
    object is returned across the joblib boundary. The parent process folds
    each partial into the global CorpusReport via `CorpusReport.merge_partial`.
    """

    documents_processed: int = 0
    outcomes: dict[str, int] = field(default_factory=empty_outcomes)
    kept_sections: int = 0
    dropped_sections: int = 0
    total_sections: int = 0
    kept_paragraphs: int = 0
    dropped_paragraphs: int = 0
    total_paragraphs: int = 0
    kept_chars: int = 0
    dropped_chars: int = 0
    total_chars: int = 0
    drops_by_reason: dict[str, dict[str, int]] = field(default_factory=empty_drops)

    def add(self, doc: DocReport) -> None:
        self.documents_processed += 1
        if doc.outcome in self.outcomes:
            self.outcomes[doc.outcome] += 1
        else:
            self.outcomes[doc.outcome] = self.outcomes.get(doc.outcome, 0) + 1
        self.kept_sections += doc.kept_sections
        self.dropped_sections += doc.dropped_sections
        self.total_sections += doc.total_sections
        self.kept_paragraphs += doc.kept_paragraphs
        self.dropped_paragraphs += doc.dropped_paragraphs
        self.total_paragraphs += doc.total_paragraphs
        self.kept_chars += doc.kept_chars
        self.dropped_chars += doc.dropped_chars
        self.total_chars += doc.total_chars
        for reason, bucket in doc.dropped_sections_by_reason.items():
            agg = self.drops_by_reason.setdefault(reason, {"sections": 0, "paragraphs": 0, "chars": 0})
            agg["sections"] += bucket["sections"]
            agg["paragraphs"] += bucket["paragraphs"]
            agg["chars"] += bucket["chars"]


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_summary_json(path: Path, corpus_report: CorpusReport) -> None:
    """Atomically (best-effort) rewrite the corpus summary JSON file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(corpus_report.to_summary_dict(), indent=2))
    tmp.replace(path)


def open_per_doc_writer(path: Path, append: bool) -> IO[str]:
    """Open the per-doc JSONL.GZ file for streaming writes.

    Pass `append=True` to resume an existing file (resumed run); `False` to
    truncate (fresh run). Returns a text-mode handle.
    """
    mode = "at" if append else "wt"
    return gzip.open(path, mode, encoding="utf-8")


def write_doc_row(handle: IO[str], doc: DocReport) -> None:
    row = asdict(doc)
    if not doc.sections:
        row.pop("sections", None)
    handle.write(json.dumps(row, separators=(",", ":")))
    handle.write("\n")


def append_gz_file(dest_path: Path, src_path: Path) -> None:
    """Append the raw gzip bytes of `src_path` onto `dest_path`.

    Both files are independent gzip members; concatenating them produces a
    valid multi-member gzip stream that decompressors (including `gzip.open`)
    read transparently. Used to merge per-worker temp JSONL.GZ shards into
    the corpus-wide per-doc report without round-tripping through decompress.
    """
    with open(src_path, "rb") as src, open(dest_path, "ab") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
