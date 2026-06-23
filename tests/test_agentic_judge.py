from __future__ import annotations

import gzip
import json
from pathlib import Path

from click.testing import CliRunner

import araiadoc.agentic.runners as runners
from araiadoc.agentic import agentic_judge_dataset
from araiadoc.agentic.cli import parse_keep_decisions
from araiadoc.agentic.docs import doc_input_sha256, iter_sectionized_docs, job_key
from araiadoc.agentic.parsing import parse_judge_response
from araiadoc.agentic.prompting import build_judge_prompt, truncate_document_text


def _write_sectionized_doc(path: Path, **fields: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


class TestIterSectionizedDocs:
    def test_walks_nested_json_and_skips_reports(self, tmp_path):
        source = tmp_path / "sectionized"
        _write_sectionized_doc(
            source / "00" / "123.json",
            title=" Grid resilience ",
            abstract="\nStorm impacts\n",
            introduction=" Utilities prepare for storms. ",
            empty="   ",
        )
        (source / "sectionization_report.json").write_text("{}", encoding="utf-8")
        (source / "failures.json").write_text("[]", encoding="utf-8")

        docs = iter_sectionized_docs(source)

        assert len(docs) == 1
        assert docs[0]["doc_id"] == "123"
        assert docs[0]["source_path"] == "00/123.json"
        assert docs[0]["title"] == "Grid resilience"
        assert docs[0]["abstract"] == "Storm impacts"
        assert docs[0]["sections"] == [{"header": "introduction", "text": "Utilities prepare for storms."}]


class TestPromptConstruction:
    def test_prompt_preserves_section_boundaries(self):
        doc = {
            "title": "Grid report",
            "abstract": "About outage recovery.",
            "sections": [{"header": "methods", "text": "We model restoration."}],
        }

        prompt = build_judge_prompt("Judge utility relevance.", doc, 1000)

        assert "Return ONLY valid JSON" in prompt
        assert "Title: Grid report" in prompt
        assert "Abstract:\nAbout outage recovery." in prompt
        assert "## methods\nWe model restoration." in prompt

    def test_truncation_prioritizes_intro_before_other_sections(self):
        doc = {
            "title": "T",
            "abstract": "A",
            "sections": [
                {"header": "methods", "text": "M" * 300},
                {"header": "introduction", "text": "I" * 50},
            ],
        }

        text = truncate_document_text(doc, 120)

        assert "## introduction" in text
        assert "## methods" not in text
        assert len(text) <= 120


class TestParseJudgeResponse:
    def test_parses_plain_json(self):
        parsed = parse_judge_response('{"decision":"relevant","score":3,"rationale":"Matches."}')

        assert parsed["parsed"] is True
        assert parsed["decision"] == "relevant"
        assert parsed["score"] == 3

    def test_parses_json_inside_fence(self):
        parsed = parse_judge_response('```json\n{"decision":"maybe","score":1,"rationale":"Partial."}\n```')

        assert parsed["parsed"] is True
        assert parsed["decision"] == "maybe"

    def test_invalid_json_is_parse_failure(self):
        parsed = parse_judge_response("not json")

        assert parsed["parsed"] is False
        assert parsed["decision"] is None
        assert parsed["error"]

    def test_invalid_decision_is_parse_failure(self):
        parsed = parse_judge_response('{"decision":"yes","score":3,"rationale":"No."}')

        assert parsed["parsed"] is False
        assert parsed["decision"] is None
        assert "invalid decision" in parsed["error"]

    def test_fractional_score_is_parse_failure(self):
        parsed = parse_judge_response('{"decision":"maybe","score":1.5,"rationale":"Partial."}')

        assert parsed["parsed"] is False
        assert parsed["score"] is None
        assert "invalid score" in parsed["error"]


class TestResumeKey:
    def testjob_key_changes_when_prompt_model_or_input_changes(self):
        doc = {
            "doc_id": "1",
            "source_path": "00/1.json",
            "title": "A",
            "abstract": "B",
            "sections": [],
        }
        input_hash = doc_input_sha256(doc)
        key = job_key(
            source_path="00/1.json",
            doc_id="1",
            input_sha256=input_hash,
            prompt_sha256="p1",
            model="m1",
            base_url="u1",
        )

        assert key != job_key(
            source_path="00/1.json",
            doc_id="1",
            input_sha256=input_hash,
            prompt_sha256="p2",
            model="m1",
            base_url="u1",
        )
        assert key != job_key(
            source_path="00/1.json",
            doc_id="1",
            input_sha256=input_hash,
            prompt_sha256="p1",
            model="m2",
            base_url="u1",
        )

    def test_keep_decisions_validation(self):
        assert parse_keep_decisions("relevant, maybe") == {"relevant", "maybe"}


class TestAgenticJudgeCli:
    def test_dry_run_prints_prompts_without_api_key(self, tmp_path):
        source = tmp_path / "sectionized"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _write_sectionized_doc(
            source / "00" / "1.json",
            title="Grid",
            abstract="Storms",
            intro="Utility text",
        )

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [str(source), "--prompt", str(prompt), "--dry-run", "--limit", "1"],
        )

        assert result.exit_code == 0, result.output
        assert "Would judge documents: 1" in result.output
        assert "Title: Grid" in result.output
        assert "## intro" in result.output

    def test_rejects_output_inside_source(self, tmp_path):
        source = tmp_path / "sectionized"
        source.mkdir()
        prompt = tmp_path / "rubric.md"
        prompt.write_text("rubric", encoding="utf-8")

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--output-dir",
                str(source / "judged"),
                "--dry-run",
            ],
        )

        assert result.exit_code != 0
        assert "--output-dir must be outside SOURCE" in result.output

    def test_request_mode_writes_results_and_copies_relevant(self, tmp_path, monkeypatch):
        source = tmp_path / "sectionized"
        output = tmp_path / "judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _write_sectionized_doc(
            source / "00" / "1.json",
            title="Grid",
            abstract="Storms",
            intro="Utility text",
        )
        _write_sectionized_doc(source / "00" / "2.json", title="Other", abstract="None", intro="Other text")
        responses = iter(
            [
                '{"decision":"relevant","score":3,"rationale":"Matches."}',
                '{"decision":"irrelevant","score":0,"rationale":"No match."}',
            ]
        )

        def fake_completion(**kwargs):
            return next(responses)

        monkeypatch.setattr(runners, "chat_completion_with_retries", fake_completion)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--output-dir",
                str(output),
                "--api-key",
                "secret",
                "--concurrency",
                "1",
                "--copy-kept",
            ],
        )

        assert result.exit_code == 0, result.output
        with gzip.open(output / "judge_results.jsonl.gz", "rt", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        assert len(rows) == 2
        assert {row["decision"] for row in rows} == {"relevant", "irrelevant"}
        assert (output / "kept" / "00" / "1.json").exists()
        assert not (output / "kept" / "00" / "2.json").exists()
        summary = json.loads((output / "judge_summary.json").read_text(encoding="utf-8"))
        assert summary["api_key_provided"] is True
        assert "secret" not in (output / "judge_summary.json").read_text(encoding="utf-8")
        checkpoint = json.loads((output / "judge_checkpoint.json").read_text(encoding="utf-8"))
        assert len(checkpoint["completed_keys"]) == 2

    def test_resume_summary_counts_prior_result_rows(self, tmp_path, monkeypatch):
        source = tmp_path / "sectionized"
        output = tmp_path / "judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _write_sectionized_doc(
            source / "00" / "1.json",
            title="Grid",
            abstract="Storms",
            intro="Utility text",
        )
        _write_sectionized_doc(source / "00" / "2.json", title="Other", abstract="None", intro="Other text")

        responses = iter(
            [
                '{"decision":"relevant","score":3,"rationale":"Matches."}',
                '{"decision":"irrelevant","score":0,"rationale":"No match."}',
            ]
        )

        def fake_completion(**kwargs):
            return next(responses)

        monkeypatch.setattr(runners, "chat_completion_with_retries", fake_completion)
        first = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--output-dir",
                str(output),
                "--api-key",
                "secret",
                "--concurrency",
                "1",
                "--limit",
                "1",
            ],
        )
        assert first.exit_code == 0, first.output

        second = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--output-dir",
                str(output),
                "--api-key",
                "secret",
                "--concurrency",
                "1",
            ],
        )
        assert second.exit_code == 0, second.output

        summary = json.loads((output / "judge_summary.json").read_text(encoding="utf-8"))
        assert summary["total_discovered"] == 2
        assert summary["total_attempted"] == 2
        assert summary["total_succeeded"] == 2
        assert summary["decision_counts"] == {"irrelevant": 1, "relevant": 1}
        assert summary["current_run_attempted"] == 1
        assert summary["current_run_succeeded"] == 1
