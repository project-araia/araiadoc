#!/usr/bin/env python3
"""Inspect critical-infrastructure metadata in extracted s2orc JSON files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--sample", type=int, default=3, help="Number of matching metadata samples to print")
    args = parser.parse_args()

    documents = 0
    read_failures = 0
    araiadoc_tag_documents = 0
    critical_documents = 0
    tag_values: Counter[str] = Counter()
    matched_group_tags: Counter[str] = Counter()
    samples: list[tuple[Path, dict]] = []

    for path in sorted(args.directory.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            read_failures += 1
            continue
        if not isinstance(document, dict):
            continue
        documents += 1

        raw_tags = document.get("_araiadoc_tags")
        if not isinstance(raw_tags, dict):
            continue
        araiadoc_tag_documents += 1

        critical = raw_tags.get("critical_infrastructure")
        if not isinstance(critical, dict):
            continue
        critical_documents += 1

        tags = critical.get("tags", [])
        if isinstance(tags, list):
            tag_values.update(str(tag) for tag in tags if tag)

        groups = critical.get("matched_groups", [])
        if isinstance(groups, list):
            matched_group_tags.update(
                str(group["tag"]) for group in groups if isinstance(group, dict) and group.get("tag")
            )

        if len(samples) < args.sample:
            samples.append((path, critical))

    print(f"Directory: {args.directory}")
    print(f"JSON documents read: {documents}")
    print(f"JSON files skipped due to read/parse errors: {read_failures}")
    print(f"Documents with _araiadoc_tags object: {araiadoc_tag_documents}")
    print(f"Documents with critical_infrastructure object: {critical_documents}")
    print(f"\ncritical_infrastructure.tags: {dict(sorted(tag_values.items()))}")
    print(f"critical_infrastructure.matched_groups[].tag: {dict(sorted(matched_group_tags.items()))}")

    for path, critical in samples:
        print(f"\nSample: {path}")
        print(json.dumps(critical, indent=2, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
