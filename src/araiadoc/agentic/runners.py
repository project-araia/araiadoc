from __future__ import annotations

import concurrent.futures
import json
import random
import time
from pathlib import Path
from typing import Any

from rich.progress import Progress

from araiadoc.agentic.artifacts import (
    append_result,
    copy_kept_doc,
    make_result_row,
    write_checkpoint,
)
from araiadoc.agentic.constants import TRANSIENT_STATUS_CODES
from araiadoc.agentic.parsing import parse_judge_response
from araiadoc.agentic.util import now_iso


def chat_completion_with_retries(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    retries: int = 4,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            status_code = getattr(e, "status_code", None)
            retryable = status_code in TRANSIENT_STATUS_CODES or status_code is None
            if attempt >= retries or not retryable:
                raise
            time.sleep((2**attempt) + random.uniform(0, 0.5))
    raise RuntimeError("unreachable retry loop")


def run_requests_mode(
    *,
    jobs: list[dict[str, Any]],
    source: Path,
    output_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    prompt_sha256: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    concurrency: int,
    copy_kept: bool,
    keep_decisions: set[str],
    completed_keys: set[str],
    checkpoint_path: Path,
    result_path: Path,
    progress: Progress,
) -> dict[str, Any]:
    stats = {
        "succeeded": 0,
        "failed": 0,
        "parse_failures": 0,
        "decision_counts": {},
        "failures": [],
    }
    task = progress.add_task("[green]Judging documents", total=len(jobs))

    def call(job: dict[str, Any]) -> tuple[dict[str, Any], str]:
        raw = chat_completion_with_retries(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt=job["prompt"],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return job, raw

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_jobs = {executor.submit(call, job): job for job in jobs}
        for future in concurrent.futures.as_completed(future_jobs):
            job = future_jobs[future]
            try:
                job, raw_response = future.result()
                parsed_response = parse_judge_response(raw_response)
                row = make_result_row(
                    doc=job["doc"],
                    model=model,
                    base_url=base_url,
                    prompt_sha256=prompt_sha256,
                    input_sha256=job["input_sha256"],
                    raw_response=raw_response,
                    parsed_response=parsed_response,
                )
                append_result(result_path, row)
                completed_keys.add(job["key"])
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
                    copy_kept_doc(job["doc"], source, output_dir)
            except Exception as e:
                stats["failed"] += 1
                stats["failures"].append(
                    {
                        "doc_id": job["doc"]["doc_id"],
                        "source_path": job["doc"]["source_path"],
                        "error": str(e),
                        "created_at": now_iso(),
                    }
                )
                progress.log(f"* Error judging {job['doc']['source_path']}: {e}")
            progress.update(task, advance=1)
    return stats


def response_content_to_text(content: Any) -> str:
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, str):
        return content
    read = getattr(content, "read", None)
    if callable(read):
        data = read()
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    return str(content)


def run_provider_batch_mode(
    *,
    jobs: list[dict[str, Any]],
    source: Path,
    output_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    prompt_sha256: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    copy_kept: bool,
    keep_decisions: set[str],
    completed_keys: set[str],
    checkpoint_path: Path,
    result_path: Path,
    batch_poll_interval: float,
    batch_timeout: float,
    progress: Progress,
) -> dict[str, Any]:
    from openai import OpenAI

    stats = {
        "succeeded": 0,
        "failed": 0,
        "parse_failures": 0,
        "decision_counts": {},
        "failures": [],
    }
    if not jobs:
        return stats
    jobs_by_key = {job["key"]: job for job in jobs}
    request_path = output_dir / "batch_requests.jsonl"
    with request_path.open("w", encoding="utf-8") as f:
        for job in jobs:
            body = {
                "model": model,
                "messages": [{"role": "user", "content": job["prompt"]}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            f.write(
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

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    with request_path.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )

    wait_task = progress.add_task("[green]Waiting for provider batch", total=None)
    deadline = time.time() + batch_timeout
    while getattr(batch, "status", None) not in {
        "completed",
        "failed",
        "expired",
        "cancelled",
    }:
        if time.time() > deadline:
            raise TimeoutError(f"Provider batch {batch.id} did not finish before --batch-timeout")
        time.sleep(batch_poll_interval)
        batch = client.batches.retrieve(batch.id)
        progress.update(wait_task, description=f"[green]Provider batch: {batch.status}")
    progress.stop_task(wait_task)

    if getattr(batch, "status", None) != "completed":
        raise RuntimeError(f"Provider batch {batch.id} ended with status {batch.status}")

    output_file_id = getattr(batch, "output_file_id", None)
    output_text = ""
    if output_file_id:
        output_text = response_content_to_text(client.files.content(output_file_id))
        (output_dir / "batch_output.jsonl").write_text(output_text, encoding="utf-8")

    error_file_id = getattr(batch, "error_file_id", None)
    error_text = ""
    if error_file_id:
        error_text = response_content_to_text(client.files.content(error_file_id))
        (output_dir / "batch_errors.jsonl").write_text(error_text, encoding="utf-8")

    if not output_text and not error_text:
        raise RuntimeError(f"Provider batch {batch.id} completed without output or error files")

    seen_keys: set[str] = set()
    task = progress.add_task("[green]Parsing provider batch", total=None)
    for line in output_text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            key = item["custom_id"]
            seen_keys.add(key)
            job = jobs_by_key[key]
            response = item.get("response") or {}
            body = response.get("body") or {}
            raw_response = body["choices"][0]["message"].get("content") or ""
            parsed_response = parse_judge_response(raw_response)
            row = make_result_row(
                doc=job["doc"],
                model=model,
                base_url=base_url,
                prompt_sha256=prompt_sha256,
                input_sha256=job["input_sha256"],
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
                copy_kept_doc(job["doc"], source, output_dir)
        except Exception as e:
            stats["failed"] += 1
            stats["failures"].append({"error": str(e), "raw_batch_line": line, "created_at": now_iso()})
            progress.log(f"* Error parsing provider batch row: {e}")
        progress.update(task, advance=1)

    for line in error_text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            key = item.get("custom_id")
            if key:
                seen_keys.add(key)
            job = jobs_by_key.get(key)
            failure = {
                "doc_id": job["doc"]["doc_id"] if job else None,
                "source_path": job["doc"]["source_path"] if job else None,
                "error": json.dumps(item.get("error") or item, ensure_ascii=False),
                "raw_batch_line": line,
                "created_at": now_iso(),
            }
        except Exception as e:
            failure = {"error": str(e), "raw_batch_line": line, "created_at": now_iso()}
        stats["failed"] += 1
        stats["failures"].append(failure)
        progress.update(task, advance=1)

    for missing_key in sorted(set(jobs_by_key) - seen_keys):
        job = jobs_by_key[missing_key]
        stats["failed"] += 1
        stats["failures"].append(
            {
                "doc_id": job["doc"]["doc_id"],
                "source_path": job["doc"]["source_path"],
                "error": "provider batch produced no output or error row for custom_id",
                "created_at": now_iso(),
            }
        )
        progress.update(task, advance=1)
    return stats
