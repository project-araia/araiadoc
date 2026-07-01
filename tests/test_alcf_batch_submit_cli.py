"""CLI-level tests for `agentic-judge-dataset --mode alcf-batch-submit`.

Focus: how local request chunk files map onto remote ALCF input paths when
submitting, via --batch-request-dir (preferred) and the legacy --batch-input-file.
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

    def test_new_alias_names_work(self, tmp_path, monkeypatch):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 2)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                str(source),
                "--prompt",
                str(prompt),
                "--mode",
                "alcf-batch-submit",
                "--artifact-dir",
                str(output),
                "--model",
                "google/gemma-3-27b-it",
                "--api-key",
                "secret",
                "--batch-request-dir",
                "/eagle/me/requests/",
                "--batch-result-dir",
                "/eagle/me/results/",
            ],
        )

        assert result.exit_code == 0, result.output
        assert (output / "batch_requests.jsonl").exists()
        assert len(calls) == 1
        assert calls[0]["input_file"] == "/eagle/me/requests/batch_requests.jsonl"
        assert calls[0]["output_folder_path"] == "/eagle/me/results/"


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
        assert "--batch-request-dir" in result.output
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
        assert "--batch-request-dir" in result.output
        assert calls == []
        # Chunk files + manifest are still written for staging.
        assert (output / "batch_manifest.json").exists()
        assert len(sorted(output.glob("batch_requests_*.jsonl"))) >= 2


class TestSubmitAbsolutePathValidation:
    def _setup(self, tmp_path):
        source = tmp_path / "63"
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _make_corpus(source, 2)
        return source, output, prompt

    def test_relative_input_dir_rejected(self, tmp_path, monkeypatch):
        source, output, prompt = self._setup(tmp_path)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=9)
            + [
                "--api-key",
                "secret",
                "--batch-input-dir",
                "63_judged_input/",  # relative — the real bug
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code != 0
        assert "ABSOLUTE path" in result.output
        assert "--batch-request-dir" in result.output
        assert calls == []  # never submitted

    def test_relative_output_folder_rejected(self, tmp_path, monkeypatch):
        source, output, prompt = self._setup(tmp_path)
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
                "./batches_output",  # relative
            ],
        )

        assert result.exit_code != 0
        assert "ABSOLUTE path" in result.output
        assert "--batch-result-dir" in result.output
        assert calls == []

    def test_relative_input_file_rejected(self, tmp_path, monkeypatch):
        source, output, prompt = self._setup(tmp_path)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=9)
            + [
                "--api-key",
                "secret",
                "--batch-input-file",
                "input.jsonl",  # relative
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )

        assert result.exit_code != 0
        assert "ABSOLUTE path" in result.output
        assert calls == []

    def test_absolute_non_eagle_warns_but_submits(self, tmp_path, monkeypatch):
        source, output, prompt = self._setup(tmp_path)
        calls = _patch_submit(monkeypatch)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            _base_args(source, prompt, output, max_mb=9)
            + [
                "--api-key",
                "secret",
                "--batch-input-dir",
                "/home/me/requests/",  # absolute but not /eagle or /lus
                "--batch-output-folder",
                "/home/me/output/",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "warning" in result.output
        assert len(calls) == 1  # still submitted


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


def _prebuild_chunks(output: Path, prompt: Path, n: int, monkeypatch, *, model: str | None = None) -> int:
    """Run a normal stage-only submit to write chunk files, return chunk count."""
    source = output.parent / "63src"
    _make_corpus(source, n)
    _patch_submit(monkeypatch)  # not used for staging, but harmless
    args = _base_args(source, prompt, output, max_mb=0.003)
    if model is not None:
        args[args.index("--model") + 1] = model
    res = CliRunner().invoke(
        agentic_judge_dataset,
        args,  # stage only (no remote paths)
    )
    assert res.exit_code == 0, res.output
    return len(sorted(output.glob("batch_requests_*.jsonl")))


class TestResubmitExisting:
    def test_submits_existing_chunks_without_source_or_prompt(self, tmp_path, monkeypatch):
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        n_chunks = _prebuild_chunks(output, prompt, 12, monkeypatch)
        assert n_chunks >= 2

        calls = _patch_submit(monkeypatch, active=0)

        # Note: NO source positional, NO --prompt, NO --model/--max-batch-mb.
        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                "--mode",
                "alcf-batch-submit",
                "-o",
                str(output),
                "--api-key",
                "secret",
                "--resubmit-existing",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
                "--poll-interval",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "no regeneration" in result.output
        assert len(calls) == n_chunks
        submitted_inputs = {c["input_file"] for c in calls}
        assert submitted_inputs == {
            f"/eagle/me/requests/{p.name}" for p in sorted(output.glob("batch_requests_*.jsonl"))
        }

    def test_resubmit_uses_model_baked_into_existing_requests(self, tmp_path, monkeypatch):
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        original_model = "google/gemma-3-27b-it"
        n_chunks = _prebuild_chunks(output, prompt, 12, monkeypatch, model=original_model)
        assert n_chunks >= 2

        calls = _patch_submit(monkeypatch, active=0)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                "--mode",
                "alcf-batch-submit",
                "-o",
                str(output),
                "--api-key",
                "secret",
                "--resubmit-existing",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
                "--poll-interval",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert f"Using model from existing request JSONL: {original_model}" in result.output
        assert {c["model"] for c in calls} == {original_model}

    def test_does_not_overwrite_existing_chunk_files(self, tmp_path, monkeypatch):
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        _prebuild_chunks(output, prompt, 12, monkeypatch)

        chunk0 = sorted(output.glob("batch_requests_*.jsonl"))[0]
        before = chunk0.read_bytes()
        mtime_before = chunk0.stat().st_mtime

        _patch_submit(monkeypatch, active=0)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                "--mode",
                "alcf-batch-submit",
                "-o",
                str(output),
                "--api-key",
                "secret",
                "--resubmit-existing",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
                "--poll-interval",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert chunk0.read_bytes() == before
        assert chunk0.stat().st_mtime == mtime_before

    def test_errors_when_no_chunks_present(self, tmp_path, monkeypatch):
        output = tmp_path / "empty_out"
        _patch_submit(monkeypatch)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                "--mode",
                "alcf-batch-submit",
                "-o",
                str(output),
                "--api-key",
                "secret",
                "--resubmit-existing",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
            ],
        )
        assert result.exit_code != 0
        assert "found no batch_requests" in result.output

    def test_requires_output_dir(self, tmp_path, monkeypatch):
        _patch_submit(monkeypatch)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-submit", "--api-key", "secret", "--resubmit-existing"],
        )
        assert result.exit_code != 0
        assert "requires --artifact-dir/--output-dir" in result.output

    def test_rejected_for_non_submit_mode(self, tmp_path, monkeypatch):
        output = tmp_path / "out"
        _patch_submit(monkeypatch)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-collect", "-o", str(output), "--resubmit-existing"],
        )
        assert result.exit_code != 0
        assert "only valid with --mode alcf-batch-submit" in result.output

    def test_resume_skips_already_submitted_existing_chunk(self, tmp_path, monkeypatch):
        output = tmp_path / "63_judged"
        prompt = tmp_path / "rubric.md"
        prompt.write_text("Judge utility relevance.", encoding="utf-8")
        n_chunks = _prebuild_chunks(output, prompt, 12, monkeypatch)

        # Pre-mark chunk 000 as submitted.
        (output / "batch_submit_checkpoint.json").write_text(
            json.dumps(
                {"submitted": {"/eagle/me/requests/batch_requests_000.jsonl": {"batch_id": "old", "status": "pending"}}}
            ),
            encoding="utf-8",
        )
        calls = _patch_submit(monkeypatch, active=0)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            [
                "--mode",
                "alcf-batch-submit",
                "-o",
                str(output),
                "--api-key",
                "secret",
                "--resubmit-existing",
                "--batch-input-dir",
                "/eagle/me/requests/",
                "--batch-output-folder",
                "/eagle/me/output/",
                "--poll-interval",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert len(calls) == n_chunks - 1
        assert "/eagle/me/requests/batch_requests_000.jsonl" not in {c["input_file"] for c in calls}


class TestBatchStatusMode:
    def _write_submit_ckpt(self, output: Path, submitted: dict) -> None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "batch_submit_checkpoint.json").write_text(json.dumps({"submitted": submitted}), encoding="utf-8")

    def test_requires_output_dir(self):
        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-status", "--api-key", "secret"],
        )
        assert result.exit_code != 0
        assert "requires --artifact-dir" in result.output

    def test_errors_without_checkpoint(self, tmp_path):
        output = tmp_path / "out"
        output.mkdir()
        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-status", "-o", str(output), "--api-key", "secret"],
        )
        assert result.exit_code != 0
        assert "No submitted batches recorded" in result.output

    def test_snapshot_reports_states(self, tmp_path, monkeypatch):
        output = tmp_path / "out"
        self._write_submit_ckpt(
            output,
            {
                "/eagle/me/req/batch_requests_000.jsonl": {"batch_id": "b0", "status": "pending"},
                "/eagle/me/req/batch_requests_001.jsonl": {"batch_id": "b1", "status": "pending"},
            },
        )

        def fake_get(*, base_url, api_key, batch_id, timeout):
            if batch_id == "b0":
                return {"state": "completed", "batch_id": "b0"}
            return {"state": "ongoing", "batch_id": "b1"}

        import araiadoc.agentic.alcf_batch as alcf_batch_mod

        monkeypatch.setattr(alcf_batch_mod, "get_alcf_batch_result", fake_get)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-status", "-o", str(output), "--api-key", "secret"],
        )
        assert result.exit_code == 0, result.output
        assert "completed=1" in result.output
        assert "ongoing=1" in result.output
        assert "b0" in result.output and "b1" in result.output

    def test_reports_failed_message(self, tmp_path, monkeypatch):
        output = tmp_path / "out"
        self._write_submit_ckpt(
            output,
            {"/eagle/me/req/batch_requests_000.jsonl": {"batch_id": "b0", "status": "pending"}},
        )

        def fake_get(*, base_url, api_key, batch_id, timeout):
            return {
                "state": "failed",
                "batch_id": batch_id,
                "message": "Traceback ...\nFileNotFoundError: 63/x.jsonl",
            }

        import araiadoc.agentic.alcf_batch as alcf_batch_mod

        monkeypatch.setattr(alcf_batch_mod, "get_alcf_batch_result", fake_get)

        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-status", "-o", str(output), "--api-key", "secret"],
        )
        assert result.exit_code == 0, result.output
        assert "failed=1" in result.output
        assert "FileNotFoundError" in result.output
        assert "1 batch(es) FAILED" in result.output

    def test_requires_api_key(self, tmp_path, monkeypatch):
        output = tmp_path / "out"
        self._write_submit_ckpt(
            output,
            {"/eagle/me/req/batch_requests_000.jsonl": {"batch_id": "b0"}},
        )
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = CliRunner().invoke(
            agentic_judge_dataset,
            ["--mode", "alcf-batch-status", "-o", str(output)],
        )
        assert result.exit_code != 0
        assert "api-key" in result.output.lower()
