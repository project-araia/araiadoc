#!/usr/bin/env python3
import argparse
import glob
import os
import sys
import time

import requests

# Configuration
SOLR_URL = "http://titanv.gss.anl.gov:8983/solr/s2orc_corpus/select"
TIMEOUT = 600


def query_solr(query_text, filter_queries=None):
    """Query SOLR using POST with all parameters in the body."""
    data = {"q": query_text, "rows": 0, "wt": "json", "df": "paragraph"}
    if filter_queries:
        data["fq"] = filter_queries

    try:
        # Sending all parameters in data= ensures they go in the POST body
        response = requests.post(SOLR_URL, data=data, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"\nQuery error: {e}", file=sys.stderr)
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text[:500]}", file=sys.stderr)
        return None


def extract_all_blocks(content):
    """Extract all parenthesized blocks from the content."""
    all_blocks = []
    current_block = []
    depth = 0
    for line in content.split("\n"):
        if line.strip() == "(":
            depth += 1
        if depth > 0:
            current_block.append(line)
        if line.strip() == ")":
            depth -= 1
            if depth == 0:
                all_blocks.append("\n".join(current_block))
                current_block = []
    return all_blocks


def main():
    parser = argparse.ArgumentParser(description="Query SOLR for group keyword files.")
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Do not remove duplicates between groups.",
    )
    args = parser.parse_args()

    dedupe = not args.no_dedupe

    search_patterns = ["../scratch/group_*.txt", "scratch/group_*.txt", "group_*.txt"]
    files = []
    for pattern in search_patterns:
        found = glob.glob(pattern)
        if found:
            files.extend(found)
            break
    files.sort()

    if not files:
        print("No files found matching 'group_*.txt'.")
        sys.exit(1)

    # Use first file to establish global anchor and exclusions
    with open(files[0], "r") as f:
        first_file_blocks = extract_all_blocks(f.read())

    anchor = first_file_blocks[1] if len(first_file_blocks) > 1 else None
    exclusions = first_file_blocks[2] if len(first_file_blocks) > 2 else None

    accumulated_group_terms = []
    total_count = 0

    cumulative_label = "Cumulative" if dedupe else "Sum (w/ dups)"
    print(f"{'Group Count':<15} {cumulative_label:<15} {'Time (s)':<10} {'Label'}")
    print("-" * 90)

    for f in files:
        label = os.path.splitext(os.path.basename(f))[0]
        # Shorten label for display if needed
        display_label = (label[:55] + "..") if len(label) > 55 else label

        try:
            with open(f, "r") as fh:
                content = fh.read()

            blocks = extract_all_blocks(content)
            if not blocks:
                print(f"{'SKIP':<15} {'-':<15} {'-':<10} {display_label} [No blocks found]")
                continue

            group_keywords = blocks[0]

            fq = []
            if anchor:
                fq.append(anchor)
            if exclusions:
                fq.append(f"NOT {exclusions}")

            # Add previous groups to exclusions to avoid duplicates (if deduping is active)
            if dedupe:
                for prev_g in accumulated_group_terms:
                    fq.append(f"NOT {prev_g}")

            print(f"-> Querying {label}...", end="\r", file=sys.stderr)
            sys.stderr.flush()

            start_time = time.time()
            result = query_solr(group_keywords, filter_queries=fq)
            elapsed = time.time() - start_time

            if result and "response" in result and "numFound" in result["response"]:
                count = result["response"]["numFound"]
                total_count += count
                print(f"{count:<15,} {total_count:<15,} {elapsed:<10.2f} {display_label}")
                sys.stdout.flush()
                # Record current group for future exclusions
                accumulated_group_terms.append(group_keywords)
            else:
                print(f"{'ERROR':<15} {'-':<15} {elapsed:<10.2f} {display_label} [FAILED]")

        except Exception as e:
            print(f"{'ERROR':<15} {'-':<15} {'-':<10} {display_label} [{e}]")

    print("-" * 90)
    summary_label = "TOTAL UNIQUE" if dedupe else "TOTAL SUM (w/ duplicates)"
    print(f"{summary_label:<25} {total_count:<15,}")


if __name__ == "__main__":
    main()
