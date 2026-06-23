"""Compatibility exports for the agentic judge command.

New code should import from ``araiadoc.agentic`` or its submodules.
"""

from araiadoc.agentic import agentic_judge_dataset
from araiadoc.agentic.cli import parse_keep_decisions as _parse_keep_decisions
from araiadoc.agentic.docs import doc_input_sha256 as _doc_input_sha256
from araiadoc.agentic.docs import iter_sectionized_docs as _iter_sectionized_docs
from araiadoc.agentic.docs import job_key as _job_key
from araiadoc.agentic.parsing import parse_judge_response as _parse_judge_response
from araiadoc.agentic.prompting import build_judge_prompt as _build_judge_prompt
from araiadoc.agentic.prompting import truncate_document_text as _truncate_document_text
from araiadoc.agentic.runners import chat_completion_with_retries as _chat_completion_with_retries

__all__ = [
    "agentic_judge_dataset",
    "_build_judge_prompt",
    "_chat_completion_with_retries",
    "_doc_input_sha256",
    "_iter_sectionized_docs",
    "_job_key",
    "_parse_judge_response",
    "_parse_keep_decisions",
    "_truncate_document_text",
]
