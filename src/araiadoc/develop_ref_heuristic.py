import random
from pathlib import Path

# Import from our text quality module
try:
    from .text_quality.reference_quality import extract_references, get_heuristic_score
except ImportError:
    from text_quality.reference_quality import extract_references, get_heuristic_score


def test_single_file(path_str):
    p = Path(path_str)
    print(f"--- DEBUG File: {p.name} ---")
    content, refs = extract_references(p)

    if refs:
        print(f"First Ref Chunk (Score: {get_heuristic_score(refs[0], debug=True)}):")  # noqa
        print(f"'{refs[0][:200]}'")  # noqa
    else:
        print("No references found.")

    if content:
        last_chunk = content[-1]
        print(f"\nLast Content Chunk (Score: {get_heuristic_score(last_chunk, debug=True)}):")  # noqa
        print(f"'{last_chunk[-200:] if len(last_chunk) > 200 else last_chunk}'")  # noqa


def main():
    # Specific file that failed previously
    problem_files = [
        "53637945_processed.json",  # Caption marked as ref
        "39872203_processed.json",  # Refs missed (Score 0)
        "92168237_processed.json",  # Refs missed
    ]

    base_dir = Path("/Users/jnavarro/callm/araiadoc/data/600k_titanv_results_12-1_sectionized_no_rejected")

    print("=== TESTING PROBLEM FILES ===")
    for fname in problem_files:
        path = base_dir / fname
        if path.exists():
            test_single_file(path)
            print("\n" + "=" * 30 + "\n")

    print("=== RANDOM SAMPLE ===")
    all_files = list(base_dir.glob("*_processed.json"))
    sample_files = random.sample(all_files, 50)

    for p in sample_files:
        print(f"--- File: {p.name} ---")
        content, refs = extract_references(p)
        print(f"  Detected {len(refs)} reference blocks.")
        if refs:
            print(f"  [REF START] score={get_heuristic_score(refs[0])}: {refs}...")
        if content:
            print(f"  [CONTENT END] score={get_heuristic_score(content[-1])}: ...{content[-1][-1000:]}")
        print("\n")


if __name__ == "__main__":
    main()


text = ""
