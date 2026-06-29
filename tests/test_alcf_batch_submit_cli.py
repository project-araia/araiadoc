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


def _patch_submit(monkeypatch, *, active: int = 0, existing: list | None = None) -> list[dict]:
    """Capture every submit_alcf_batch call; return the list of recorded kwargs.

    Also stubs the gateway-query helpers so no real HTTP happens:
      - count_active_batches -> constant *active*
      - list_alcf_batches    -> *existing* (for resume reconciliation)
      - time.sleep           -> no-op
    """
    calls: list[dict] = []

    def fake_submit(**kwargs):
        calls.append(kwargs)
        return {"batch_id": f"batch-{len(calls)}", "status": "pending"}

    monkeypatch.setattr(cli, "submit_alcf_batch", fake_submit)
    monkeypatch.setattr(cli, "count_active_batches", lambda **kw: active)
    import araiadoc.agentic.alcf_batch as alcf_batch_mod

    monkeypatch.setattr(alcf_batch_mod, "list_alcf_batches", lambda **kw: list(existing or []))
    monkeypatch.setattr(cli.time, "sleep", lambda *a, **k: None)
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


def _multichunk_args(source, prompt, output) -> list[str]:
    return _base_args(source, prompt, output, max_mb=0.003) + [
        "--api-key",
        "secret",
        "--batch-input-dir",
        "/eagle/me/requests/",
        "--batch-output-folder",
        "/eagle/me/output/",
        "--poll-interval",
        "1",
    ]


class TestSubmitThrottling:
    def test_writes_submit_checkpoint_with_batch_ids(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)
        calls = _patch_submit(monkeypatch, active=0)

        result = CliRunner().invoke(agentic_judge_dataset, _multichunk_args(source, prompt, output))

        assert result.exit_code == 0, result.output
        ckpt = json.loads((output / "batch_submit_checkpoint.json").read_text(encoding="utf-8"))
        chunk_files = sorted(output.glob("batch_requests_*.jsonl"))
        # One checkpoint entry per submitted chunk, keyed by remote input path.
        assert len(ckpt["submitted"]) == len(chunk_files) == len(calls)
        for p in chunk_files:
            key = f"/eagle/me/requests/{p.name}"
            assert key in ckpt["submitted"]
            assert ckpt["submitted"][key]["batch_id"].startswith("batch-")

    def test_waits_for_slot_when_at_limit(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 6)

        # First poll reports 2 active (at limit), then frees up.
        active_seq = iter([2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        calls: list[dict] = []

        def fake_submit(**kwargs):
            calls.append(kwargs)
            return {"batch_id": f"b{len(calls)}", "status": "pending"}

        sleeps: list[float] = []
        monkeypatch.setattr(cli, "submit_alcf_batch", fake_submit)
        monkeypatch.setattr(cli, "count_active_batches", lambda **kw: next(active_seq))
        import araiadoc.agentic.alcf_batch as alcf_batch_mod

        monkeypatch.setattr(alcf_batch_mod, "list_alcf_batches", lambda **kw: [])
        monkeypatch.setattr(cli.time, "sleep", lambda s: sleeps.append(s))

        result = CliRunner().invoke(agentic_judge_dataset, _multichunk_args(source, prompt, output))

        assert result.exit_code == 0, result.output
        # It had to wait at least once before a slot freed.
        assert len(sleeps) >= 1
        assert "waiting" in result.output

    def test_quota_exceeded_backs_off_and_retries(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 4)

        from araiadoc.agentic.alcf_batch import BatchQuotaExceeded

        # First submit attempt raises quota; second succeeds.
        attempts = {"n": 0}
        calls: list[dict] = []

        def fake_submit(**kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise BatchQuotaExceeded("Quota of 2 active batch(es) per user exceeded.")
            calls.append(kwargs)
            return {"batch_id": f"b{len(calls)}", "status": "pending"}

        monkeypatch.setattr(cli, "submit_alcf_batch", fake_submit)
        monkeypatch.setattr(cli, "count_active_batches", lambda **kw: 0)
        import araiadoc.agentic.alcf_batch as alcf_batch_mod

        monkeypatch.setattr(alcf_batch_mod, "list_alcf_batches", lambda **kw: [])
        monkeypatch.setattr(cli.time, "sleep", lambda *a, **k: None)

        result = CliRunner().invoke(agentic_judge_dataset, _multichunk_args(source, prompt, output))

        assert result.exit_code == 0, result.output
        assert "quota full on submit" in result.output
        # Every chunk eventually recorded despite the first transient quota error.
        ckpt = json.loads((output / "batch_submit_checkpoint.json").read_text(encoding="utf-8"))
        assert len(ckpt["submitted"]) == len(sorted(output.glob("batch_requests_*.jsonl")))


class TestSubmitResume:
    def test_skips_chunks_in_existing_checkpoint(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)

        # Pre-write a checkpoint marking chunk 000 as already submitted.
        output.mkdir(parents=True, exist_ok=True)
        (output / "batch_submit_checkpoint.json").write_text(
            json.dumps(
                {"submitted": {"/eagle/me/requests/batch_requests_000.jsonl": {"batch_id": "old", "status": "pending"}}}
            ),
            encoding="utf-8",
        )
        calls = _patch_submit(monkeypatch, active=0)

        result = CliRunner().invoke(agentic_judge_dataset, _multichunk_args(source, prompt, output))

        assert result.exit_code == 0, result.output
        n_chunks = len(sorted(output.glob("batch_requests_*.jsonl")))
        # One chunk already done -> only the rest get submitted.
        assert len(calls) == n_chunks - 1
        submitted_inputs = {c["input_file"] for c in calls}
        assert "/eagle/me/requests/batch_requests_000.jsonl" not in submitted_inputs
        assert "Resuming" in result.output

    def test_adopts_batches_already_on_gateway(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 12)

        # No local checkpoint, but the gateway already has chunk 000 from a prior run.
        existing = [
            {
                "batch_id": "gw-000",
                "status": "running",
                "input_file": "/eagle/me/requests/batch_requests_000.jsonl",
            }
        ]
        calls = _patch_submit(monkeypatch, active=1, existing=existing)

        result = CliRunner().invoke(agentic_judge_dataset, _multichunk_args(source, prompt, output))

        assert result.exit_code == 0, result.output
        submitted_inputs = {c["input_file"] for c in calls}
        # Chunk 000 was adopted, not re-submitted.
        assert "/eagle/me/requests/batch_requests_000.jsonl" not in submitted_inputs
        ckpt = json.loads((output / "batch_submit_checkpoint.json").read_text(encoding="utf-8"))
        adopted = ckpt["submitted"]["/eagle/me/requests/batch_requests_000.jsonl"]
        assert adopted["batch_id"] == "gw-000"
        assert adopted.get("adopted_from_gateway") is True
