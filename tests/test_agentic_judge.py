from __future__ import annotations

import gzip
import json
from pathlib import Path

from click.testing import CliRunner

import araiadoc.agentic.runners as runners
from araiadoc.agentic import agentic_judge_dataset
from araiadoc.agentic.alcf_batch import (
    build_batch_request_line,
    collect_alcf_batch_output,
    write_batch_manifest,
    write_batch_request_file,
)
from araiadoc.agentic.cli import parse_keep_decisions
from araiadoc.agentic.docs import doc_input_sha256, iter_sectionized_docs, job_key
from araiadoc.agentic.parsing import parse_judge_response
from araiadoc.agentic.prompting import build_judge_prompt, truncate_document_text


def _write_sectionized_doc(path: Path, **fields: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


def _make_job(doc_id: str, prompt: str) -> dict:
    return {
        "key": doc_id,
        "doc": {
            "doc_id": doc_id,
            "source_path": f"00/{doc_id}.json",
            "title": f"title-{doc_id}",
        },
        "input_sha256": "x",
        "prompt": prompt,
    }


def _batch_output_line(custom_id: str, content: str) -> str:
    return (
        json.dumps(
            {
                "custom_id": custom_id,
                "response": {"body": {"choices": [{"message": {"content": content}}]}},
            }
        )
        + "\n"
    )


class TestAlcfBatchRequestBuilding:
    def test_request_line_has_custom_id_and_body(self):
        line = build_batch_request_line(_make_job("1", "hello"), model="m", temperature=0.0, max_tokens=8)
        obj = json.loads(line)
        assert obj["custom_id"] == "1"
        assert obj["url"] == "/v1/chat/completions"
        assert obj["body"]["model"] == "m"
        assert obj["body"]["messages"][0]["role"] == "system"
        assert obj["body"]["messages"][-1] == {"role": "user", "content": "hello"}

    def test_write_request_file_and_manifest(self, tmp_path):
        jobs = [_make_job("1", "a"), _make_job("2", "b")]
        request_path = tmp_path / "batch_requests.jsonl"
        manifest_path = tmp_path / "batch_manifest.json"

        total_bytes = write_batch_request_file(jobs, request_path, model="m", temperature=0.0, max_tokens=8)
        write_batch_manifest(jobs, manifest_path)

        lines = request_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert total_bytes > 0

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["1"]["source_path"] == "00/1.json"
        assert manifest["1"]["input_sha256"] == "x"


class TestAlcfBatchCollect:
    def test_collect_folds_output_into_results(self, tmp_path):
        source = tmp_path / "sectionized"
        source.mkdir()
        output_dir = tmp_path / "judged"
        output_dir.mkdir()
        result_path = output_dir / "judge_results.jsonl.gz"
        checkpoint_path = output_dir / "judge_checkpoint.json"

        manifest = {
            "1": {
                "doc_id": "1",
                "source_path": "00/1.json",
                "title": "t1",
                "input_sha256": "x",
            },
            "2": {
                "doc_id": "2",
                "source_path": "00/2.json",
                "title": "t2",
                "input_sha256": "x",
            },
        }
        batch_output = tmp_path / "batch_output.jsonl"
        batch_output.write_text(
            _batch_output_line("1", '{"decision":"relevant","score":3,"rationale":"ok"}')
            + _batch_output_line("2", '{"decision":"irrelevant","score":0,"rationale":"no"}'),
            encoding="utf-8",
        )

        completed_keys: set[str] = set()
        stats = collect_alcf_batch_output(
            output_path=batch_output,
            manifest=manifest,
            source=source,
            output_dir=output_dir,
            model="m",
            base_url="u",
            prompt_sha256="p",
            copy_kept=False,
            keep_decisions={"relevant"},
            completed_keys=completed_keys,
            checkpoint_path=checkpoint_path,
            result_path=result_path,
        )

        assert stats["succeeded"] == 2
        assert stats["failed"] == 0
        assert stats["decision_counts"] == {"relevant": 1, "irrelevant": 1}
        with gzip.open(result_path, "rt", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        assert {r["decision"] for r in rows} == {"relevant", "irrelevant"}

    def test_collect_marks_missing_custom_ids_as_failed(self, tmp_path):
        source = tmp_path / "sectionized"
        source.mkdir()
        output_dir = tmp_path / "judged"
        output_dir.mkdir()
        manifest = {
            "1": {
                "doc_id": "1",
                "source_path": "00/1.json",
                "title": "t1",
                "input_sha256": "x",
            },
            "2": {
                "doc_id": "2",
                "source_path": "00/2.json",
                "title": "t2",
                "input_sha256": "x",
            },
        }
        batch_output = tmp_path / "batch_output.jsonl"
        batch_output.write_text(
            _batch_output_line("1", '{"decision":"relevant","score":3,"rationale":"ok"}'),
            encoding="utf-8",
        )

        stats = collect_alcf_batch_output(
            output_path=batch_output,
            manifest=manifest,
            source=source,
            output_dir=output_dir,
            model="m",
            base_url="u",
            prompt_sha256="p",
            copy_kept=False,
            keep_decisions={"relevant"},
            completed_keys=set(),
            checkpoint_path=output_dir / "judge_checkpoint.json",
            result_path=output_dir / "judge_results.jsonl.gz",
        )

        assert stats["succeeded"] == 1
        assert stats["failed"] == 1
        assert any(f.get("source_path") == "00/2.json" for f in stats["failures"])


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
        assert "--artifact-dir/--output-dir must be outside SOURCE" in result.output

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

    def test_collect_removes_stale_failures_file_after_success(self, tmp_path):
        source = tmp_path / "sectionized"
        output = tmp_path / "judged"
        prompt = tmp_path / "rubric.md"
        batch_output = tmp_path / "batch_output.jsonl"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _write_sectionized_doc(
            source / "00" / "1.json",
            title="Grid",
            abstract="Storms",
            intro="Utility text",
        )
        doc = iter_sectionized_docs(source)[0]
        output.mkdir()
        (output / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "job-1": {
                        "doc_id": doc["doc_id"],
                        "source_path": doc["source_path"],
                        "title": doc["title"],
                        "input_sha256": doc_input_sha256(doc),
                    }
                }
            ),
            encoding="utf-8",
        )
        (output / "failures.json").write_text(
            json.dumps([{"error": "stale missing output from a previous run"}]),
            encoding="utf-8",
        )
        batch_output.write_text(
            _batch_output_line("job-1", '{"decision":"relevant","score":3,"rationale":"Matches."}'),
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--mode",
                "alcf-batch-collect",
                "--output-dir",
                str(output),
                "--collect-batch-output",
                str(batch_output),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Documents failed: 0" in result.output
        assert not (output / "failures.json").exists()

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
