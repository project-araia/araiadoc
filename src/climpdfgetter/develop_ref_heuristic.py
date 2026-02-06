import json
import random
import re
from pathlib import Path


def get_heuristic_score(text, debug=False):
    score = 0
    text_lower = text.lower()

    # --- Strong Positive Signals ---
    # DOI
    if re.search(r"10\.\d{4,}/", text):
        if debug:
            print("  +5 DOI")
        score += 5
    # URL / Retrieval
    if (
        "http://" in text
        or "https://" in text
        or "retrieved from" in text_lower
        or "accessed:" in text_lower
        or "available at:" in text_lower
    ):
        if debug:
            print("  +4 URL")
        score += 4
    # Citation Markers at start
    if re.match(r"^\[\d+\]", text.strip()) or re.match(r"^\d+\.", text.strip()):
        if debug:
            print("  +5 Citation Marker")
        score += 5
    # "et al."
    if "et al." in text_lower or "et al," in text_lower:
        if debug:
            print("  +4 et al.")
        score += 4
    # Common reference terms / Journal Abbreviations
    journal_terms = [
        "proc.",
        "journal of",
        "trans.",
        "intl.",
        "conf.",
        "univ.",
        "press",
        "adv.",
        "sci.",
        "lett.",
        "rev.",
        "res.",
        "phys.",
        "chem.",
        "biol.",
        "geophys.",
        "ann.",
        "bull.",
        "j.",
        "am.",
        "soc.",
        "ieee",
        "acm",
        "nature",
        "science",
        "cell",
    ]
    # Check for whole words to avoid "res" matching "results"
    # We'll use a regex for these
    found_terms = []
    for term in journal_terms:
        # escapes dots for regex
        term_esc = re.escape(term)
        if re.search(r"\b" + term_esc + r"\b", text_lower) or (term.endswith(".") and term in text_lower):
            found_terms.append(term)

    if found_terms:
        if debug:
            print(f"  +3 Journal Terms: {found_terms}")  # noqa
        score += 3

    # --- Medium Positive Signals ---
    # Year (1900-2029) - excluding years commonly found in prose like "In 1999, we..."
    # References usually have (Year) or Year after authors.
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match:
        # Check if it looks like a citation year (in parens or at end/start)
        if (
            re.search(r"\((19|20)\d{2}\)", text)
            or re.match(r"^(19|20)\d{2}\b", text.strip())
            or re.search(r"\b(19|20)\d{2}\.$", text.strip())
        ):
            if debug:
                print(f"  +3 Strong Year: {year_match.group(0)}")  # noqa
            score += 3
        else:
            if debug:
                print(f"  +1 Weak Year: {year_match.group(0)}")  # noqa
            score += 1

    # Pages / Vol
    if re.search(r"\b(vol\.|no\.|pp\.)", text_lower) or re.search(r"\d+\s*:\s*\d+[-–]\d+", text):
        if debug:
            print("  +2 Pages/Vol")  # noqa
        score += 2

    # Author-like patterns
    # "Smith, J." or "Smith, J.A."
    if re.match(r"^[A-Z][a-z]+,\s+[A-Z]\.", text.strip()):
        if debug:
            print("  +2 Author (Last, I.)")  # noqa
        score += 2
    # "J. Smith" or "J.A. Smith" - riskier, distinct from "U.S. Army"
    if re.match(r"^[A-Z]\.([A-Z]\.)?\s+[A-Z][a-z]+", text.strip()) and not re.match(r"^U\.S\.", text.strip()):
        if debug:
            print("  +1 Author (I. Last)")  # noqa
        score += 1

    # --- Content Signals (Negative) ---
    # Common Sentence Starters / Connectives
    prose_markers = [
        "however",
        "therefore",
        "although",
        "furthermore",
        "in conclusion",
        "we found",
        "results show",
        "discussion",
        "abstract",
        "introduction",
        "as shown in",
        "the figure",
        "the table",
        "section",
    ]
    if any(marker in text_lower for marker in prose_markers):
        if debug:
            print("  -5 Prose Marker")  # noqa
        score -= 5

    # First person
    if re.search(r"\bwe\b", text_lower) or re.search(r"\bour\b", text_lower):
        if debug:
            print("  -3 First Person")  # noqa
        score -= 3

    # Figure/Table captions
    if re.match(r"^(figure|fig\.|table|tab\.)\s*\d+", text_lower.strip()):
        if debug:
            print("  -10 Figure/Table Caption")  # noqa
        score -= 10

    # Single sentence ending in period without citation features
    if len(text.split()) > 10 and text.strip().endswith(".") and score < 2:
        # Long prose-like line that didn't trigger positive signals
        if debug:
            print("  -2 Plain Sentence")  # noqa
        score -= 2

    return score


def extract_references(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)

    if not data:
        return None, None

    # Get the last key's value
    last_key = list(data.keys())[-1]
    last_value = data[last_key]

    # Split by double newline (paragraphs)
    chunks = re.split(r"\n\n+", last_value)

    # Threshold for deciding "Is this a reference?"
    # Since visual inspection showed some refs scoring 0 or 2, and captions scoring 2
    # We really want to avoid captions.
    threshold = 1

    # Backward pass
    # We look for a *contiguous* block of references at the end.
    # The first text chunk (from the end) that fails the check terminates the reference section.

    split_index = len(chunks)

    for i in range(len(chunks) - 1, -1, -1):
        chunk = chunks[i].strip()
        if not chunk:
            continue

        score = get_heuristic_score(chunk)

        # If score is high enough, we assume it's a reference and update split_index.
        # If score is low, we assume we hit content and STOP.
        if score >= threshold:
            split_index = i
        else:
            break

    content_chunks = chunks[:split_index]
    ref_chunks = chunks[split_index:]

    return content_chunks, ref_chunks


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

    base_dir = Path("/Users/jnavarro/callm/climpdfgetter/data/600k_titanv_results_12-1_sectionized_no_rejected")

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
            print(f"  [REF START] score={get_heuristic_score(refs[0])}: {refs[0][:100]}...")
        if content:
            print(f"  [CONTENT END] score={get_heuristic_score(content[-1])}: ...{content[-1][-100:]}")
        print("\n")


if __name__ == "__main__":
    main()
