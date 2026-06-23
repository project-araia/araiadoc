from __future__ import annotations

from typing import Any

from araiadoc.agentic.docs import doc_input_sha256, job_key
from araiadoc.agentic.prompting import build_judge_prompt


def prepare_doc_jobs(
    *,
    docs: list[dict[str, Any]],
    rubric: str,
    prompt_sha256: str,
    model: str,
    base_url: str,
    max_input_chars: int,
    completed_keys: set[str],
    resume: bool,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for doc in docs:
        input_sha256 = doc_input_sha256(doc)
        key = job_key(
            source_path=doc["source_path"],
            doc_id=doc["doc_id"],
            input_sha256=input_sha256,
            prompt_sha256=prompt_sha256,
            model=model,
            base_url=base_url,
        )
        if resume and key in completed_keys:
            continue
        jobs.append(
            {
                "key": key,
                "doc": doc,
                "input_sha256": input_sha256,
                "prompt": build_judge_prompt(rubric, doc, max_input_chars),
            }
        )
    return jobs
