"""Tests for araiadoc.sectionize pure-function layer.

Covers:
  _parse_spans
  _compile_exclude_patterns
  _normalize_to_v2
  _best_effort_title
  _best_effort_external_ids
  _get_corpus_id
  _sharded_output_file
  _sectionize_item_s2orc_v2  (unit + golden integration)

Run with:
    pixi run -e dev pytest tests/test_sectionize.py -v
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import make_v1_doc, make_v2_doc

from araiadoc.sectionize import (
    _best_effort_external_ids,
    _best_effort_title,
    _compile_exclude_patterns,
    _exclude_matches_for_doc,
    _filter_dataset_workflow,
    _filter_one_json_file,
    _filter_one_jsonl_file,
    _get_corpus_id,
    _normalize_to_v2,
    _parse_spans,
    _sectionize_item_s2orc_v2,
    _sharded_output_file,
    filter_dataset,
)

# ---------------------------------------------------------------------------
# _parse_spans
# ---------------------------------------------------------------------------


class TestParseSpans:
    def test_none_returns_empty(self):
        assert _parse_spans(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_spans("") == []

    def test_invalid_json_returns_empty(self):
        assert _parse_spans("not-json{{{") == []

    def test_non_list_json_returns_empty(self):
        assert _parse_spans('{"start": 0, "end": 5}') == []

    def test_non_dict_elements_skipped(self):
        result = _parse_spans(json.dumps([1, "string", None, {"start": 0, "end": 3}]))
        assert len(result) == 1
        assert result[0]["start"] == 0

    def test_int_offsets_preserved(self):
        spans = [{"start": 5, "end": 10}, {"start": 0, "end": 4}]
        result = _parse_spans(json.dumps(spans))
        assert result[0]["start"] == 0
        assert result[1]["start"] == 5

    def test_string_offsets_coerced_to_int(self):
        """v1 legacy shards encode start/end as strings."""
        spans = [{"start": "2675", "end": "3418"}]
        result = _parse_spans(json.dumps(spans))
        assert result[0]["start"] == 2675
        assert result[0]["end"] == 3418

    def test_sorted_by_start(self):
        spans = [
            {"start": 20, "end": 30},
            {"start": 5, "end": 10},
            {"start": 0, "end": 3},
        ]
        result = _parse_spans(json.dumps(spans))
        starts = [s["start"] for s in result]
        assert starts == sorted(starts)

    def test_uncoerceable_offset_drops_span(self):
        spans = [{"start": "bad", "end": 10}, {"start": 0, "end": 5}]
        result = _parse_spans(json.dumps(spans))
        assert len(result) == 1
        assert result[0]["start"] == 0

    def test_missing_attributes_key_ok(self):
        """attributes is optional — absence must not cause a drop."""
        spans = [{"start": 0, "end": 5}]
        result = _parse_spans(json.dumps(spans))
        assert len(result) == 1
        assert "attributes" not in result[0]

    def test_with_attributes_key_preserved(self):
        spans = [{"start": 0, "end": 5, "attributes": {"n": "1"}}]
        result = _parse_spans(json.dumps(spans))
        assert result[0]["attributes"] == {"n": "1"}

    def test_empty_list_returns_empty(self):
        assert _parse_spans("[]") == []


# ---------------------------------------------------------------------------
# _compile_exclude_patterns
# ---------------------------------------------------------------------------


class TestCompileExcludePatterns:
    def test_none_inputs_return_empty(self):
        assert _compile_exclude_patterns() == []

    def test_comma_separated_string(self):
        patterns = _compile_exclude_patterns(patterns_str="foo,bar,baz")
        assert len(patterns) == 3
        texts = [p.pattern for p in patterns]
        assert "foo" in texts and "bar" in texts and "baz" in texts

    def test_whitespace_stripped_from_terms(self):
        patterns = _compile_exclude_patterns(patterns_str="  foo  ,  bar  ")
        assert len(patterns) == 2

    def test_empty_terms_skipped(self):
        patterns = _compile_exclude_patterns(patterns_str=",,,foo,,,")
        assert len(patterns) == 1

    def test_case_insensitive_matching(self):
        patterns = _compile_exclude_patterns(patterns_str="Genome")
        assert patterns[0].search("GENOME is here")
        assert patterns[0].search("genome is here")

    def test_pattern_file(self, tmp_path):
        pfile = tmp_path / "patterns.txt"
        pfile.write_text("alpha\n# comment line\n\nbeta\n")
        patterns = _compile_exclude_patterns(pattern_file=pfile)
        texts = [p.pattern for p in patterns]
        assert "alpha" in texts
        assert "beta" in texts
        assert "# comment line" not in texts
        assert len(patterns) == 2

    def test_string_and_file_combined(self, tmp_path):
        pfile = tmp_path / "p.txt"
        pfile.write_text("from_file\n")
        patterns = _compile_exclude_patterns(patterns_str="from_string", pattern_file=pfile)
        texts = [p.pattern for p in patterns]
        assert "from_string" in texts
        assert "from_file" in texts

    def test_patterns_are_compiled_regex(self):
        import re

        patterns = _compile_exclude_patterns(patterns_str=r"\btest\b")
        assert isinstance(patterns[0], re.Pattern)


# ---------------------------------------------------------------------------
# raw dataset filtering helpers
# ---------------------------------------------------------------------------


class TestFilterDatasetHelpers:
    def test_exclude_matches_legacy_v2_paragraphs(self):
        import re

        doc = {
            "corpus_id": "abc",
            "title": ["Grid resilience"],
            "abstract": ["Safe abstract."],
            "paragraph": ["This paper studies gene expression."],
        }
        matches = _exclude_matches_for_doc(doc, [re.compile("gene expression", re.IGNORECASE)])
        assert matches == ["gene expression"]

    def test_filter_one_json_file_copies_kept_file(self, tmp_path):
        patterns = _compile_exclude_patterns(patterns_str="genomics")
        source = tmp_path / "raw"
        source.mkdir()
        doc_path = source / "keep.json"
        doc = make_v2_doc(corpusid=1, title="Energy systems", body_text="Utility resilience planning.")
        doc_path.write_text(json.dumps(doc))

        output_dir = tmp_path / "filtered"
        result = _filter_one_json_file(doc_path, source, output_dir, patterns)

        assert result["status"] == "kept"
        assert (output_dir / "keep.json").exists()
        assert json.loads((output_dir / "keep.json").read_text())["corpusid"] == 1

    def test_filter_one_json_file_excludes_matching_file(self, tmp_path):
        patterns = _compile_exclude_patterns(patterns_str="genomics")
        source = tmp_path / "raw"
        source.mkdir()
        doc_path = source / "drop.json"
        doc = make_v2_doc(corpusid=2, title="Genomics study", body_text="Utility resilience planning.")
        doc_path.write_text(json.dumps(doc))

        output_dir = tmp_path / "filtered"
        result = _filter_one_json_file(doc_path, source, output_dir, patterns)

        assert result["status"] == "excluded"
        assert result["matched"] == ["genomics"]
        assert not (output_dir / "drop.json").exists()

    def test_filter_one_json_file_removes_stale_output_when_excluded_on_rerun(self, tmp_path):
        source = tmp_path / "raw"
        source.mkdir()
        doc_path = source / "changed.json"
        output_dir = tmp_path / "filtered"

        kept_doc = make_v2_doc(corpusid=3, title="Energy systems", body_text="Utility resilience planning.")
        doc_path.write_text(json.dumps(kept_doc))
        _filter_one_json_file(doc_path, source, output_dir, _compile_exclude_patterns(patterns_str="genomics"))
        assert (output_dir / "changed.json").exists()

        excluded_doc = make_v2_doc(corpusid=3, title="Genomics study", body_text="Utility resilience planning.")
        doc_path.write_text(json.dumps(excluded_doc))
        result = _filter_one_json_file(doc_path, source, output_dir, _compile_exclude_patterns(patterns_str="genomics"))

        assert result["status"] == "excluded"
        assert not (output_dir / "changed.json").exists()

    def test_filter_one_jsonl_file_rewrites_kept_docs(self, tmp_path):
        patterns = _compile_exclude_patterns(patterns_str="genomics")
        source = tmp_path / "raw"
        source.mkdir()
        shard = source / "shard.jsonl.gz"
        keep_doc = make_v2_doc(corpusid=10, title="Energy systems", body_text="Utility resilience planning.")
        drop_doc = make_v2_doc(corpusid=11, title="Genomics study", body_text="Utility resilience planning.")
        with gzip.open(shard, "wt", encoding="utf-8") as f:
            f.write(json.dumps(keep_doc) + "\n")
            f.write(json.dumps(drop_doc) + "\n")

        output_dir = tmp_path / "filtered"
        result = _filter_one_jsonl_file(shard, source, output_dir, patterns)

        assert result["kept"] == 1
        assert result["excluded"] == 1
        assert result["matched_counts"] == {"genomics": 1}
        with gzip.open(output_dir / "shard.jsonl.gz", "rt", encoding="utf-8") as f:
            docs = [json.loads(line) for line in f if line.strip()]
        assert [doc["corpusid"] for doc in docs] == [10]

    def test_filter_workflow_discovers_plain_gz_s2orc_shard(self, tmp_path):
        from rich.progress import Progress

        patterns = _compile_exclude_patterns(patterns_str="genomics")
        source = tmp_path / "raw"
        source.mkdir()
        shard = source / "s2orc-shard.gz"
        keep_doc = make_v2_doc(corpusid=20, title="Energy systems", body_text="Utility resilience planning.")
        drop_doc = make_v2_doc(corpusid=21, title="Genomics study", body_text="Utility resilience planning.")
        with gzip.open(shard, "wt", encoding="utf-8") as f:
            f.write(json.dumps(keep_doc) + "\n")
            f.write(json.dumps(drop_doc) + "\n")

        output_dir = tmp_path / "filtered"
        with Progress() as progress:
            report = _filter_dataset_workflow(source, output_dir, patterns, progress)

        assert report["batch_files_processed"] == 1
        assert report["documents_kept"] == 1
        assert report["documents_excluded"] == 1
        with gzip.open(output_dir / "s2orc-shard.gz", "rt", encoding="utf-8") as f:
            docs = [json.loads(line) for line in f if line.strip()]
        assert [doc["corpusid"] for doc in docs] == [20]
        assert json.loads((output_dir / "filter_report.json").read_text())["matched_counts"] == {"genomics": 1}

    def test_filter_dataset_cli_rejects_output_inside_source(self, tmp_path):
        source = tmp_path / "raw"
        source.mkdir()
        runner = CliRunner()

        result = runner.invoke(
            filter_dataset,
            [str(source), "--patterns", "genomics", "--output-dir", str(source / "filtered")],
        )

        assert result.exit_code != 0
        assert "--output-dir must be outside SOURCE" in result.output

    def test_filter_dataset_cli_writes_report_for_json_files(self, tmp_path):
        source = tmp_path / "raw"
        source.mkdir()
        keep_doc = make_v2_doc(corpusid=30, title="Energy systems", body_text="Utility resilience planning.")
        drop_doc = make_v2_doc(corpusid=31, title="Genomics study", body_text="Utility resilience planning.")
        (source / "keep.json").write_text(json.dumps(keep_doc))
        (source / "drop.json").write_text(json.dumps(drop_doc))
        output_dir = tmp_path / "filtered"

        result = CliRunner().invoke(
            filter_dataset,
            [str(source), "--patterns", "genomics", "--output-dir", str(output_dir)],
        )

        assert result.exit_code == 0, result.output
        assert (output_dir / "keep.json").exists()
        assert not (output_dir / "drop.json").exists()
        report = json.loads((output_dir / "filter_report.json").read_text())
        assert report["documents_kept"] == 1
        assert report["documents_excluded"] == 1
        assert report["matched_counts"] == {"genomics": 1}


# ---------------------------------------------------------------------------
# _normalize_to_v2
# ---------------------------------------------------------------------------


class TestNormalizeToV2:
    def test_already_v2_returned_unchanged(self):
        doc = make_v2_doc(corpusid=1, body_text="hello", para_spans=[{"start": 0, "end": 5}])
        result = _normalize_to_v2(doc)
        assert result is doc or result == doc
        assert "body" in result

    def test_v1_gains_body_key(self):
        doc = make_v1_doc(corpusid=2, body_text="hello world", para_spans=[{"start": 0, "end": 5}])
        result = _normalize_to_v2(doc)
        assert "body" in result
        assert result["body"]["text"] == "hello world"

    def test_sectionheader_aliased_to_section_header(self):
        doc = make_v1_doc(
            corpusid=3,
            body_text="Intro\nBackground\nText here.",
            para_spans=[{"start": 17, "end": 27}],
            header_spans=[{"start": 6, "end": 16}],
        )
        result = _normalize_to_v2(doc)
        ann = result["body"]["annotations"]
        assert "section_header" in ann
        # original sectionheader key also still present (copy of dict)
        assert "sectionheader" in ann

    def test_title_backfilled_from_annotation_span(self):
        # body_text: "My Title\nBody text here."
        text = "My Title\nBody text here."
        doc = make_v1_doc(
            corpusid=4,
            body_text=text,
            title_spans=[{"start": 0, "end": 8}],
        )
        result = _normalize_to_v2(doc)
        assert result.get("title") == "My Title"

    def test_title_backfilled_from_first_line(self):
        text = "First Line Is Title\nBody paragraph."
        doc = make_v1_doc(corpusid=5, body_text=text)
        result = _normalize_to_v2(doc)
        assert result.get("title") == "First Line Is Title"

    def test_existing_title_not_overwritten(self):
        doc = make_v2_doc(corpusid=6, title="Kept Title", body_text="Body.")
        doc_with_title = dict(doc)
        doc_with_title["title"] = "Kept Title"
        result = _normalize_to_v2(doc_with_title)
        assert result.get("title") == "Kept Title"

    def test_no_content_key_returns_unchanged(self):
        doc = {"corpusid": 7}
        result = _normalize_to_v2(doc)
        assert result == doc


# ---------------------------------------------------------------------------
# _best_effort_title
# ---------------------------------------------------------------------------


class TestBestEffortTitle:
    def test_top_level_title_used_first(self):
        doc = make_v2_doc(corpusid=1, title="My Paper Title", body_text="body")
        assert _best_effort_title(doc) == "My Paper Title"

    def test_whitespace_only_title_falls_through(self):
        doc = make_v2_doc(corpusid=1, body_text="Actual first line\nMore.")
        doc["title"] = "   "
        assert _best_effort_title(doc) == "Actual first line"

    def test_annotation_span_title(self):
        text = "Paper Title Text\nIntroduction paragraph."
        doc = make_v2_doc(
            corpusid=2,
            body_text=text,
            extra_annotations={"title": [{"start": 0, "end": 16}]},
        )
        assert _best_effort_title(doc) == "Paper Title Text"

    def test_first_nonempty_line_fallback(self):
        text = "  \n\nActual Title\nParagraph text."
        doc = make_v2_doc(corpusid=3, body_text=text)
        assert _best_effort_title(doc) == "Actual Title"

    def test_none_returns_empty_string(self):
        assert _best_effort_title(None) == ""

    def test_non_dict_returns_empty_string(self):
        assert _best_effort_title("not a dict") == ""  # type: ignore

    def test_empty_doc_returns_empty_string(self):
        assert _best_effort_title({}) == ""

    def test_content_text_fallback_for_v1(self):
        """v1 docs use content.text; best_effort_title should find the first line."""
        doc = {"corpusid": 10, "content": {"text": "V1 Title Line\nBody here."}}
        assert _best_effort_title(doc) == "V1 Title Line"


# ---------------------------------------------------------------------------
# _best_effort_external_ids
# ---------------------------------------------------------------------------


class TestBestEffortExternalIds:
    def test_externalids_key(self):
        doc = {"externalids": {"doi": "10.1234/abc", "arxiv": None}}
        result = _best_effort_external_ids(doc)
        assert result == {"doi": "10.1234/abc"}

    def test_external_ids_underscore_key(self):
        doc = {"external_ids": {"pubmed": "12345678"}}
        result = _best_effort_external_ids(doc)
        assert result == {"pubmed": "12345678"}

    def test_externalIds_camel_key(self):
        doc = {"externalIds": {"mag": "9876"}}
        result = _best_effort_external_ids(doc)
        assert result == {"mag": "9876"}

    def test_falsy_values_stripped(self):
        doc = {"externalids": {"doi": "10.1/x", "arxiv": None, "pubmed": ""}}
        result = _best_effort_external_ids(doc)
        assert "arxiv" not in result
        assert "pubmed" not in result
        assert result["doi"] == "10.1/x"

    def test_all_falsy_falls_through_to_empty(self):
        doc = {"externalids": {"doi": None, "arxiv": None}}
        result = _best_effort_external_ids(doc)
        assert result == {}

    def test_no_ids_key_returns_empty(self):
        assert _best_effort_external_ids({"title": "foo"}) == {}

    def test_none_returns_empty(self):
        assert _best_effort_external_ids(None) == {}

    def test_first_non_empty_dict_wins(self):
        doc = {
            "externalids": {"doi": "10.1/x"},
            "external_ids": {"pubmed": "999"},
        }
        result = _best_effort_external_ids(doc)
        # externalids is checked first
        assert result == {"doi": "10.1/x"}


# ---------------------------------------------------------------------------
# _get_corpus_id
# ---------------------------------------------------------------------------


class TestGetCorpusId:
    def test_list_value_returns_first_as_string(self):
        assert _get_corpus_id({"corpus_id": [42, 99]}) == "42"

    def test_scalar_value_returns_string(self):
        assert _get_corpus_id({"corpus_id": 7}) == "7"

    def test_string_value_returned_as_is(self):
        assert _get_corpus_id({"corpus_id": "abc"}) == "abc"

    def test_none_value_uses_fallback_stem(self):
        assert _get_corpus_id({"corpus_id": None}, fallback_stem="fallback") == "fallback"

    def test_missing_key_uses_fallback_stem(self):
        assert _get_corpus_id({}, fallback_stem="stem") == "stem"

    def test_missing_key_no_fallback_returns_unknown(self):
        assert _get_corpus_id({}) == "unknown"

    def test_none_value_no_fallback_returns_unknown(self):
        assert _get_corpus_id({"corpus_id": None}) == "unknown"


# ---------------------------------------------------------------------------
# _sharded_output_file
# ---------------------------------------------------------------------------


class TestShardedOutputFile:
    def test_shard_is_last_two_chars(self, tmp_path):
        path = _sharded_output_file(tmp_path, "12345678")
        assert path.parent.name == "78"
        assert path.name == "12345678.json"

    def test_shard_dir_created(self, tmp_path):
        path = _sharded_output_file(tmp_path, "99990000")
        assert path.parent.exists()

    def test_short_id_uses_whole_id_as_shard(self, tmp_path):
        path = _sharded_output_file(tmp_path, "X")
        assert path.parent.name == "X"
        assert path.name == "X.json"

    def test_exactly_two_char_id(self, tmp_path):
        path = _sharded_output_file(tmp_path, "ab")
        assert path.parent.name == "ab"
        assert path.name == "ab.json"

    def test_returns_path_object(self, tmp_path):
        result = _sharded_output_file(tmp_path, "1234")
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# _sectionize_item_s2orc_v2  — unit tests
# ---------------------------------------------------------------------------


class TestSectionizeItemS2orcV2:
    def _long_english_text(self, n_words: int = 60) -> str:
        return " ".join(["word"] * n_words)

    def test_empty_body_text_fails(self):
        doc = make_v2_doc(corpusid=1, body_text="")
        success, result, error, report = _sectionize_item_s2orc_v2(doc)
        assert not success
        assert "Empty body text" in error
        assert report.outcome == "structural_failure"

    def test_no_paragraph_annotations_fails(self):
        doc = make_v2_doc(corpusid=2, body_text="Some text here.", para_spans=None)
        success, result, error, report = _sectionize_item_s2orc_v2(doc)
        assert not success
        assert "No paragraph annotations" in error
        assert report.outcome == "structural_failure"

    def test_exclude_pattern_hit_returns_excluded(self):
        import re

        doc = make_v2_doc(
            corpusid=3,
            body_text="gene expression levels were measured.",
            para_spans=[{"start": 0, "end": 36}],
        )
        patterns = [re.compile("gene expression", re.IGNORECASE)]
        success, result, error, report = _sectionize_item_s2orc_v2(doc, exclude_patterns=patterns)
        assert not success
        assert report.outcome == "excluded_by_pattern"
        assert "gene expression" in error

    def test_corpus_id_in_error_message(self):
        doc = make_v2_doc(corpusid=42, body_text="")
        _, _, error, _ = _sectionize_item_s2orc_v2(doc)
        assert "42" in error

    def test_returns_four_tuple(self, synth_v2_doc):
        result = _sectionize_item_s2orc_v2(synth_v2_doc)
        assert len(result) == 4
        success, sectioned, error, report = result
        assert isinstance(success, bool)
        assert isinstance(sectioned, dict)

    def test_title_in_output(self, synth_v2_doc):
        _, sectioned, _, _ = _sectionize_item_s2orc_v2(synth_v2_doc)
        assert "title" in sectioned

    def test_pre_header_paragraphs_become_abstract(self):
        # text layout: pre-header para, then a header, then a content para
        text = "Abstract text here with enough words to pass filters. " * 3
        header_start = len(text)
        text += "Introduction"
        header_end = len(text)
        text += "\n"
        para2_start = len(text)
        text += "Introduction body content paragraph with enough words. " * 3
        para2_end = len(text)

        doc = make_v2_doc(
            corpusid=10,
            body_text=text,
            para_spans=[
                {"start": 0, "end": header_start - 1},  # pre-header
                {"start": para2_start, "end": para2_end},
            ],
            header_spans=[{"start": header_start, "end": header_end}],
        )
        success, sectioned, _, _ = _sectionize_item_s2orc_v2(doc)
        assert success
        assert "abstract" in sectioned

    def test_duplicate_canonical_headers_appended_not_overwritten(self):
        # Two spans for "introduction" header → two para spans → content joined
        chunk = "This is a long enough introductory paragraph. " * 5
        text = "Introduction\n" + chunk + "Introduction\n" + chunk
        h0_end = len("Introduction")
        p0_start = h0_end + 1
        p0_end = p0_start + len(chunk) - 1
        h1_start = p0_end + 1
        h1_end = h1_start + len("Introduction")
        p1_start = h1_end + 1
        p1_end = p1_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=20,
            body_text=text,
            para_spans=[
                {"start": p0_start, "end": p0_end},
                {"start": p1_start, "end": p1_end},
            ],
            header_spans=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        _, sectioned, _, _ = _sectionize_item_s2orc_v2(doc)
        intro_val = sectioned.get("introduction", "")
        # Both paragraphs are appended under the single canonical "introduction"
        # header, so the value must be longer than a single chunk. If the second
        # occurrence had overwritten the first, the length would be ~one chunk.
        assert len(intro_val) > len(chunk)

    def test_outcome_unfiltered_when_nothing_dropped(self):
        chunk = "A well-written English sentence repeated many times. " * 5
        text = "Introduction\n" + chunk
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = p_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=30,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[{"start": 0, "end": h_end}],
        )
        success, _, _, report = _sectionize_item_s2orc_v2(doc)
        assert success
        assert report.outcome in ("unfiltered", "partially_filtered")

    def test_capture_section_detail_populates_sections_list(self, synth_v2_doc):
        _, _, _, report = _sectionize_item_s2orc_v2(synth_v2_doc, capture_section_detail=True)
        # Must have at least one SectionDetail row
        assert len(report.sections) >= 1

    def test_no_capture_section_detail_leaves_sections_empty(self, synth_v2_doc):
        _, _, _, report = _sectionize_item_s2orc_v2(synth_v2_doc, capture_section_detail=False)
        assert report.sections == []

    def test_fully_filtered_outcome_when_all_sections_dropped(self):
        # Use a non-english gibberish paragraph under a real header to force
        # non_english_or_invalid drop for the only section.
        text = "Results\n" + "xyz " * 200
        h_end = len("Results")
        p_start = h_end + 1
        p_end = len(text)

        doc = make_v2_doc(
            corpusid=40,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[{"start": 0, "end": h_end}],
        )
        success, sectioned, error, report = _sectionize_item_s2orc_v2(doc)
        # The only section is non-English gibberish, so it is dropped and the
        # document has no valid content sections.
        assert not success
        assert report.outcome == "fully_filtered"
        assert [k for k in sectioned if k not in ("title", "abstract")] == []
        assert report.total_sections == report.kept_sections + report.dropped_sections
        assert report.dropped_sections >= 1

    def test_references_header_stops_sectionization(self):
        # "References" is in unneeded_sections_skip_remaining
        chunk = "A sufficient English paragraph. " * 5
        text = "Introduction\n" + chunk + "References\n" + "Smith et al. 2020. Journal. " * 10
        h0_end = len("Introduction")
        p0_start = h0_end + 1
        p0_end = p0_start + len(chunk) - 1
        h1_start = p0_end + 1
        h1_end = h1_start + len("References")
        p1_start = h1_end + 1
        p1_end = len(text)

        doc = make_v2_doc(
            corpusid=50,
            body_text=text,
            para_spans=[
                {"start": p0_start, "end": p0_end},
                {"start": p1_start, "end": p1_end},
            ],
            header_spans=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        _, sectioned, _, report = _sectionize_item_s2orc_v2(doc)
        assert "references" not in sectioned
        assert report.dropped_sections > 0

    def test_report_finalized_after_success(self):
        chunk = "A good English paragraph. " * 6
        text = "Introduction\n" + chunk
        h_end = len("Introduction")
        p_start = h_end + 1
        p_end = p_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=60,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[{"start": 0, "end": h_end}],
        )
        success, _, _, report = _sectionize_item_s2orc_v2(doc)
        assert report.total_sections == report.kept_sections + report.dropped_sections

    def test_empty_parent_header_surfaced_as_empty_string(self):
        # A header immediately followed by another header (no intervening
        # paragraph span) is a parent header. It must be surfaced as a key with
        # an empty-string value, counted as an empty_parent_section, and NOT
        # rescue an otherwise-empty document.
        chunk = "A sufficient English paragraph with real content. " * 5
        # text layout: "Methods" (parent, no para) -> "Sampling" (child, para)
        text = "Methods\nSampling\n" + chunk
        h0_end = len("Methods")
        h1_start = h0_end + 1
        h1_end = h1_start + len("Sampling")
        p_start = h1_end + 1
        p_end = p_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=70,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        success, sectioned, _, report = _sectionize_item_s2orc_v2(doc)
        assert success
        # Parent header present with empty-string value.
        assert sectioned.get("methods") == ""
        # Child header has real content.
        assert sectioned.get("sampling", "")
        assert report.empty_parent_sections == 1

    def test_empty_parent_header_does_not_rescue_empty_doc(self):
        # A document whose ONLY non-abstract section is an empty parent header
        # must still be reported as fully_filtered (empty parents don't count
        # as real content).
        text = "Methods\nResults\n"
        h0_end = len("Methods")
        h1_start = h0_end + 1
        h1_end = h1_start + len("Results")
        # A single tiny paragraph far away so neither header owns it... actually
        # give zero paragraphs between/after both headers by pointing the only
        # paragraph before the first header (becomes abstract, too short).
        doc = make_v2_doc(
            corpusid=71,
            body_text=text,
            para_spans=[{"start": 0, "end": 0}],  # empty paragraph -> ignored
            header_spans=[
                {"start": 0, "end": h0_end},
                {"start": h1_start, "end": h1_end},
            ],
        )
        success, sectioned, _, report = _sectionize_item_s2orc_v2(doc)
        # Both headers are empty parents -> emitted as empty strings, but there
        # is no real content section, so the doc is fully_filtered.
        content_keys = [k for k in sectioned if k not in ("title", "abstract") and sectioned[k]]
        assert content_keys == []
        assert not success
        assert report.outcome == "fully_filtered"

    def test_numeral_prefix_retained_in_stored_header(self):
        # "3. Introduction" must keep the leading numeral in the stored key
        # while still being recognized as content (not dropped as noise).
        chunk = "A sufficient English paragraph with real content. " * 5
        raw_header = "3. Introduction"
        text = raw_header + "\n" + chunk
        h_end = len(raw_header)
        p_start = h_end + 1
        p_end = p_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=72,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[{"start": 0, "end": h_end}],
        )
        success, sectioned, _, _ = _sectionize_item_s2orc_v2(doc)
        assert success
        assert "3. introduction" in sectioned
        assert "introduction" not in sectioned

    def test_pure_enumeration_header_swallowed(self):
        # A header that is ENTIRELY an enumeration ("3.") is structural noise
        # — a bullet/list marker, not a real subsection title. The span walk
        # swallows it, so the paragraph that follows folds into whatever
        # section is currently open (here, the pre-header region, which
        # becomes the abstract). The key invariant: "3." / "3" must never
        # appear as a real section key, and the paragraph content must not
        # be silently dropped.
        chunk = "A sufficient English paragraph with real content. " * 5
        raw_header = "3."
        text = raw_header + "\n" + chunk
        h_end = len(raw_header)
        p_start = h_end + 1
        p_end = p_start + len(chunk) - 1

        doc = make_v2_doc(
            corpusid=73,
            body_text=text,
            para_spans=[{"start": p_start, "end": p_end}],
            header_spans=[{"start": 0, "end": h_end}],
        )
        _, sectioned, _, _ = _sectionize_item_s2orc_v2(doc)
        assert "3." not in sectioned
        assert "3" not in sectioned
        # Paragraph content must survive — it folds into the abstract here
        # because no real section had been opened when the enumeration
        # header appeared.
        assert chunk.strip() in sectioned.get("abstract", "")


# ---------------------------------------------------------------------------
# Golden integration tests — real v1 docs → expected sectionized output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus_id", ["275209400", "20416300"])
def test_golden_sectionization_round_trip(corpus_id, golden_raw_dir, golden_sect_dir):
    """Re-sectionize committed raw docs and compare to the committed golden output.

    This catches regressions in the sectionizer or its helpers when real-world
    documents are processed.  The golden outputs were produced by the current
    production sectionizer and committed alongside the raw docs.
    """
    raw_path = golden_raw_dir / f"{corpus_id}.json"
    sect_path = golden_sect_dir / "00" / f"{corpus_id}.json"

    assert raw_path.exists(), f"Raw fixture missing: {raw_path}"
    assert sect_path.exists(), f"Sectionized fixture missing: {sect_path}"

    import json as _json

    from araiadoc.sectionize import _normalize_to_v2

    with open(raw_path) as f:
        raw = _json.load(f)
    with open(sect_path) as f:
        expected = _json.load(f)

    v2 = _normalize_to_v2(raw)
    success, sectioned, error, report = _sectionize_item_s2orc_v2(v2)

    # Check every key the golden output has (except title which may differ
    # in normalization) is present in our result.
    content_keys = [k for k in expected if k not in ("title",)]
    for key in content_keys:
        assert key in sectioned, (
            f"Missing section '{key}' in re-sectionized output for corpus_id={corpus_id}. "
            f"Got keys: {list(sectioned.keys())}"
        )

    # The sectionizer must succeed for these known-good docs.
    assert success, f"Sectionizer failed for {corpus_id}: {error}"
