#!/usr/bin/env python3
"""Scan sectionized documents and flag those matching Q2_NOT_BLOCK terms.

Usage
-----
    python scripts/filter_not_block.py DATA_DIR [--delete] [--jobs N]

DATA_DIR  Path to the sectionized dataset directory
          (e.g. data/titanv_all_utility_results_2026-05-18_11:14:14_sectionized)

Options
-------
--delete   Actually remove matched files (default: dry-run report only)
--jobs N   Parallel workers (default: -1 = all CPUs)
--out CSV  Write matched file list to CSV (default: not_block_matches.csv)
"""

import argparse
import csv
import json
import logging
import os
import re
from pathlib import Path

from joblib import Parallel, delayed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------------------------------------------------------------
# NOT-block terms – keep in sync with Q2_NOT_BLOCK in searches.py
# ---------------------------------------------------------------------------
NOT_TERMS = [
    # Biology / medicine
    "protein structure",
    "gene expression",
    "amino acid",
    "cell signaling",
    "neural circuit",
    "synaptic",
    "genome",
    "genomic",
    "transcriptome",
    "metabolome",
    "clinical trial",
    "randomized controlled trial",
    "patient outcome",
    "drug delivery",
    "pharmaceutical",
    "oncology",
    "tumor",
    "pathogen",
    "spectroscopy",
    # Chemical engineering
    "chemical reactor",
    "polymerization",
    "distillation column",
    "catalytic cracking",
    "reaction kinetics",
    "molar concentration",
    # Astrophysics
    "stellar",
    "galactic",
    "exoplanet",
    "black hole",
    "neutron star",
    "dark matter",
    "dark energy",
    "redshift",
    # Particle physics
    "hadron",
    "quark",
    "lepton",
    "boson",
    "particle accelerator",
    "collider",
    "plasma",
    # Semiconductor / nano fabrication
    "thin film deposition",
    "sputter",
    "epitaxial growth",
    "nanoparticle synthesis",
    "quantum dot",
    "CMOS",
]

# Pre-compile a single regex with all terms (case-insensitive)
_NOT_PATTERN = re.compile("|".join(re.escape(t) for t in NOT_TERMS), re.IGNORECASE)


def _flatten_text(doc: dict) -> str:
    """Concatenate all string values in the document."""
    parts = []
    for v in doc.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(item) for item in v)
    return " ".join(parts)


def check_file(filepath: str) -> dict | None:
    """Return match info if the document contains any NOT-block term."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None

    text = _flatten_text(doc)
    matches = set(m.lower() for m in _NOT_PATTERN.findall(text))
    if matches:
        return {
            "file": filepath,
            "title": doc.get("title", ""),
            "matched_terms": sorted(matches),
        }
    return None


def main():
    parser = argparse.ArgumentParser(description="Flag (and optionally delete) sectionized docs matching Q2 NOT block.")
    parser.add_argument("data_dir", type=str, help="Sectionized dataset directory")
    parser.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Remove matched files (default: dry-run)",
    )
    parser.add_argument("--jobs", type=int, default=-1, help="Parallel workers")
    parser.add_argument(
        "--out",
        type=str,
        default="not_block_matches.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        logging.error("Not a directory: %s", data_dir)
        return

    # Collect all JSON files (skip batch_checkpoint.json)
    json_files = sorted(str(p) for p in data_dir.rglob("*.json") if p.name != "batch_checkpoint.json")
    logging.info("Found %d JSON files to scan", len(json_files))

    results = Parallel(n_jobs=args.jobs, verbose=5)(delayed(check_file)(fp) for fp in json_files)
    hits = [r for r in results if r is not None]

    logging.info(
        "Matched %d / %d documents (%.1f%%)",
        len(hits),
        len(json_files),
        100.0 * len(hits) / max(len(json_files), 1),
    )

    # Term frequency summary
    from collections import Counter

    term_counts = Counter()
    for h in hits:
        for t in h["matched_terms"]:
            term_counts[t] += 1
    logging.info("Term frequency breakdown:")
    for term, count in term_counts.most_common():
        logging.info("  %-30s %d", term, count)

    # Write CSV
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "title", "matched_terms"])
        writer.writeheader()
        for h in hits:
            writer.writerow({**h, "matched_terms": "; ".join(h["matched_terms"])})
    logging.info("Wrote matches to %s", args.out)

    # Delete if requested
    if args.delete:
        for h in hits:
            os.remove(h["file"])
            logging.info("Deleted: %s", h["file"])
        logging.info("Deleted %d files", len(hits))
    else:
        logging.info("Dry run — no files deleted. Use --delete to remove.")


if __name__ == "__main__":
    main()
