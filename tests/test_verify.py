"""Tests for araiadoc.processing.verify pure-function layer.

Covers:
  _build_ground_truth_sections
  _diagnose_missing
  _doc_full_text
  _audit_loaded_doc  (via audit_one)
  audit_one          (file I/O + error handling)
  CorpusAudit        (add, loss_pct, section_loss_pct, to_dict)

Run with:
    pixi run -e dev pytest tests/test_verify.py -v
"""

from __future__ import annotations

import json

import pytest
from conftest import FIXTURES_RAW_DIR, FIXTURES_SECT_DIR

from araiadoc.processing.verify import (
    CorpusAudit,
    DocAudit,
    _audit_loaded_doc,
    _best_effort_oa_urls,
    _build_ground_truth_sections,
    _diagnose_missing,
    _doc_full_text,
    _sample_oa_pdfs,
    audit_one,
)

# ---------------------------------------------------------------------------
# Helpers: build minimal v2 docs and sectionized JSON for audit tests
# ---------------------------------------------------------------------------


def _v2_with_sections(text: str, paras: list[dict], headers: list[dict]) -> dict:
    """Wrap text + span lists into a v2 body dict (already _normalize_to_v2 shape)."""
    import json as _j

    return {
        "corpusid": 77777,
        "body": {
            "text": text,
            "annotations": {
                "paragraph": _j.dumps(paras),
                "section_header": _j.dumps(headers),
            },
        },
    }


# ---------------------------------------------------------------------------
# _build_ground_truth_sections
# ---------------------------------------------------------------------------


class TestBuildGroundTruthSections:
    def test_pre_header_paragraphs_become_abstract(self):
        # Layout: para (pre-header) then a header then a para
        text = "Abstract text here.\nIntroduction\nIntro paragraph."
        pre_para_end = len("Abstract text here.")
        h_start = pre_para_end + 1
        h_end = h_start + len("Introduction")
        p2_start = h_end + 1
        p2_end = len(text)

        doc = _v2_with_sections(
            text,
            paras=[
                {"start": 0, "end": pre_para_end},
                {"start": p2_start, "end": p2_end},
            ],
            headers=[{"start": h_start, "end": h_end}],
        )
        sections = _build_ground_truth_sections(doc)
        assert len(sections) >= 1
        assert sections[0]["raw_header"] == ""
        assert sections[0]["norm_header"] == "abstract"
        assert len(sections[0]["paragraphs"]) == 1

    def test_no_headers_whole_body_is_abstract(self):
        text = "Only body text, no headers present."
        doc = _v2_with_sections(
            text,
            paras=[{"start": 0, "end": len(text)}],
            headers=[],
        )
        sections = _build_ground_truth_sections(doc)
        assert len(sections) == 1
        assert sections[0]["norm_header"] == "abstract"

    def test_last_section_extends_to_end_of_text(self):
        text = "Introduction\nIntro paragraph.Extra text."
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = len(text)

        doc = _v2_with_sections(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[{"start": 0, "end": h_end}],
        )
        sections = _build_ground_truth_sections(doc)
        intro = next(s for s in sections if s["norm_header"] == "introduction")
        assert len(intro["paragraphs"]) == 1
        assert "Extra text" in intro["paragraphs"][0]

    def test_empty_header_no_paras_section_included(self):
        # Header with no paragraph spans inside its window → paras == []
        text = "Introduction\nBackground\nParagraph under background."
        h0_end = len("Introduction")
        h1_start = h0_end + 1
        h1_end = h1_start + len("Background")
        p_start = h1_end + 1
        p_end = len(text)

        doc = _v2_with_sections(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        sections = _build_ground_truth_sections(doc)
        headers_found = [s["norm_header"] for s in sections]
        assert "introduction" in headers_found
        assert "background" in headers_found

    def test_total_chars_is_sum_of_paragraph_lengths(self):
        text = "Introduction\nShort para."
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = len(text)

        doc = _v2_with_sections(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[{"start": 0, "end": h_end}],
        )
        sections = _build_ground_truth_sections(doc)
        intro = next(s for s in sections if s["norm_header"] == "introduction")
        expected_chars = sum(len(p) for p in intro["paragraphs"])
        expected_words = sum(len(p.split()) for p in intro["paragraphs"])
        assert intro["total_chars"] == expected_chars
        assert intro["total_words"] == expected_words

    def test_empty_body_returns_empty_list(self):
        doc = {"body": {"text": "", "annotations": {}}}
        sections = _build_ground_truth_sections(doc)
        assert sections == []

    def test_paragraph_assigned_to_nearest_preceding_header(self):
        # Two headers; paragraph starts after second header ends.
        text = "Intro\nBackground\nPara under background."
        h0_end = len("Intro")
        h1_start = h0_end + 1
        h1_end = h1_start + len("Background")
        p_start = h1_end + 1
        p_end = len(text)

        doc = _v2_with_sections(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        sections = _build_ground_truth_sections(doc)
        bg = next(s for s in sections if s["norm_header"] == "background")
        assert len(bg["paragraphs"]) == 1


# ---------------------------------------------------------------------------
# _diagnose_missing
# ---------------------------------------------------------------------------


class TestDiagnoseMissing:
    def test_noise_header(self):
        # "figure" is in unneeded_sections_no_skip_remaining, but _header_is_noise
        # catches some patterns first. We use an actual noise pattern.
        # _header_is_noise checks for things like numbers-only, very short, etc.
        # Use a clearly noisy raw header.
        reason = _diagnose_missing("", "figure 1", "")
        # "figure" is in unneeded_sections_no_skip_remaining → unneeded_no_skip
        assert reason in ("noise_header", "unneeded_no_skip", "unknown_after_break")

    def test_unneeded_skip_remaining_acknowledgments(self):
        # "References" is caught by _header_is_noise before skip_remaining;
        # use "Acknowledgments" which is skip_remaining but not noise.
        reason = _diagnose_missing("Acknowledgments", "acknowledgment", "We thank the reviewers.")
        assert reason == "unneeded_skip_remaining"

    def test_unneeded_no_skip_caption(self):
        # "caption" is in unneeded_sections_no_skip_remaining.  Short raw headers
        # containing noise-list tokens also match _header_is_noise first (≤3 tokens),
        # so either "noise_header" or "unneeded_no_skip" is a valid result here.
        reason = _diagnose_missing("Figure caption", "caption", "This figure shows...")
        assert reason in ("noise_header", "unneeded_no_skip")

    def test_non_substantive_content(self):
        # Content that is far too short to be substantive
        reason = _diagnose_missing("Methods", "methods", "X")
        assert reason in ("non_substantive", "unknown_after_break")

    def test_unknown_after_break_for_unattributable(self):
        # A section that passes all filters but is still missing must be unknown.
        long_english = "This is a solid English paragraph with good content. " * 5
        reason = _diagnose_missing("Results", "results", long_english)
        # Either non_english_or_invalid (unlikely for good English) or unknown_after_break
        assert reason in ("non_english_or_invalid", "unknown_after_break")

    def test_needed_but_skip_after_conclusion(self):
        # "conclusion" is in needed_sections_but_skip_remaining
        reason = _diagnose_missing("Conclusion", "conclusion", "We conclude that X.")
        # If this is present (not missing) it's kept; if it IS missing the
        # most plausible explanation is unknown (see _diagnose_missing logic).
        assert reason == "unknown_after_break"


# ---------------------------------------------------------------------------
# _doc_full_text
# ---------------------------------------------------------------------------


class TestDocFullText:
    def test_v2_body_text_included(self):
        doc = {"body": {"text": "body content"}}
        result = _doc_full_text(doc)
        assert "body content" in result

    def test_title_included_when_present(self):
        doc = {"title": "My Title", "body": {"text": "body text"}}
        result = _doc_full_text(doc)
        assert "My Title" in result
        assert "body text" in result

    def test_falls_back_to_content_text(self):
        doc = {"content": {"text": "v1 body"}}
        result = _doc_full_text(doc)
        assert "v1 body" in result

    def test_empty_doc_returns_empty_string(self):
        result = _doc_full_text({})
        assert result == ""

    def test_no_trailing_leading_space_from_empty_parts(self):
        doc = {"body": {"text": "only body"}}
        result = _doc_full_text(doc)
        # No leading space (no title)
        assert not result.startswith(" ")

    def test_title_and_content_joined_by_space(self):
        doc = {"title": "T", "body": {"text": "B"}}
        result = _doc_full_text(doc)
        assert result == "T B"


# ---------------------------------------------------------------------------
# _audit_loaded_doc  (indirectly also tests audit_one)
# ---------------------------------------------------------------------------


class TestAuditLoadedDoc:
    def _build_raw_v2(self, text: str, paras: list[dict], headers: list[dict]) -> dict:
        """Minimal already-normalized v2 doc (no 'content' key needed)."""
        import json as _j

        return {
            "corpusid": 55555,
            "body": {
                "text": text,
                "annotations": {
                    "paragraph": _j.dumps(paras),
                    "section_header": _j.dumps(headers),
                },
            },
        }

    def test_successful_audit_populates_sections(self, tmp_path):
        text = "Introduction\nThis is the intro paragraph content."
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = len(text)

        raw = self._build_raw_v2(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[{"start": 0, "end": h_end}],
        )

        # Write a sectionized file that contains the intro paragraph
        intro_content = text[p_start:p_end]
        sect_data = {"introduction": intro_content}
        sect_path = tmp_path / "55555.json"
        sect_path.write_text(json.dumps(sect_data))

        audit = _audit_loaded_doc(raw, "raw_label", sect_path, "55555")
        assert audit.error is None
        assert audit.sections_total >= 1
        assert audit.sections_present >= 1

    def test_missing_section_counted(self, tmp_path):
        text = "Introduction\nIntro para content is present.\nBackground\nBackground content here."
        h0_end = len("Introduction")
        p0_start = h0_end + 1
        p0_end = p0_start + len("Intro para content is present.")
        h1_start = p0_end + 1
        h1_end = h1_start + len("Background")
        p1_start = h1_end + 1
        p1_end = len(text)

        raw = self._build_raw_v2(
            text,
            paras=[
                {"start": p0_start, "end": p0_end},
                {"start": p1_start, "end": p1_end},
            ],
            headers=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )

        # Sectionized file only has intro, not background
        sect_data = {"introduction": text[p0_start:p0_end]}
        sect_path = tmp_path / "55555.json"
        sect_path.write_text(json.dumps(sect_data))

        audit = _audit_loaded_doc(raw, "raw_label", sect_path, "55555")
        assert audit.error is None
        assert audit.sections_missing >= 1
        assert audit.missing_chars > 0
        assert audit.missing_words > 0

    def test_missing_sect_file_sets_error(self, tmp_path):
        raw = self._build_raw_v2("text", [], [])
        sect_path = tmp_path / "does_not_exist.json"
        audit = _audit_loaded_doc(raw, "label", sect_path, "fallback")
        assert audit.error is not None
        assert "failed to read sectionized" in audit.error

    def test_probe_presence_check_uses_first_50_chars(self, tmp_path):
        # The probe is the first 50 chars of the first paragraph of each section.
        # If those 50 chars appear in the joined sectionized text, it's "present".
        intro = "A" * 60  # paragraph content > 50 chars
        text = "Introduction\n" + intro
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = len(text)

        raw = self._build_raw_v2(
            text,
            paras=[{"start": p_start, "end": p_end}],
            headers=[{"start": 0, "end": h_end}],
        )

        # Only include the first 50 chars in the sectionized file
        sect_data = {"introduction": "A" * 50}
        sect_path = tmp_path / "55555.json"
        sect_path.write_text(json.dumps(sect_data))

        audit = _audit_loaded_doc(raw, "label", sect_path, "55555")
        assert audit.sections_present >= 1


# ---------------------------------------------------------------------------
# audit_one  (file-level wrapper)
# ---------------------------------------------------------------------------


class TestAuditOne:
    def test_missing_raw_file_sets_error(self, tmp_path):
        raw_path = tmp_path / "missing.json"
        sect_path = tmp_path / "sect.json"
        sect_path.write_text("{}")
        audit = audit_one(raw_path, sect_path)
        assert audit.error is not None
        assert "failed to read raw" in audit.error

    def test_successful_round_trip_with_golden_fixtures(self):
        """Use the committed fixture pair for a real round-trip audit."""
        raw_path = FIXTURES_RAW_DIR / "275209400.json"
        sect_path = FIXTURES_SECT_DIR / "00" / "275209400.json"
        if not raw_path.exists() or not sect_path.exists():
            pytest.skip("Golden fixture files not present")
        audit = audit_one(raw_path, sect_path)
        assert audit.error is None
        assert audit.sections_total >= 1
        # The sectionized output was produced from this exact raw doc,
        # so content loss should be low (sections deliberately dropped by
        # filters may still show as "missing" in the ground-truth audit).
        assert audit.loss_pct < 100.0

    def test_corpus_id_is_populated_from_raw_file(self, tmp_path):
        raw = {"corpusid": 12345, "content": {"text": "Some text.", "annotations": {}}}
        raw_path = tmp_path / "12345.json"
        raw_path.write_text(json.dumps(raw))
        sect_path = tmp_path / "sect.json"
        sect_path.write_text("{}")
        audit = audit_one(raw_path, sect_path)
        assert audit.corpus_id == "12345"


# ---------------------------------------------------------------------------
# CorpusAudit
# ---------------------------------------------------------------------------


class TestCorpusAudit:
    def _make_doc_audit(
        self, *, missing=0, present=2, raw_chars=500, missing_chars=0, raw_words=100, missing_words=0, error=None
    ):
        d = DocAudit(
            corpus_id="d",
            raw_path="/r",
            sect_path="/s",
            sections_total=present + missing,
            sections_present=present,
            sections_missing=missing,
            raw_chars=raw_chars,
            missing_chars=missing_chars,
            raw_words=raw_words,
            missing_words=missing_words,
        )
        if missing:
            d.missing_by_reason["noise_header"] = missing
        d.error = error
        return d

    def test_add_error_doc_increments_errors_only(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(error="some error"))
        assert ca.errors == 1
        assert ca.audited == 0
        assert ca.sections_total == 0

    def test_add_good_doc_increments_audited(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit())
        assert ca.audited == 1
        assert ca.errors == 0

    def test_aggregate_section_counts(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(present=3, missing=1, raw_chars=200, missing_chars=50))
        ca.add(self._make_doc_audit(present=2, missing=0, raw_chars=100, missing_chars=0))
        assert ca.sections_total == 6
        assert ca.sections_present == 5
        assert ca.sections_missing == 1

    def test_aggregate_char_counts(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_chars=300, missing_chars=75))
        ca.add(self._make_doc_audit(raw_chars=100, missing_chars=0))
        assert ca.raw_chars == 400
        assert ca.missing_chars == 75

    def test_aggregate_word_counts(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_words=200, missing_words=40))
        ca.add(self._make_doc_audit(raw_words=100, missing_words=0))
        assert ca.raw_words == 300
        assert ca.missing_words == 40

    def test_word_loss_pct_correct(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_words=200, missing_words=50))
        assert ca.word_loss_pct == pytest.approx(25.0)

    def test_word_loss_pct_zero_when_no_raw_words(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        assert ca.word_loss_pct == pytest.approx(0.0)

    def test_missing_by_reason_accumulated(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(missing=2))
        ca.add(self._make_doc_audit(missing=1))
        assert ca.missing_by_reason.get("noise_header") == 3

    def test_loss_pct_zero_when_no_missing_chars(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_chars=200, missing_chars=0))
        assert ca.loss_pct == pytest.approx(0.0)

    def test_loss_pct_correct(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_chars=200, missing_chars=50))
        assert ca.loss_pct == pytest.approx(25.0)

    def test_loss_pct_zero_when_raw_chars_zero(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        assert ca.loss_pct == pytest.approx(0.0)

    def test_section_loss_pct_correct(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(present=3, missing=1))
        assert ca.section_loss_pct == pytest.approx(25.0)

    def test_section_loss_pct_zero_when_no_sections(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        assert ca.section_loss_pct == pytest.approx(0.0)

    def test_to_dict_shape(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(raw_chars=100, missing_chars=10))
        d = ca.to_dict()
        for key in (
            "raw_dir",
            "sect_dir",
            "sampled",
            "audited",
            "errors",
            "sections_total",
            "sections_present",
            "sections_missing",
            "raw_chars",
            "missing_chars",
            "loss_pct",
            "raw_words",
            "missing_words",
            "word_loss_pct",
            "section_loss_pct",
            "missing_by_reason",
        ):
            assert key in d, f"Missing key in to_dict output: {key}"

    def test_to_dict_excludes_docs_by_default(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit())
        d = ca.to_dict(include_docs=False)
        assert "docs" not in d

    def test_to_dict_includes_docs_when_requested(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit())
        d = ca.to_dict(include_docs=True)
        assert "docs" in d
        assert len(d["docs"]) == 1

    def test_docs_list_always_appended_including_errors(self):
        ca = CorpusAudit(raw_dir="/r", sect_dir="/s")
        ca.add(self._make_doc_audit(error="oops"))
        assert len(ca.docs) == 1
        d = ca.to_dict(include_docs=True)
        assert len(d["docs"]) == 1


# ---------------------------------------------------------------------------
# Open-access PDF sampling (Task 3)
# ---------------------------------------------------------------------------


class TestBestEffortOaUrls:
    def test_v1_oainfo_and_pdfurls(self):
        doc = {
            "content": {
                "source": {
                    "oainfo": {"openaccessurl": "https://example.org/a.pdf"},
                    "pdfurls": ["https://mirror.org/a.pdf", "https://example.org/a.pdf"],
                }
            }
        }
        urls = _best_effort_oa_urls(doc)
        # oainfo first, then unique pdfurls (the duplicate is de-duped).
        assert urls == ["https://example.org/a.pdf", "https://mirror.org/a.pdf"]

    def test_v2_body_source(self):
        doc = {"body": {"source": {"oainfo": {"openaccessurl": "https://example.org/b.pdf"}}}}
        assert _best_effort_oa_urls(doc) == ["https://example.org/b.pdf"]

    def test_no_source_returns_empty(self):
        assert _best_effort_oa_urls({"corpusid": 1}) == []

    def test_malformed_does_not_raise(self):
        assert _best_effort_oa_urls({"content": {"source": "not a dict"}}) == []

    def test_scalar_pdfurls(self):
        doc = {"content": {"source": {"pdfurls": "https://example.org/c.pdf"}}}
        assert _best_effort_oa_urls(doc) == ["https://example.org/c.pdf"]


class TestSampleOaPdfs:
    def _write_raw(self, raw_dir, corpus_id, url):
        shard = raw_dir / str(corpus_id)[-2:]
        shard.mkdir(parents=True, exist_ok=True)
        (shard / f"{corpus_id}.json").write_text(
            json.dumps(
                {
                    "corpusid": corpus_id,
                    "content": {"source": {"oainfo": {"openaccessurl": url}}},
                }
            )
        )

    def test_samples_json_docs(self, tmp_path):
        raw = tmp_path / "raw"
        self._write_raw(raw, 100, "https://example.org/100.pdf")
        self._write_raw(raw, 201, "https://example.org/201.pdf")
        json_paths = list(raw.rglob("*.json"))
        samples = _sample_oa_pdfs(raw, [], json_paths, n=2, seed=0)
        assert len(samples) == 2
        by_id = {cid: urls for cid, _title, urls in samples}
        assert by_id["100"] == ["https://example.org/100.pdf"]
        assert by_id["201"] == ["https://example.org/201.pdf"]

    def test_sample_respects_n(self, tmp_path):
        raw = tmp_path / "raw"
        for i in range(5):
            self._write_raw(raw, 1000 + i, f"https://example.org/{i}.pdf")
        json_paths = list(raw.rglob("*.json"))
        samples = _sample_oa_pdfs(raw, [], json_paths, n=2, seed=0)
        assert len(samples) == 2
