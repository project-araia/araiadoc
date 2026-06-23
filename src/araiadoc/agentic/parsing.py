from __future__ import annotations

import json
from typing import Any

from araiadoc.agentic.constants import VALID_DECISIONS


def extract_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]  # noqa: E203
    return stripped


def parse_judge_response(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_text(text))
    except json.JSONDecodeError as e:
        return {
            "parsed": False,
            "error": str(e),
            "decision": None,
            "score": None,
            "rationale": "",
        }
    if not isinstance(parsed, dict):
        return {
            "parsed": False,
            "error": "response JSON is not an object",
            "decision": None,
            "score": None,
            "rationale": "",
        }

    decision = str(parsed.get("decision", "")).strip().lower()
    score = parsed.get("score")
    rationale = parsed.get("rationale", "")
    if decision not in VALID_DECISIONS:
        return {
            "parsed": False,
            "error": f"invalid decision: {decision!r}",
            "decision": None,
            "score": None,
            "rationale": str(rationale),
        }
    if isinstance(score, bool) or not isinstance(score, int):
        return {
            "parsed": False,
            "error": f"invalid score: {score!r}",
            "decision": decision,
            "score": None,
            "rationale": str(rationale),
        }
    if score not in {0, 1, 2, 3}:
        return {
            "parsed": False,
            "error": f"invalid score: {score!r}",
            "decision": decision,
            "score": None,
            "rationale": str(rationale),
        }
    return {
        "parsed": True,
        "error": None,
        "decision": decision,
        "score": score,
        "rationale": str(rationale),
    }
