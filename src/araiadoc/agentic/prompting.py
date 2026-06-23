from __future__ import annotations

from typing import Any

from araiadoc.agentic.constants import PRIORITY_SECTION_MARKERS


def ordered_sections_for_prompt(sections: list[dict[str, str]]) -> list[dict[str, str]]:
    def score(section: dict[str, str]) -> tuple[int, int]:
        header = section["header"].lower()
        for idx, marker in enumerate(PRIORITY_SECTION_MARKERS):
            if marker in header:
                return (0, idx)
        return (1, 0)

    indexed = list(enumerate(sections))
    indexed.sort(key=lambda item: (score(item[1]), item[0]))
    return [item[1] for item in indexed]


def truncate_document_text(doc: dict[str, Any], max_input_chars: int) -> str:
    title = doc.get("title", "")
    abstract = doc.get("abstract", "")
    sections = doc.get("sections", [])

    prelude = f"Title: {title}\n\nAbstract:\n{abstract}\n\nSections:"
    chunks = [prelude]
    remaining = max_input_chars - len(prelude)
    if remaining <= 0:
        return prelude[:max_input_chars]

    for section in ordered_sections_for_prompt(sections):
        header = section["header"]
        text = section["text"]
        section_prefix = f"\n\n## {header}\n"
        full_chunk = section_prefix + text
        if len(full_chunk) <= remaining:
            chunks.append(full_chunk)
            remaining -= len(full_chunk)
            continue
        if remaining > len(section_prefix) + 20:
            chunks.append(section_prefix + text[: remaining - len(section_prefix)].rstrip())
        break

    return "".join(chunks)


def build_judge_prompt(rubric: str, doc: dict[str, Any], max_input_chars: int) -> str:
    document_text = truncate_document_text(doc, max_input_chars)
    return f"""You are judging document relevance.

Rubric:
{rubric.strip()}

Return ONLY valid JSON with this schema:
{{
  "decision": "relevant" | "irrelevant" | "maybe",
  "score": 0 | 1 | 2 | 3,
  "rationale": "short explanation, max 2 sentences"
}}

Document:
{document_text}
""".strip()
