"""CLI-level tests for `agentic-judge-dataset --mode alcf-batch-submit`.

Focus: how local request chunk files map onto remote ALCF input paths when
submitting, via --batch-input-dir (preferred) and the legacy --batch-input-file.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import araiadoc.agentic.cli as cli
from araiadoc.agentic import agentic_judge_dataset


def _write_sectionized_doc(path: Path, **fields: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


def _make_corpus(source: Path, n: int) -> None:
    for i in range(n):
        _write_sectionized_doc(
            source / "00" / f"{i}.json",
            title=f"Doc {i}",
            abstract="Grid resilience under storms. " * 20,
            introduction="Utilities prepare for severe weather events. " * 20,
        )


def _patch_submit(monkeypatch) -> list[dict]:
    """Capture every submit_alcf_batch call; return the list of recorded kwargs."""
    calls: list[dict] = []

    def fake_submit(**kwargs):
        calls.append(kwargs)
        return {"id": f"batch-{len(calls)}", "status": "queued"}

    monkeypatch.setattr(cli, "submit_alcf_batch", fake_submit)
    return calls


def _base_args(source: Path, prompt: Path, output: Path, max_mb: float) -> list[str]:
    return [
        str(source),
        "--prompt",
        str(prompt),
        "--mode",
        "alcf-batch-submit",
        "-o",
        str(output),
        "--model",
        "google/gemma-3-27b-it",
        "--max-batch-mb",
        str(max_mb),
    ]


class TestSubmitSingleChunk:
    def test_single_chunk_with_input_file(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 2)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=9)
            + [
                "--api-key",
                "secret",
                "--batch-input-file",
                "/eagle/me/input.jsonl",
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code == 0, result.output
        assert (output / "batch_requests.jsonl").exists()
        assert len(calls) == 1
        assert calls[0]["input_file"] == "/eagle/me/input.jsonl"
        assert calls[0]["output_folder_path"] == "/eagle/me/output/"

    def test_single_chunk_with_input_dir_uses_local_filename(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 2)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=9)
            + [
                "--api-key",
                "secret",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["input_file"] == "/eagle/me/requests/batch_requests.jsonl"


class TestSubmitMultiChunk:
    def _tiny_mb_for_multichunk(self) -> float:
        # ~3KB per chunk → forces many chunks for the corpus below.
        return 0.003

    def test_input_dir_maps_each_chunk_to_its_local_filename(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=self._tiny_mb_for_multichunk())
            + [
                "--api-key",
                "secret",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code == 0, result.output
        # More than one chunk was produced.
        chunk_files = sorted(output.glob("batch_requests_*.jsonl"))
        assert len(chunk_files) >= 2
        # One submit per chunk.
        assert len(calls) == len(chunk_files)
        # Each remote input is <dir>/<local filename>, in order.
        expected = [f"/eagle/me/requests/{p.name}" for p in chunk_files]
        assert [c["input_file"] for c in calls] == expected
        # All share the same output folder.
        assert {c["output_folder_path"] for c in calls} == {"/eagle/me/output/"}

    def test_input_dir_trailing_slash_normalized(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)
        calls = _patch_submit(monkeypatch)

        CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=self._tiny_mb_for_multichunk())
            + [
                "--api-key",
                "secret",
                "--batch-input-dir",
                "/eagle/me/requests",  # no trailing slash
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        for c in calls:
            assert "//" not in c["input_file"].replace("://", "")
            assert c["input_file"].startswith("/eagle/me/requests/batch_requests_")

    def test_input_file_with_multichunk_errors(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=self._tiny_mb_for_multichunk())
            + [
                "--api-key",
                "secret",
                "--batch-input-file",
                "/eagle/me/input.jsonl",
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code != 0
        assert "--batch-input-dir" in result.output
        assert calls == []  # nothing submitted


class TestSubmitStageOnly:
    def test_no_remote_paths_stages_and_does_not_submit(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=0.003),
        )

        assert result.exit_code == 0, result.output
        assert "NOT submitted" in result.output
        assert "--batch-input-dir" in result.output
        assert calls == []
        # Chunk files + manifest are still written for staging.
        assert (output / "batch_manifest.json").exists()
        assert len(sorted(output.glob("batch_requests_*.jsonl"))) >= 2
