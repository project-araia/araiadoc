"""ALCF inference-service batch support.

The ALCF inference gateway batch API is *not* the OpenAI Files/Batches API.
There is no file upload step. Instead a single POST to ``{base_url}/batches``
references input/output **paths on ALCF shared storage** (e.g. Eagle /
``/eagle/argonne_tpc/...``) that the inference service itself reads and writes:

    POST {base_url}/batches
    {
      "model": "...",
      "input_file": "/eagle/.../input.jsonl",
      "output_folder_path": "/eagle/.../output/"
    }

Because the service reads/writes ALCF storage directly, the workflow is split
into two phases that bracket a manual (or Globus) file transfer:

1. ``submit``  - build the request JSONL locally, optionally stage it, and POST
                 the batch referencing the ALCF input/output paths.
2. ``collect`` - read the service-produced output JSONL back and fold it into the
                 same ``judge_results.jsonl.gz`` / summary / copy-kept artifacts
                 used by request mode.

This keeps judging reproducible across modes while accommodating the
filesystem-mediated ALCF batch contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from araiadoc.agentic.artifacts import (
    append_result,
    copy_kept_doc,
    make_result_row,
    write_checkpoint,
)
from araiadoc.agentic.parsing import parse_judge_response
from araiadoc.agentic.util import atomic_write_json, now_iso


def build_batch_request_line(job: dict[str, Any], *, model: str, temperature: float, max_tokens: int) -> str:
    """Build one ALCF/OpenAI-style chat-completions batch request line."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": job["prompt"]}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return (
        json.dumps(
            {
                "custom_id": job["key"],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def write_batch_request_file(
    jobs: list[dict[str, Any]],
    request_path: Path,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> int:
    """Write the batch request JSONL locally; return its byte size."""
    request_path.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with request_path.open("w", encoding="utf-8") as f:
        for job in jobs:
            line = build_batch_request_line(job, model=model, temperature=temperature, max_tokens=max_tokens)
            total_bytes += len(line.encode("utf-8"))
            f.write(line)
    return total_bytes


def write_batch_manifest(jobs: list[dict[str, Any]], manifest_path: Path) -> None:
    """Persist a custom_id -> doc identity map so collect can rebuild rows."""
    manifest = {
        job["key"]: {
            "doc_id": job["doc"]["doc_id"],
            "source_path": job["doc"]["source_path"],
            "title": job["doc"].get("title", ""),
            "input_sha256": job["input_sha256"],
        }
        for job in jobs
    }
    atomic_write_json(manifest_path, manifest)


def submit_alcf_batch(
    *,
    base_url: str,
    api_key: str,
    model: str,
    input_file: str,
    output_folder_path: str,
    timeout: float,
) -> dict[str, Any]:
    """POST a batch job to the ALCF inference gateway and return its response."""
    import httpx

    url = base_url.rstrip("/") + "/batches"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input_file": input_file,
        "output_folder_path": output_folder_path,
    }
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        raise click.UsageError(
            f"ALCF batch submission failed ({response.status_code}) at {url}:\n" f"{response.text[:2000]}"
        )
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"raw_response": response.text}


def _iter_batch_output_lines(output_path: Path):
    """Yield non-empty lines from a single file or all .jsonl files in a dir."""
    if output_path.is_dir():
        files = sorted(output_path.glob("*.jsonl"))
        if not files:
            files = sorted(output_path.glob("*.json"))
    else:
        files = [output_path]
    for file in files:
        with file.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield line


def collect_alcf_batch_output(
    *,
    output_path: Path,
    manifest: dict[str, dict[str, Any]],
    source: Path,
    output_dir: Path,
    model: str,
    base_url: str,
    prompt_sha256: str,
    copy_kept: bool,
    keep_decisions: set[str],
    completed_keys: set[str],
    checkpoint_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    """Fold ALCF batch output JSONL back into judge artifacts."""
    stats = {
        "succeeded": 0,
        "failed": 0,
        "parse_failures": 0,
        "decision_counts": {},
        "failures": [],
    }
    seen_keys: set[str] = set()

    for line in _iter_batch_output_lines(output_path):
        try:
            item = json.loads(line)
            key = item.get("custom_id")
            if key:
                seen_keys.add(key)
            entry = manifest.get(key)
            if entry is None:
                stats["failed"] += 1
                stats["failures"].append(
                    {
                        "error": f"custom_id not in manifest: {key!r}",
                        "raw_batch_line": line,
                        "created_at": now_iso(),
                    }
                )
                continue

            response = item.get("response") or {}
            body = response.get("body") or {}
            error = item.get("error")
            if error or not body:
                stats["failed"] += 1
                stats["failures"].append(
                    {
                        "doc_id": entry["doc_id"],
                        "source_path": entry["source_path"],
                        "error": json.dumps(error or item, ensure_ascii=False),
                        "raw_batch_line": line,
                        "created_at": now_iso(),
                    }
                )
                continue

            raw_response = body["choices"][0]["message"].get("content") or ""
            parsed_response = parse_judge_response(raw_response)
            doc = {
                "doc_id": entry["doc_id"],
                "source_path": entry["source_path"],
                "title": entry.get("title", ""),
            }
            row = make_result_row(
                doc=doc,
                model=model,
                base_url=base_url,
                prompt_sha256=prompt_sha256,
                input_sha256=entry["input_sha256"],
                raw_response=raw_response,
                parsed_response=parsed_response,
            )
            append_result(result_path, row)
            completed_keys.add(key)
            write_checkpoint(
                checkpoint_path,
                completed_keys=completed_keys,
                model=model,
                base_url=base_url,
                prompt_sha256=prompt_sha256,
            )
            stats["succeeded"] += 1
            if not row["parsed"]:
                stats["parse_failures"] += 1
            decision = row.get("decision")
            if decision:
                stats["decision_counts"][decision] = stats["decision_counts"].get(decision, 0) + 1
            if copy_kept and row["parsed"] and decision in keep_decisions:
                copy_kept_doc(doc, source, output_dir)
        except Exception as e:
            stats["failed"] += 1
            stats["failures"].append({"error": str(e), "raw_batch_line": line, "created_at": now_iso()})

    for missing_key in sorted(set(manifest) - seen_keys):
        entry = manifest[missing_key]
        stats["failed"] += 1
        stats["failures"].append(
            {
                "doc_id": entry["doc_id"],
                "source_path": entry["source_path"],
                "error": "no batch output row found for custom_id",
                "created_at": now_iso(),
            }
        )
    return stats
