"""Tests for ALCF batch request chunking (write_batch_request_chunks, derive_chunk_input_path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from araiadoc.agentic.alcf_batch import (
    ACTIVE_BATCH_STATUSES,
    BatchQuotaExceeded,
    _batches_list_base,
    build_batch_request_line,
    count_active_batches,
    derive_chunk_input_path,
    discover_batch_request_chunks,
    list_alcf_batches,
    model_from_batch_request_chunks,
    write_batch_request_chunks,
)


def _make_job(doc_id: str, prompt: str = "hello") -> dict:
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


def _line_bytes(job: dict) -> int:
    return len(build_batch_request_line(job, model="m", temperature=0.0, max_tokens=8).encode("utf-8"))


# ---------------------------------------------------------------------------
# derive_chunk_input_path
# ---------------------------------------------------------------------------


class TestDeriveChunkInputPath:
    def test_suffixes_stem_with_zero_padded_index(self):
        result = derive_chunk_input_path("/eagle/argonne/input.jsonl", 0)
        assert result == "/eagle/argonne/input_000.jsonl"

    def test_index_pads_to_three_digits(self):
        assert derive_chunk_input_path("/eagle/foo/bar.jsonl", 7) == "/eagle/foo/bar_007.jsonl"
        assert derive_chunk_input_path("/eagle/foo/bar.jsonl", 42) == "/eagle/foo/bar_042.jsonl"
        assert derive_chunk_input_path("/eagle/foo/bar.jsonl", 123) == "/eagle/foo/bar_123.jsonl"

    def test_preserves_suffix_case(self):
        result = derive_chunk_input_path("/eagle/foo/input.JSONL", 1)
        assert result == "/eagle/foo/input_001.JSONL"

    def test_preserves_parent_directory(self):
        result = derive_chunk_input_path("/a/b/c/requests.jsonl", 5)
        assert Path(result).parent == Path("/a/b/c")

    def test_flat_filename_no_directory(self):
        result = derive_chunk_input_path("input.jsonl", 0)
        assert result == "input_000.jsonl"


# ---------------------------------------------------------------------------
# write_batch_request_chunks — single-chunk (≤ max_bytes)
# ---------------------------------------------------------------------------


class TestWriteBatchRequestChunksSingleChunk:
    def test_small_corpus_writes_legacy_filename(self, tmp_path):
        jobs = [_make_job("1"), _make_job("2")]
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=9_000_000,
        )
        assert len(chunks) == 1
        assert chunks[0]["path"].name == "batch_requests.jsonl"
        assert chunks[0]["index"] is None

    def test_single_chunk_contains_all_requests(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(5)]
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=9_000_000,
        )
        lines = chunks[0]["path"].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5
        custom_ids = {json.loads(li)["custom_id"] for li in lines}
        assert custom_ids == {str(i) for i in range(5)}

    def test_num_bytes_matches_file_size(self, tmp_path):
        jobs = [_make_job("a"), _make_job("b")]
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=9_000_000,
        )
        assert chunks[0]["num_bytes"] == chunks[0]["path"].stat().st_size

    def test_num_requests_matches_job_count(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(10)]
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=9_000_000,
        )
        assert chunks[0]["num_requests"] == 10


# ---------------------------------------------------------------------------
# write_batch_request_chunks — multi-chunk splitting
# ---------------------------------------------------------------------------


class TestWriteBatchRequestChunksMultiChunk:
    def _tight_max_bytes(self, jobs: list[dict], jobs_per_chunk: int) -> int:
        """Return a max_bytes that fits exactly jobs_per_chunk lines per chunk."""
        # Sum of the first jobs_per_chunk lines, minus one byte so the next job
        # forces a new chunk.
        total = sum(_line_bytes(jobs[i]) for i in range(jobs_per_chunk))
        # Subtracting 1 ensures the (jobs_per_chunk+1)-th job can't fit.
        return total

    def test_splits_into_numbered_files(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(4)]
        # Each line is roughly the same size; fit exactly 2 per chunk.
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 2,
        )
        assert len(chunks) == 2
        assert chunks[0]["path"].name == "batch_requests_000.jsonl"
        assert chunks[1]["path"].name == "batch_requests_001.jsonl"

    def test_index_labels_are_sequential_integers(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(6)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 2,
        )
        assert [c["index"] for c in chunks] == list(range(len(chunks)))

    def test_all_requests_preserved_across_chunks(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(7)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 3,
        )
        all_ids: set[str] = set()
        for chunk in chunks:
            for line in chunk["path"].read_text(encoding="utf-8").splitlines():
                all_ids.add(json.loads(line)["custom_id"])
        assert all_ids == {str(i) for i in range(7)}

    def test_total_request_count_equals_job_count(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(9)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 4,
        )
        assert sum(c["num_requests"] for c in chunks) == 9

    def test_no_chunk_exceeds_max_bytes(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(10)]
        one_line = _line_bytes(jobs[0])
        max_bytes = one_line * 3
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=max_bytes,
        )
        for chunk in chunks:
            assert chunk["num_bytes"] <= max_bytes

    def test_num_bytes_matches_file_sizes_in_multi_chunk(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(6)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 2,
        )
        for chunk in chunks:
            assert chunk["num_bytes"] == chunk["path"].stat().st_size

    def test_three_way_split(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(9)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 3,
        )
        assert len(chunks) == 3
        for chunk in chunks:
            assert chunk["num_requests"] == 3

    def test_uneven_split_puts_remainder_in_last_chunk(self, tmp_path):
        # 7 jobs, 3 per chunk → chunks of [3, 3, 1]
        jobs = [_make_job(str(i)) for i in range(7)]
        one_line = _line_bytes(jobs[0])
        chunks = write_batch_request_chunks(
            jobs,
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=one_line * 3,
        )
        assert [c["num_requests"] for c in chunks] == [3, 3, 1]


# ---------------------------------------------------------------------------
# write_batch_request_chunks — oversized single line
# ---------------------------------------------------------------------------


class TestWriteBatchRequestChunksOversizedLine:
    def test_oversized_line_placed_alone_in_own_chunk(self, tmp_path, capsys):
        job = _make_job("big", "x" * 500)
        one_line = _line_bytes(job)
        # Set max_bytes well below the single line size.
        max_bytes = one_line // 2

        chunks = write_batch_request_chunks(
            [job],
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=max_bytes,
        )
        # Single job → still one chunk (no second job to split from).
        assert len(chunks) == 1
        lines = chunks[0]["path"].read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["custom_id"] == "big"

    def test_oversized_line_emits_warning(self, tmp_path, capsys):
        job = _make_job("big", "x" * 500)
        one_line = _line_bytes(job)
        max_bytes = one_line // 2

        write_batch_request_chunks(
            [job],
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=max_bytes,
        )
        # click.echo writes to stdout; capsys captures it.
        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "big" in captured.out

    def test_oversized_line_in_multi_job_batch_goes_to_own_chunk(self, tmp_path):
        small = _make_job("small", "hi")
        big = _make_job("big", "x" * 500)
        big_bytes = _line_bytes(big)
        # max_bytes fits small but not big.
        max_bytes = big_bytes - 1

        chunks = write_batch_request_chunks(
            [small, big],
            tmp_path,
            model="m",
            temperature=0.0,
            max_tokens=8,
            max_bytes=max_bytes,
        )
        all_ids: list[str] = []
        for chunk in chunks:
            for line in chunk["path"].read_text(encoding="utf-8").splitlines():
                all_ids.append(json.loads(line)["custom_id"])
        assert set(all_ids) == {"small", "big"}

    def test_empty_job_list_returns_empty_chunks(self, tmp_path):
        chunks = write_batch_request_chunks([], tmp_path, model="m", temperature=0.0, max_tokens=8, max_bytes=9_000_000)
        assert chunks == []


# ---------------------------------------------------------------------------
# discover_batch_request_chunks (resubmit-existing)
# ---------------------------------------------------------------------------


class TestDiscoverBatchRequestChunks:
    def test_roundtrips_written_multichunk(self, tmp_path):
        jobs = [_make_job(str(i)) for i in range(6)]
        one_line = _line_bytes(jobs[0])
        written = write_batch_request_chunks(
            jobs, tmp_path, model="m", temperature=0.0, max_tokens=8, max_bytes=one_line * 2
        )
        assert len(written) >= 2

        found = discover_batch_request_chunks(tmp_path)
        assert [c["index"] for c in found] == [c["index"] for c in written]
        assert [c["path"].name for c in found] == [c["path"].name for c in written]
        assert [c["num_requests"] for c in found] == [c["num_requests"] for c in written]
        assert [c["num_bytes"] for c in found] == [c["num_bytes"] for c in written]

    def test_single_file_has_none_index(self, tmp_path):
        jobs = [_make_job("a"), _make_job("b")]
        write_batch_request_chunks(jobs, tmp_path, model="m", temperature=0.0, max_tokens=8, max_bytes=9_000_000)
        found = discover_batch_request_chunks(tmp_path)
        assert len(found) == 1
        assert found[0]["index"] is None
        assert found[0]["path"].name == "batch_requests.jsonl"
        assert found[0]["num_requests"] == 2

    def test_prefers_numbered_over_single(self, tmp_path):
        # Both a single and numbered files present -> numbered win.
        (tmp_path / "batch_requests.jsonl").write_text('{"a":1}\n', encoding="utf-8")
        (tmp_path / "batch_requests_000.jsonl").write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
        found = discover_batch_request_chunks(tmp_path)
        assert len(found) == 1
        assert found[0]["index"] == 0
        assert found[0]["num_requests"] == 2

    def test_empty_dir_returns_empty(self, tmp_path):
        assert discover_batch_request_chunks(tmp_path) == []

    def test_indexes_parsed_and_sorted(self, tmp_path):
        for name in ("batch_requests_002.jsonl", "batch_requests_000.jsonl", "batch_requests_001.jsonl"):
            (tmp_path / name).write_text('{"x":1}\n', encoding="utf-8")
        found = discover_batch_request_chunks(tmp_path)
        assert [c["index"] for c in found] == [0, 1, 2]


class TestModelFromBatchRequestChunks:
    def test_returns_unique_embedded_model(self, tmp_path):
        jobs = [_make_job("a"), _make_job("b")]
        write_batch_request_chunks(
            jobs, tmp_path, model="google/gemma-3-27b-it", temperature=0.0, max_tokens=8, max_bytes=9_000_000
        )
        chunks = discover_batch_request_chunks(tmp_path)
        assert model_from_batch_request_chunks(chunks) == "google/gemma-3-27b-it"

    def test_errors_on_mixed_models(self, tmp_path):
        p = tmp_path / "batch_requests_000.jsonl"
        p.write_text(
            build_batch_request_line(_make_job("a"), model="m1", temperature=0.0, max_tokens=8)
            + build_batch_request_line(_make_job("b"), model="m2", temperature=0.0, max_tokens=8),
            encoding="utf-8",
        )
        chunks = discover_batch_request_chunks(tmp_path)
        with pytest.raises(Exception, match="multiple models"):
            model_from_batch_request_chunks(chunks)

    def test_errors_on_missing_model(self, tmp_path):
        p = tmp_path / "batch_requests.jsonl"
        p.write_text('{"custom_id":"1","body":{}}\n', encoding="utf-8")
        chunks = discover_batch_request_chunks(tmp_path)
        with pytest.raises(Exception, match="Missing body.model"):
            model_from_batch_request_chunks(chunks)

    def test_errors_on_invalid_json(self, tmp_path):
        p = tmp_path / "batch_requests.jsonl"
        p.write_text("not json\n", encoding="utf-8")
        chunks = discover_batch_request_chunks(tmp_path)
        with pytest.raises(Exception, match="Invalid JSON"):
            model_from_batch_request_chunks(chunks)


# ---------------------------------------------------------------------------
# Batch list / active-count / quota helpers
# ---------------------------------------------------------------------------


class TestBatchesListBase:
    def test_strips_cluster_framework_segment(self):
        base = "https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1"
        assert _batches_list_base(base) == "https://inference-api.alcf.anl.gov/resource_server/v1"

    def test_trailing_slash_tolerated(self):
        base = "https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1/"
        assert _batches_list_base(base) == "https://inference-api.alcf.anl.gov/resource_server/v1"

    def test_no_resource_server_marker_falls_back(self):
        base = "https://example.com/custom/v1"
        assert _batches_list_base(base) == "https://example.com/custom/v1"


class TestActiveBatchStatuses:
    def test_pending_and_running_are_active(self):
        assert ACTIVE_BATCH_STATUSES == frozenset({"pending", "running"})


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            import json as _json

            raise _json.JSONDecodeError("no json", "", 0)
        return self._payload


class TestListAndCountActive:
    def _patch_httpx_get(self, monkeypatch, resp):
        import httpx

        monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)

    def test_count_active_counts_pending_and_running_only(self, monkeypatch):
        payload = [
            {"batch_id": "1", "status": "pending"},
            {"batch_id": "2", "status": "running"},
            {"batch_id": "3", "status": "completed"},
            {"batch_id": "4", "status": "failed"},
        ]
        self._patch_httpx_get(monkeypatch, _FakeResp(200, payload))
        n = count_active_batches(base_url="https://x/resource_server/sophia/vllm/v1", api_key="k", timeout=5)
        assert n == 2

    def test_list_unwraps_dict_shapes(self, monkeypatch):
        payload = {"batches": [{"batch_id": "1", "status": "pending"}]}
        self._patch_httpx_get(monkeypatch, _FakeResp(200, payload))
        out = list_alcf_batches(base_url="https://x/resource_server/sophia/vllm/v1", api_key="k", timeout=5)
        assert out == [{"batch_id": "1", "status": "pending"}]

    def test_list_non_json_returns_empty(self, monkeypatch):
        self._patch_httpx_get(monkeypatch, _FakeResp(200, None, text="oops"))
        out = list_alcf_batches(base_url="https://x/resource_server/sophia/vllm/v1", api_key="k", timeout=5)
        assert out == []

    def test_list_error_status_raises(self, monkeypatch):
        import click

        self._patch_httpx_get(monkeypatch, _FakeResp(500, None, text="server error"))
        try:
            list_alcf_batches(base_url="https://x/resource_server/sophia/vllm/v1", api_key="k", timeout=5)
        except click.UsageError as e:
            assert "list failed" in str(e)
        else:
            raise AssertionError("expected UsageError")


class TestSubmitQuotaDetection:
    def _patch_httpx_post(self, monkeypatch, resp):
        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: resp)

    def test_quota_message_raises_quota_exceeded(self, monkeypatch):
        from araiadoc.agentic.alcf_batch import submit_alcf_batch

        resp = _FakeResp(
            400,
            None,
            text='{"error": {"code": "quota_exceeded", "message": "Quota of 2 active batch(es) per user exceeded."}}',
        )
        self._patch_httpx_post(monkeypatch, resp)
        try:
            submit_alcf_batch(
                base_url="https://x/resource_server/sophia/vllm/v1",
                api_key="k",
                model="m",
                input_file="/eagle/in.jsonl",
                output_folder_path="/eagle/out/",
                timeout=5,
            )
        except BatchQuotaExceeded:
            pass
        else:
            raise AssertionError("expected BatchQuotaExceeded")

    def test_other_400_raises_usage_error(self, monkeypatch):
        import click

        from araiadoc.agentic.alcf_batch import submit_alcf_batch

        resp = _FakeResp(400, None, text='{"error": "bad input file path"}')
        self._patch_httpx_post(monkeypatch, resp)
        try:
            submit_alcf_batch(
                base_url="https://x/resource_server/sophia/vllm/v1",
                api_key="k",
                model="m",
                input_file="/eagle/in.jsonl",
                output_folder_path="/eagle/out/",
                timeout=5,
            )
        except click.UsageError:
            pass
        else:
            raise AssertionError("expected UsageError")
