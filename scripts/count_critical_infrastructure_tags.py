#!/usr/bin/env python3
"""Count critical-infrastructure tags in get-from-local-s2orc output."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

SKIP_NAMES = {
    "duckdb_checkpoint.json",
    "duckdb_q3_checkpoint.json",
    "failures.json",
    "filter_report.json",
    "sectionization_report.json",
}


def iter_documents(root: Path):
    for path in sorted(root.rglob("*.json")):
        if path.name in SKIP_NAMES or not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(document, dict):
            yield path, document


def count_tags(root: Path) -> dict:
    documents = 0
    tagged_documents = 0
    cross_tags: Counter[str] = Counter()
    sectors: Counter[str] = Counter()
    subsectors: Counter[str] = Counter()

    for _, document in iter_documents(root):
        documents += 1
        critical = document.get("_araiadoc_tags", {}).get("critical_infrastructure", {})
        if not isinstance(critical, dict) or not critical:
            continue

        tagged_documents += 1
        cross_tags.update({str(tag) for tag in critical.get("tags", [])})
        for sector_record in critical.get("sectors", []):
            if not isinstance(sector_record, dict):
                continue
            sector = sector_record.get("sector")
            if sector:
                sectors[str(sector)] += 1
            subsectors.update({str(value) for value in sector_record.get("subsectors", []) if value})

    return {
        "documents": documents,
        "tagged_documents": tagged_documents,
        "cross_cutting_tags": dict(sorted(cross_tags.items())),
        "sectors": dict(sorted(sectors.items())),
        "subsectors": dict(sorted(subsectors.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory written by get-from-local-s2orc")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    counts = count_tags(args.directory)
    if args.json:
        print(json.dumps(counts, indent=2))
        return

    print(f"Documents scanned: {counts['documents']}")
    print(f"Documents with critical-infrastructure tags: {counts['tagged_documents']}")
    for category in ("cross_cutting_tags", "sectors", "subsectors"):
        print(f"\n{category.replace('_', ' ').title()}:")
        for name, count in counts[category].items():
            print(f"{count:>8}  {name}")


if __name__ == "__main__":
    main()
