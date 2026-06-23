from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

from araiadoc.agentic.util import atomic_write_json, now_iso


def make_result_row(
    *,
    doc: dict[str, Any],
    model: str,
    base_url: str,
    prompt_sha256: str,
    input_sha256: str,
    raw_response: str,
    parsed_response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "doc_id": doc["doc_id"],
        "source_path": doc["source_path"],
        "line_number": None,
        "title": doc.get("title", ""),
        "model": model,
        "base_url": base_url,
        "prompt_sha256": prompt_sha256,
        "input_sha256": input_sha256,
        "decision": parsed_response.get("decision"),
        "score": parsed_response.get("score"),
        "rationale": parsed_response.get("rationale", ""),
        "raw_response": raw_response,
        "parsed": parsed_response.get("parsed", False),
        "parse_error": parsed_response.get("error"),
        "created_at": now_iso(),
    }


def append_result(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def copy_kept_doc(doc: dict[str, Any], source: Path, output_dir: Path) -> None:
    rel_path = Path(doc["source_path"])
    dest = output_dir / "kept" / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / rel_path, dest)


def summarize_results_file(
    path: Path,
    *,
    model: str,
    base_url: str,
    prompt_sha256: str,
    expected_input_hashes: dict[str, str],
) -> dict[str, Any]:
    summary = {"succeeded": 0, "parse_failures": 0, "decision_counts": {}}
    if not path.exists():
        return summary

    seen_keys: set[tuple[str, str]] = set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            source_path = row.get("source_path")
            input_sha256 = row.get("input_sha256")
            if expected_input_hashes.get(source_path) != input_sha256:
                continue
            if row.get("model") != model or row.get("base_url") != base_url:
                continue
            if row.get("prompt_sha256") != prompt_sha256:
                continue
            row_key = (source_path, input_sha256)
            if row_key in seen_keys:
                continue
            seen_keys.add(row_key)
            summary["succeeded"] += 1
            if not row.get("parsed", False):
                summary["parse_failures"] += 1
            decision = row.get("decision")
            if decision:
                summary["decision_counts"][decision] = summary["decision_counts"].get(decision, 0) + 1
    return summary


def write_checkpoint(
    path: Path,
    *,
    completed_keys: set[str],
    model: str,
    base_url: str,
    prompt_sha256: str,
    updated_at: str | None = None,
) -> None:
    atomic_write_json(
        path,
        {
            "completed_keys": sorted(completed_keys),
            "model": model,
            "base_url": base_url,
            "prompt_sha256": prompt_sha256,
            "updated_at": updated_at or now_iso(),
        },
    )


def write_summary(
    path: Path,
    *,
    source: Path,
    output_dir: Path,
    model: str,
    base_url: str,
    prompt_path: Path,
    prompt_sha256: str,
    mode: str,
    keep_decisions: set[str],
    copy_kept: bool,
    total_discovered: int,
    total_attempted: int,
    total_succeeded: int,
    total_failed: int,
    decision_counts: dict[str, int],
    parse_failures: int,
    current_run_attempted: int,
    current_run_succeeded: int,
    current_run_failed: int,
    current_run_decision_counts: dict[str, int],
    current_run_parse_failures: int,
    retries: int,
    api_key_provided: bool,
) -> None:
    atomic_write_json(
        path,
        {
            "source": str(source),
            "output_dir": str(output_dir),
            "model": model,
            "base_url": base_url,
            "mode": mode,
            "prompt_path": str(prompt_path),
            "prompt_sha256": prompt_sha256,
            "total_discovered": total_discovered,
            "total_attempted": total_attempted,
            "total_succeeded": total_succeeded,
            "total_failed": total_failed,
            "decision_counts": dict(sorted(decision_counts.items())),
            "parse_failures": parse_failures,
            "current_run_attempted": current_run_attempted,
            "current_run_succeeded": current_run_succeeded,
            "current_run_failed": current_run_failed,
            "current_run_decision_counts": dict(sorted(current_run_decision_counts.items())),
            "current_run_parse_failures": current_run_parse_failures,
            "retries": retries,
            "copy_kept": copy_kept,
            "keep_decisions": sorted(keep_decisions),
            "api_key_provided": api_key_provided,
            "updated_at": now_iso(),
        },
    )
