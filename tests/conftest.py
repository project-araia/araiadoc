"""Shared pytest fixtures for araiadoc tests.

Helpers build minimal but realistic synthetic s2orc documents in either the
v1 (content/sectionheader) or v2 (body/section_header) shape used by the
production sectionizers.  Annotation values are JSON-encoded strings of span
lists, matching the format produced by the upstream s2orc dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path to committed real-document fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_RAW_DIR = FIXTURES_DIR / "raw"
FIXTURES_SECT_DIR = FIXTURES_DIR / "sectionized"


# ---------------------------------------------------------------------------
# Helpers for building synthetic s2orc documents
# ---------------------------------------------------------------------------


def _encode_spans(spans: list[dict]) -> str:
    """JSON-encode a list of span dicts the way s2orc stores them."""
    return json.dumps(spans)


def make_v2_doc(
    *,
    corpusid: int = 99999,
    title: str = "",
    body_text: str = "",
    para_spans: list[dict] | None = None,
    header_spans: list[dict] | None = None,
    extra_annotations: dict | None = None,
) -> dict:
    """Build a minimal s2orc v2 document dict.

    ``para_spans`` and ``header_spans`` are plain Python dicts; they are
    JSON-encoded here so the returned doc matches the on-disk format.
    """
    annotations: dict[str, str] = {}
    if para_spans is not None:
        annotations["paragraph"] = _encode_spans(para_spans)
    if header_spans is not None:
        annotations["section_header"] = _encode_spans(header_spans)
    if extra_annotations:
        for k, v in extra_annotations.items():
            annotations[k] = _encode_spans(v) if isinstance(v, list) else v

    doc: dict = {
        "corpusid": corpusid,
        "body": {
            "text": body_text,
            "annotations": annotations,
        },
    }
    if title:
        doc["title"] = title
    return doc


def make_v1_doc(
    *,
    corpusid: int = 88888,
    body_text: str = "",
    para_spans: list[dict] | None = None,
    header_spans: list[dict] | None = None,
    title_spans: list[dict] | None = None,
    external_ids: dict | None = None,
) -> dict:
    """Build a minimal s2orc v1 document dict.

    v1 nests everything under ``content`` and uses ``sectionheader`` (no
    underscore). There is no top-level ``title`` field; title is recovered
    from an annotation span or the first line of body text.
    """
    annotations: dict[str, str] = {}
    if para_spans is not None:
        annotations["paragraph"] = _encode_spans(para_spans)
    if header_spans is not None:
        annotations["sectionheader"] = _encode_spans(header_spans)
    if title_spans is not None:
        annotations["title"] = _encode_spans(title_spans)

    doc: dict = {
        "corpusid": corpusid,
        "content": {
            "text": body_text,
            "annotations": annotations,
        },
    }
    if external_ids is not None:
        doc["externalids"] = external_ids
    return doc


# ---------------------------------------------------------------------------
# A self-contained synthetic document with a known layout:
#
#   text = "Title line\nIntro paragraph here.\nBackground section.\nSecond background para.\nConclusion text."
#
#   Offsets (character-precise):
#     title span:       [0, 10]   → "Title line"
#     para 0 (pre-hdr): [11, 31]  → "Intro paragraph here."   (before any header)
#     header 0:         [32, 42]  → "Background"
#     para 1:           [43, 62]  → "Second background para."   (truncated to fit)
#     header 1:         [63, 73]  → "Conclusion"
#     para 2:           [74, 89]  → "Conclusion text."
# ---------------------------------------------------------------------------

SYNTH_TEXT = (
    "Title line\n"  # [0:11]   → 0..10 = "Title line"
    "Intro paragraph here.\n"  # [11:33]  → 11..32 = "Intro paragraph here."
    "Background\n"  # [33:44]  → 33..43 = "Background"
    "Second para here.\n"  # [44:63]  → 44..62 = "Second para here."
    "Conclusion\n"  # [63:74]  → 63..73 = "Conclusion"
    "Conclusion text."  # [74:90]  → 74..90 = "Conclusion text."
)


@pytest.fixture
def synth_v2_doc() -> dict:
    """Synthetic v2 doc with known section structure for sectionizer tests.

    Offsets are character-precise against SYNTH_TEXT (verified by slicing).
    """
    title_span = {"start": 0, "end": 10}  # "Title line"
    pre_header_para = {"start": 11, "end": 32}  # "Intro paragraph here."
    header0 = {"start": 33, "end": 43}  # "Background"
    para1 = {"start": 44, "end": 61}  # "Second para here."
    header1 = {"start": 62, "end": 72}  # "Conclusion"
    para2 = {"start": 73, "end": 89}  # "Conclusion text."

    return make_v2_doc(
        corpusid=12345,
        title="Title line",
        body_text=SYNTH_TEXT,
        para_spans=[pre_header_para, para1, para2],
        header_spans=[header0, header1],
        extra_annotations={"title": [title_span]},
    )


@pytest.fixture
def golden_raw_dir() -> Path:
    return FIXTURES_RAW_DIR


@pytest.fixture
def golden_sect_dir() -> Path:
    return FIXTURES_SECT_DIR
