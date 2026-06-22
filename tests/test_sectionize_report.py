"""Tests for araiadoc.sectionize_report.

Covers:
  _pct
  DocReport  (record_kept, record_dropped, finalize, SectionDetail gating)
  CorpusReport  (add, to_summary_dict, merge_partial)
  CorpusReportPartial  (add, fields)

Run with:
    pixi run -e dev pytest tests/test_sectionize_report.py -v
"""

from __future__ import annotations

import pytest

from araiadoc.sectionize_report import (
    DROP_REASONS,
    OUTCOMES,
    CorpusReport,
    CorpusReportPartial,
    DocReport,
    SectionDetail,
    _pct,
    empty_drops,
    empty_outcomes,
)

# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------


class TestPct:
    def test_zero_denominator_returns_zero(self):
        assert _pct(10, 0) == 0.0

    def test_negative_denominator_returns_zero(self):
        assert _pct(10, -1) == 0.0

    def test_normal_ratio(self):
        assert _pct(1, 4) == pytest.approx(25.0)

    def test_full_ratio(self):
        assert _pct(5, 5) == pytest.approx(100.0)

    def test_zero_numerator(self):
        assert _pct(0, 100) == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(_pct(3, 7), float)


# ---------------------------------------------------------------------------
# DocReport — record_kept
# ---------------------------------------------------------------------------


class TestDocReportRecordKept:
    def setup_method(self):
        self.report = DocReport(corpus_id="test", outcome="unfiltered")

    def test_increments_kept_sections(self):
        self.report.record_kept(chars=100, paragraphs=2)
        assert self.report.kept_sections == 1

    def test_increments_kept_chars(self):
        self.report.record_kept(chars=200, paragraphs=3)
        assert self.report.kept_chars == 200

    def test_increments_kept_paragraphs(self):
        self.report.record_kept(chars=50, paragraphs=4)
        assert self.report.kept_paragraphs == 4

    def test_no_section_detail_when_header_none(self):
        self.report.record_kept(chars=50, paragraphs=1, header=None)
        assert self.report.sections == []

    def test_section_detail_appended_when_header_given(self):
        self.report.record_kept(chars=50, paragraphs=1, words=8, header="introduction")
        assert len(self.report.sections) == 1
        detail = self.report.sections[0]
        assert isinstance(detail, SectionDetail)
        assert detail.header == "introduction"
        assert detail.outcome == "kept"
        assert detail.chars == 50
        assert detail.paragraphs == 1
        assert detail.words == 8

    def test_words_accumulated(self):
        self.report.record_kept(chars=100, paragraphs=2, words=15)
        self.report.record_kept(chars=200, paragraphs=3, words=30)
        assert self.report.kept_words == 45

    def test_multiple_calls_accumulate(self):
        self.report.record_kept(chars=100, paragraphs=2)
        self.report.record_kept(chars=200, paragraphs=3)
        assert self.report.kept_sections == 2
        assert self.report.kept_chars == 300
        assert self.report.kept_paragraphs == 5

    def test_empty_parent_tracked_separately(self):
        self.report.record_kept(chars=0, paragraphs=0, empty_parent=True)
        assert self.report.kept_sections == 1
        assert self.report.empty_parent_sections == 1

    def test_non_empty_parent_default(self):
        self.report.record_kept(chars=10, paragraphs=1)
        assert self.report.empty_parent_sections == 0


# ---------------------------------------------------------------------------
# DocReport — record_dropped
# ---------------------------------------------------------------------------


class TestDocReportRecordDropped:
    def setup_method(self):
        self.report = DocReport(corpus_id="test", outcome="partially_filtered")

    def test_increments_dropped_sections(self):
        self.report.record_dropped("noise_header", chars=10, paragraphs=1)
        assert self.report.dropped_sections == 1

    def test_increments_dropped_chars_and_paragraphs(self):
        self.report.record_dropped("noise_header", chars=77, paragraphs=2)
        assert self.report.dropped_chars == 77
        assert self.report.dropped_paragraphs == 2

    def test_increments_dropped_words(self):
        self.report.record_dropped("noise_header", chars=50, paragraphs=1, words=10)
        assert self.report.dropped_words == 10

    def test_bucket_created_for_new_reason(self):
        self.report.record_dropped("non_substantive", chars=50, paragraphs=1, words=7)
        assert "non_substantive" in self.report.dropped_sections_by_reason
        bucket = self.report.dropped_sections_by_reason["non_substantive"]
        assert bucket["sections"] == 1
        assert bucket["chars"] == 50
        assert bucket["paragraphs"] == 1
        assert bucket["words"] == 7

    def test_bucket_accumulates_across_calls(self):
        self.report.record_dropped("noise_header", chars=10, paragraphs=1, words=3)
        self.report.record_dropped("noise_header", chars=20, paragraphs=2, words=5)
        bucket = self.report.dropped_sections_by_reason["noise_header"]
        assert bucket["sections"] == 2
        assert bucket["chars"] == 30
        assert bucket["paragraphs"] == 3
        assert bucket["words"] == 8

    def test_different_reasons_tracked_separately(self):
        self.report.record_dropped("noise_header", chars=10, paragraphs=1)
        self.report.record_dropped("non_substantive", chars=20, paragraphs=1)
        assert len(self.report.dropped_sections_by_reason) == 2

    def test_no_section_detail_when_header_none(self):
        self.report.record_dropped("noise_header", chars=10, paragraphs=1, header=None)
        assert self.report.sections == []

    def test_section_detail_appended_when_header_given(self):
        self.report.record_dropped("noise_header", chars=10, paragraphs=1, words=2, header="fig 1")
        assert len(self.report.sections) == 1
        detail = self.report.sections[0]
        assert detail.outcome == "noise_header"
        assert detail.header == "fig 1"
        assert detail.words == 2

    def test_unknown_reason_stored_without_error(self):
        # Unknown reasons are allowed; they just won't appear in render tables.
        self.report.record_dropped("brand_new_reason", chars=5, paragraphs=1)
        assert "brand_new_reason" in self.report.dropped_sections_by_reason


# ---------------------------------------------------------------------------
# DocReport — finalize
# ---------------------------------------------------------------------------


class TestDocReportFinalize:
    def test_total_sections_is_kept_plus_dropped(self):
        r = DocReport(corpus_id="x", outcome="partially_filtered")
        r.record_kept(chars=100, paragraphs=2)
        r.record_dropped("noise_header", chars=50, paragraphs=1)
        r.finalize()
        assert r.total_sections == 2
        assert r.total_paragraphs == 3

    def test_total_chars_computed_from_kept_plus_dropped(self):
        r = DocReport(corpus_id="x", outcome="partially_filtered")
        r.record_kept(chars=100, paragraphs=1)
        r.record_dropped("noise_header", chars=50, paragraphs=1)
        r.finalize()
        assert r.total_chars == 150

    def test_total_words_computed_from_kept_plus_dropped(self):
        r = DocReport(corpus_id="x", outcome="partially_filtered")
        r.record_kept(chars=100, paragraphs=1, words=20)
        r.record_dropped("noise_header", chars=50, paragraphs=1, words=8)
        r.finalize()
        assert r.total_words == 28

    def test_total_chars_not_overwritten_if_pre_set(self):
        r = DocReport(corpus_id="x", outcome="structural_failure")
        r.total_chars = 999  # pre-set externally
        r.record_kept(chars=100, paragraphs=1)
        r.finalize()
        # finalize must not overwrite an externally set total_chars
        assert r.total_chars == 999

    def test_all_zeros_finalize_to_zeros(self):
        r = DocReport(corpus_id="x", outcome="structural_failure")
        r.finalize()
        assert r.total_sections == 0
        assert r.total_paragraphs == 0
        assert r.total_words == 0
        assert r.total_chars == 0


# ---------------------------------------------------------------------------
# CorpusReport — add
# ---------------------------------------------------------------------------


class TestCorpusReportAdd:
    def _make_report(self, pipeline="test", source="src"):
        return CorpusReport(pipeline=pipeline, source=source)

    def _make_doc(self, outcome="unfiltered", kept_s=1, dropped_s=0, kept_c=100, dropped_c=0, kept_w=10, dropped_w=0):
        r = DocReport(corpus_id="d", outcome=outcome)
        r.kept_sections = kept_s
        r.dropped_sections = dropped_s
        r.total_sections = kept_s + dropped_s
        r.kept_chars = kept_c
        r.dropped_chars = dropped_c
        r.total_chars = kept_c + dropped_c
        r.kept_paragraphs = kept_s
        r.dropped_paragraphs = dropped_s
        r.total_paragraphs = kept_s + dropped_s
        r.kept_words = kept_w
        r.dropped_words = dropped_w
        r.total_words = kept_w + dropped_w
        if dropped_s:
            r.dropped_sections_by_reason["noise_header"] = {
                "sections": dropped_s,
                "paragraphs": dropped_s,
                "words": dropped_w,
                "chars": dropped_c,
            }
        return r

    def test_increments_documents_processed(self):
        cr = self._make_report()
        cr.add(self._make_doc())
        cr.add(self._make_doc())
        assert cr.documents_processed == 2

    def test_known_outcome_counted(self):
        cr = self._make_report()
        cr.add(self._make_doc(outcome="unfiltered"))
        assert cr.outcomes["unfiltered"] == 1

    def test_unknown_outcome_created(self):
        cr = self._make_report()
        doc = self._make_doc()
        doc.outcome = "mystery_outcome"
        cr.add(doc)
        assert cr.outcomes.get("mystery_outcome") == 1

    def test_aggregates_section_counts(self):
        cr = self._make_report()
        cr.add(self._make_doc(kept_s=3, dropped_s=1))
        cr.add(self._make_doc(kept_s=2, dropped_s=0))
        assert cr.kept_sections == 5
        assert cr.dropped_sections == 1
        assert cr.total_sections == 6

    def test_aggregates_char_counts(self):
        cr = self._make_report()
        cr.add(self._make_doc(kept_c=200, dropped_c=50))
        cr.add(self._make_doc(kept_c=100, dropped_c=0))
        assert cr.kept_chars == 300
        assert cr.dropped_chars == 50

    def test_aggregates_word_counts(self):
        cr = self._make_report()
        cr.add(self._make_doc(kept_w=20, dropped_w=5))
        cr.add(self._make_doc(kept_w=10, dropped_w=0))
        assert cr.kept_words == 30
        assert cr.dropped_words == 5
        assert cr.total_words == 35

    def test_drops_by_reason_accumulated(self):
        cr = self._make_report()
        cr.add(self._make_doc(dropped_s=2, dropped_c=80, dropped_w=15))
        cr.add(self._make_doc(dropped_s=1, dropped_c=30, dropped_w=6))
        bucket = cr.drops_by_reason.get("noise_header", {})
        assert bucket["sections"] == 3
        assert bucket["words"] == 21


# ---------------------------------------------------------------------------
# CorpusReport — to_summary_dict
# ---------------------------------------------------------------------------


class TestCorpusReportToSummaryDict:
    def _filled_corpus(self):
        cr = CorpusReport(pipeline="s2orc", source="/data")
        doc = DocReport(corpus_id="d", outcome="unfiltered")
        doc.record_kept(chars=500, paragraphs=3, words=80)
        doc.record_dropped("noise_header", chars=50, paragraphs=1, words=10)
        doc.finalize()
        cr.add(doc)
        return cr

    def test_top_level_keys(self):
        d = self._filled_corpus().to_summary_dict()
        assert "pipeline" in d
        assert "source" in d
        assert "totals" in d

    def test_pipeline_and_source(self):
        d = self._filled_corpus().to_summary_dict()
        assert d["pipeline"] == "s2orc"
        assert d["source"] == "/data"

    def test_documents_processed_correct(self):
        d = self._filled_corpus().to_summary_dict()
        assert d["totals"]["documents_processed"] == 1

    def test_outcomes_has_pct(self):
        d = self._filled_corpus().to_summary_dict()
        outcomes = d["totals"]["outcomes"]
        assert "unfiltered" in outcomes
        assert "count" in outcomes["unfiltered"]
        assert "pct" in outcomes["unfiltered"]

    def test_content_stripped_keys(self):
        d = self._filled_corpus().to_summary_dict()
        cs = d["totals"]["content_stripped"]
        for metric in ("chars", "words", "paragraphs", "sections"):
            assert metric in cs
            assert "kept" in cs[metric]
            assert "dropped" in cs[metric]
            assert "pct_dropped" in cs[metric]

    def test_content_stripped_words_values(self):
        d = self._filled_corpus().to_summary_dict()
        words = d["totals"]["content_stripped"]["words"]
        assert words["kept"] == 80
        assert words["dropped"] == 10
        assert words["total"] == 90
        assert words["pct_dropped"] == pytest.approx(100 * 10 / 90)

    def test_pct_dropped_correct(self):
        cr = CorpusReport(pipeline="p", source="s")
        doc = DocReport(corpus_id="d", outcome="partially_filtered")
        doc.kept_sections = 3
        doc.dropped_sections = 1
        doc.total_sections = 4
        doc.kept_chars = 300
        doc.dropped_chars = 100
        doc.total_chars = 400
        doc.kept_paragraphs = 3
        doc.dropped_paragraphs = 1
        doc.total_paragraphs = 4
        doc.kept_words = 60
        doc.dropped_words = 20
        doc.total_words = 80
        doc.dropped_sections_by_reason["noise_header"] = {"sections": 1, "paragraphs": 1, "words": 20, "chars": 100}
        cr.add(doc)
        d = cr.to_summary_dict()
        assert d["totals"]["content_stripped"]["sections"]["pct_dropped"] == pytest.approx(25.0)
        assert d["totals"]["content_stripped"]["words"]["pct_dropped"] == pytest.approx(25.0)

    def test_drops_by_reason_in_output(self):
        d = self._filled_corpus().to_summary_dict()
        drops = d["totals"]["drops_by_reason"]
        assert isinstance(drops, dict)


# ---------------------------------------------------------------------------
# CorpusReportPartial — add and merge_partial
# ---------------------------------------------------------------------------


class TestCorpusReportPartialAndMerge:
    def _make_doc(self, outcome="unfiltered", kept_s=2, dropped_s=1):
        r = DocReport(corpus_id="d", outcome=outcome)
        r.kept_sections = kept_s
        r.dropped_sections = dropped_s
        r.total_sections = kept_s + dropped_s
        r.kept_chars = 200
        r.dropped_chars = 50
        r.total_chars = 250
        r.kept_paragraphs = kept_s
        r.dropped_paragraphs = dropped_s
        r.total_paragraphs = kept_s + dropped_s
        r.kept_words = kept_s * 20
        r.dropped_words = dropped_s * 8
        r.total_words = r.kept_words + r.dropped_words
        if dropped_s:
            r.dropped_sections_by_reason["noise_header"] = {
                "sections": dropped_s,
                "paragraphs": dropped_s,
                "words": dropped_s * 8,
                "chars": 50,
            }
        return r

    def test_partial_add_increments_documents(self):
        p = CorpusReportPartial()
        p.add(self._make_doc())
        assert p.documents_processed == 1

    def test_partial_add_known_outcome(self):
        p = CorpusReportPartial()
        p.add(self._make_doc(outcome="unfiltered"))
        assert p.outcomes["unfiltered"] == 1

    def test_partial_drops_by_reason_accumulated(self):
        p = CorpusReportPartial()
        p.add(self._make_doc(dropped_s=2))
        p.add(self._make_doc(dropped_s=1))
        assert p.drops_by_reason["noise_header"]["sections"] == 3

    def test_partial_add_words_accumulated(self):
        p = CorpusReportPartial()
        p.add(self._make_doc())  # kept_s=2 → kept_words=40, dropped_s=1 → dropped_words=8
        assert p.kept_words == 40
        assert p.dropped_words == 8

    def test_merge_partial_into_corpus_report(self):
        p = CorpusReportPartial()
        p.add(self._make_doc())
        p.add(self._make_doc(outcome="partially_filtered"))

        cr = CorpusReport(pipeline="test", source="src")
        cr.merge_partial(p)

        assert cr.documents_processed == 2
        assert cr.kept_sections == 4
        assert cr.dropped_sections == 2
        assert cr.kept_words == 80
        assert cr.dropped_words == 16

    def test_merge_partial_accumulates_drops_by_reason(self):
        p = CorpusReportPartial()
        p.add(self._make_doc(dropped_s=2))
        cr = CorpusReport(pipeline="test", source="src")
        cr.merge_partial(p)
        assert cr.drops_by_reason["noise_header"]["sections"] == 2
        assert cr.drops_by_reason["noise_header"]["words"] == 16  # dropped_s=2 × 8

    def test_merge_partial_twice_is_additive(self):
        p1 = CorpusReportPartial()
        p1.add(self._make_doc())
        p2 = CorpusReportPartial()
        p2.add(self._make_doc())

        cr = CorpusReport(pipeline="p", source="s")
        cr.merge_partial(p1)
        cr.merge_partial(p2)
        assert cr.documents_processed == 2
        assert cr.kept_sections == 4


# ---------------------------------------------------------------------------
# CorpusReport — average section length (Task 2)
# ---------------------------------------------------------------------------


class TestCorpusReportAvgSectionLength:
    def _corpus_with_empty_parent(self):
        cr = CorpusReport(pipeline="s2orc", source="/data")
        doc = DocReport(corpus_id="d", outcome="partially_filtered")
        # Two real kept sections + one empty parent + one dropped section.
        doc.record_kept(chars=300, paragraphs=3, words=50)
        doc.record_kept(chars=100, paragraphs=1, words=15)
        doc.record_kept(chars=0, paragraphs=0, words=0, empty_parent=True)
        doc.record_dropped("noise_header", chars=40, paragraphs=2, words=8)
        doc.finalize()
        cr.add(doc)
        return cr

    def test_empty_parent_propagates_to_corpus(self):
        cr = self._corpus_with_empty_parent()
        assert cr.empty_parent_sections == 1

    def test_avg_excludes_empty_parent_before(self):
        cr = self._corpus_with_empty_parent()
        d = cr.to_summary_dict()
        avg = d["totals"]["avg_section_length"]
        # before sections = total(4) - empty_parent(1) = 3
        assert avg["before"]["sections"] == 3
        # before chars/section = total_chars(440) / 3
        assert avg["before"]["chars_per_section"] == pytest.approx(440 / 3)
        # before words/section = total_words(73) / 3
        assert avg["before"]["words_per_section"] == pytest.approx(73 / 3)

    def test_avg_excludes_empty_parent_after(self):
        cr = self._corpus_with_empty_parent()
        d = cr.to_summary_dict()
        avg = d["totals"]["avg_section_length"]
        # after sections = kept(3) - empty_parent(1) = 2
        assert avg["after"]["sections"] == 2
        # after chars/section = kept_chars(400) / 2 = 200
        assert avg["after"]["chars_per_section"] == pytest.approx(200.0)
        # after words/section = kept_words(65) / 2
        assert avg["after"]["words_per_section"] == pytest.approx(65 / 2)

    def test_summary_has_empty_parent_in_sections(self):
        cr = self._corpus_with_empty_parent()
        d = cr.to_summary_dict()
        assert d["totals"]["content_stripped"]["sections"]["empty_parent"] == 1

    def test_zero_denominator_safe(self):
        cr = CorpusReport(pipeline="p", source="s")
        d = cr.to_summary_dict()
        avg = d["totals"]["avg_section_length"]
        assert avg["before"]["chars_per_section"] == 0.0
        assert avg["after"]["chars_per_section"] == 0.0
        assert avg["before"]["words_per_section"] == 0.0
        assert avg["after"]["words_per_section"] == 0.0

    def test_empty_parent_merges_via_partial(self):
        p = CorpusReportPartial()
        doc = DocReport(corpus_id="d", outcome="partially_filtered")
        doc.record_kept(chars=0, paragraphs=0, words=0, empty_parent=True)
        doc.finalize()
        p.add(doc)
        assert p.empty_parent_sections == 1
        cr = CorpusReport(pipeline="p", source="s")
        cr.merge_partial(p)
        assert cr.empty_parent_sections == 1


# ---------------------------------------------------------------------------
# Vocabulary completeness
# ---------------------------------------------------------------------------


def test_drop_reasons_is_tuple_of_strings():
    assert isinstance(DROP_REASONS, tuple)
    assert all(isinstance(r, str) for r in DROP_REASONS)


def test_outcomes_is_tuple_of_strings():
    assert isinstance(OUTCOMES, tuple)
    assert all(isinstance(o, str) for o in OUTCOMES)


def test_empty_outcomes_has_all_outcome_keys():
    outcomes = empty_outcomes()
    for o in OUTCOMES:
        assert o in outcomes
        assert outcomes[o] == 0


def test_empty_drops_has_all_reason_keys():
    drops = empty_drops()
    for r in DROP_REASONS:
        assert r in drops
        bucket = drops[r]
        assert bucket == {"sections": 0, "paragraphs": 0, "words": 0, "chars": 0}
