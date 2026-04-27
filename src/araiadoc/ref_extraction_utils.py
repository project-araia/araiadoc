import re


def get_heuristic_score(text):
    score = 0
    text_lower = text.lower()

    # --- Strong Positive Signals (Override prose) ---
    # DOI
    if re.search(r"10\.\d{4,}/", text):
        score += 8
    # URL / Retrieval / Access
    if (
        "http://" in text
        or "https://" in text
        or "retrieved from" in text_lower
        or "accessed:" in text_lower
        or "accessed," in text_lower
        or "available at:" in text_lower
    ):
        score += 4
    # Citation Markers at start: "[1]" or "1."
    if re.match(r"^\[\d+\]", text.strip()) or re.match(r"^\d+\.", text.strip()):
        score += 6
    # "et al."
    if "et al." in text_lower or "et al," in text_lower:
        score += 4
    # Specific Pre-print/Journal indicators
    if "arxiv" in text_lower or "ssrn" in text_lower or "proc." in text_lower:
        score += 5

    # Common reference terms / Journal Abbreviations
    journal_terms = [
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
        "publishing",
        "publisher",
        "editors",
        "ed.",
        "eds.",
        "ltd",
        "inc",
        "literature cited",
        "ph.d. thesis",
        "doctoral thesis",
        "springer",
    ]

    # Check for whole words to avoid false matches
    for term in journal_terms:
        if term in text_lower:
            score += 3
            break  # One is enough

    # --- Medium Positive Signals ---
    # Year (1900-2029) - Context aware
    # Matches (1999), 1999., , 1999
    if re.search(r"[\(,]\s*(19|20)\d{2}[\)\.]", text) or re.search(r"\b(19|20)\d{2}[a-z]?\s*[\)\.]", text):
        score += 2
    elif re.search(r"\b(19|20)\d{2}\b", text):
        # Raw year, less strong
        score += 1

    # Pages / Vol
    if re.search(r"\b(vol\.|no\.|pp\.|p\.)\s*\d+", text_lower) or re.search(r"\d+\s*:\s*\d+[-–]\d+", text):
        score += 3

    # Author-like patterns
    # "Smith, J." or "Smith, J.A."
    if re.match(r"^[A-Z][a-z]+,\s+[A-Z]\.", text.strip()):
        score += 3
    # "J. Smith" or "J.A. Smith" - riskier
    if re.match(r"^[A-Z]\.([A-Z]\.)?\s+[A-Z][a-z]+", text.strip()) and not re.match(
        r"^(fig\.|table|vol\.|p\.|pp\.|u\.s\.)", text_lower.strip()
    ):
        score += 1

    # --- Content Signals (Negative) ---
    # Common Sentence Starters / Connectives
    # REMOVED: "data", "method", "analysis", "result", "simulation" as they appear in titles
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

    for marker in prose_markers:
        if marker in text_lower:
            # If we have strong signals (DOI, et al), ignore prose markers
            if score < 5:
                score -= 5
            break

    # First person - References rarely use "we" or "our" unless in title? Unlikely.
    if re.search(r"\bwe\b", text_lower) or re.search(r"\bour\b", text_lower):
        if score < 5:
            score -= 3

    # Figure/Table captions
    if re.match(r"^(figure|fig\.|table|tab\.)\s*\d+", text_lower.strip()):
        score -= 10

    # Single sentence ending in period without citation features
    # Heuristic: References are often not full sentences or are very structured.
    # Long prose-like line that didn't trigger positive signals is suspicious.
    if len(text.split()) > 15 and text.strip().endswith(".") and score < 2:
        score -= 2

    #  Relatively large percentage of single-character tokens resembles lists of authors
    percentage_single_char = len([i for i in text.split(" ") if len(i) == 1]) / len(text.split(" "))
    percentage_single_char_with_period = len([i for i in text.split(" ") if len(i) == 2 and i.endswith(".")]) / len(
        text.split(" ")
    )
    if percentage_single_char + percentage_single_char_with_period > 0.10:
        score += 3

    return score


def split_references(text):
    """
    Splits the text into (content, references).
    Returns (content_str, references_str).
    If no references found, references_str is None.
    """
    # Split by double newline (paragraphs)
    chunks = re.split(r"\n\n+", text)

    threshold = 1

    split_index = len(chunks)

    patience = 2
    consecutive_low = 0

    for i in range(len(chunks) - 1, -1, -1):
        chunk = chunks[i].strip()
        if not chunk:
            continue

        score = get_heuristic_score(chunk)

        if score >= threshold:
            split_index = i
            consecutive_low = 0
        else:
            consecutive_low += 1
            if consecutive_low > patience:
                break

    if split_index == len(chunks):
        return text, None

    content_chunks = chunks[:split_index]
    ref_chunks = chunks[split_index:]

    content_str = "\n\n".join(content_chunks)
    references_str = "\n\n".join(ref_chunks)

    return content_str, references_str
