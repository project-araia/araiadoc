from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from araiadoc.agentic.constants import SKIP_JSON_FILENAMES
from araiadoc.agentic.util import normalize_ws, sha256_text


def iter_sectionized_docs(source: Path) -> list[dict[str, Any]]:
    """Return normalized sectionized docs from nested JSON files under source."""
    docs: list[dict[str, Any]] = []
    for path in sorted(source.rglob("*.json")):
        if not path.is_file() or path.name in SKIP_JSON_FILENAMES:
            continue
        rel_path = path.relative_to(source).as_posix()
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            continue

        title = normalize_ws(data.get("title"))
        abstract = normalize_ws(data.get("abstract"))
        sections: list[dict[str, str]] = []
        for key, value in data.items():
            if key in {"title", "abstract"}:
                continue
            text = normalize_ws(value)
            if text:
                sections.append({"header": str(key), "text": text})

        if title or abstract or sections:
            docs.append(
                {
                    "doc_id": path.stem,
                    "source_path": rel_path,
                    "source_file": path,
                    "title": title,
                    "abstract": abstract,
                    "sections": sections,
                }
            )
    return docs


def doc_input_sha256(doc: dict[str, Any]) -> str:
    stable = {
        "doc_id": doc["doc_id"],
        "source_path": doc["source_path"],
        "title": doc.get("title", ""),
        "abstract": doc.get("abstract", ""),
        "sections": doc.get("sections", []),
    }
    return sha256_text(json.dumps(stable, ensure_ascii=False, sort_keys=True))


def job_key(
    *,
    source_path: str,
    doc_id: str,
    input_sha256: str,
    prompt_sha256: str,
    model: str,
    base_url: str,
) -> str:
    raw = "\n".join([source_path, doc_id, input_sha256, prompt_sha256, model, base_url])
    return sha256_text(raw)
