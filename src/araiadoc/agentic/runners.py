from __future__ import annotations

import concurrent.futures
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
