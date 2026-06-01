import re

# Import from our own modules
from .text_validation import MIN_ALPHA_CHARS, MIN_CONTENT_CHARS, _normalize_text, is_string_valid

# These are moved from sectionize.py - keeping the same values
unneeded_sections_no_skip_remaining = [
    # "abstract",
    "caption",
    "figure",
    "table",
    "authorcontribution",
    "authoraffiliation",
    "keyword",
    "disclaimer",
    "fig",
    "deleted",
    "http",
    "et al",
    "equation",
    "â¢",
    "geofluids",
    "scientificreports|plosone",
    "acsomega",
    "www.intechopen.com",
    "www.frontiersin.org",
    "dovepress",
    "advancesinmeteorology",
    "frontiersin",
    "author",
    "authorsummary",
    "publicintereststatement",
    "backclose",
    "viewarticleonline",
    "asshownin",
    "scheme",
    "box",
    "reviewer",
    "continuedfromprevpage",
    "informedconsentstatement",
]

needed_sections_but_skip_remaining = ["conclusion"]

# ---------------------------------------------------------------------------
# Synonym table: maps normalized header variants → canonical header string.
# Keys are the *output* of _normalize_header (lowercase, no prefixes, etc.).
# Values are the canonical form that should appear in the sectionized output.
# Organized by semantic group for readability.
# ---------------------------------------------------------------------------
HEADER_SYNONYMS: dict[str, str] = {
    # -- discussion ----------------------------------------------------------
    "discussions": "discussion",
    # -- conclusion ----------------------------------------------------------
    "conclusions": "conclusion",
    "concluding remarks": "conclusion",
    "concluding remark": "conclusion",
    "final remarks": "conclusion",
    "final remark": "conclusion",
    "final considerations": "conclusion",
    "final consideration": "conclusion",
    # -- materials and methods -----------------------------------------------
    # ampersand variants
    "materials & methods": "materials and methods",
    "material & methods": "materials and methods",
    "materials & method": "materials and methods",
    "material & method": "materials and methods",
    # singular/plural mixing
    "material and methods": "materials and methods",
    "materials and method": "materials and methods",
    "material and method": "materials and methods",
    # reversed order
    "methods and materials": "materials and methods",
    "methods and material": "materials and methods",
    "method and materials": "materials and methods",
    "method and material": "materials and methods",
    # chemistry synonyms
    "materials and reagents": "materials and methods",
    "materials and chemicals": "materials and methods",
    "reagents and materials": "materials and methods",
    "chemicals and materials": "materials and methods",
    # bare "methods" variants that imply the same section
    "methodology": "methods",
    "experimental methods": "methods",
    "experimental": "methods",
    "experimental section": "methods",
    "experimental procedures": "methods",
    "experimental procedure": "methods",
    # -- method (singular) ---------------------------------------------------
    "method": "methods",
    # -- results and discussion ----------------------------------------------
    "results and discussions": "results and discussion",
    "result and discussion": "results and discussion",
    "result and discussions": "results and discussion",
    "results & discussion": "results and discussion",
    "result & discussion": "results and discussion",
    "results and analysis": "results and discussion",
    "result and analysis": "results and discussion",
    # -- discussion and conclusions ------------------------------------------
    "discussion and conclusion": "discussion and conclusions",
    "conclusions and discussion": "discussion and conclusions",
    "conclusion and discussion": "discussion and conclusions",
    "discussions and conclusions": "discussion and conclusions",
    "discussions and conclusion": "discussion and conclusions",
    # -- methodology ---------------------------------------------------------
    "methodologies": "methodology",
    "research methodology": "methodology",
    "research method": "methodology",
    "research methods": "methodology",
    "research design": "methodology",
    "research design and methods": "methodology",
    # -- statistical analysis ------------------------------------------------
    "statistical analyses": "statistical analysis",
    "statistical methods": "statistical analysis",
    "statistical method": "statistical analysis",
    "statistical data analysis": "statistical analysis",
    "statistical data analyses": "statistical analysis",
    "statistics": "statistical analysis",
    # -- data analysis -------------------------------------------------------
    "data analyses": "data analysis",
    # -- data and methods ----------------------------------------------------
    "data and method": "data and methods",
    "data and methodology": "data and methods",
    "data and methodologies": "data and methods",
    # -- study area ----------------------------------------------------------
    "study areas": "study area",
    "study site": "study area",
    "study sites": "study area",
    "study region": "study area",
    "study regions": "study area",
    "study area and data": "study area",
    "site description": "study area",
    "description of the study area": "study area",
    "overview of the study area": "study area",
    "study area description": "study area",
    "the study area": "study area",
    # -- literature review ---------------------------------------------------
    "literature search": "literature review",
    "literature survey": "literature review",
    "review of literature": "literature review",
    # -- related work --------------------------------------------------------
    "related works": "related work",
    # -- summary -------------------------------------------------------------
    "summary and conclusions": "summary",
    "summary and conclusion": "summary",
    "summary and discussion": "summary",
    "summary and outlook": "summary",
    # (summary and conclusions was previously mapped to conclusion; summary
    # is the better canonical since these sections open with a summary before
    # any concluding statement)
    # -- experimental design -------------------------------------------------
    "experimental designs": "experimental design",
    "design of experiments": "experimental design",
    "experiment design": "experimental design",
    # -- participants --------------------------------------------------------
    "subjects": "participants",
    "patients": "participants",
    "animals": "participants",
    "study population": "participants",
    "study subjects": "participants",
    # -- limitations ---------------------------------------------------------
    "limitation": "limitations",
    "limitations of the study": "limitations",
    "limitations of this study": "limitations",
    "study limitations": "limitations",
    "limitation of the study": "limitations",
    "strengths and limitations": "limitations",
}


def apply_synonyms(header: str) -> str:
    """
    Map a normalized header to its canonical form using HEADER_SYNONYMS.

    This is applied *after* _normalize_header so both input and lookup key
    are already lowercase with prefixes stripped.
    """
    return HEADER_SYNONYMS.get(header, header)


unneeded_sections_skip_remaining = [
    "acknowledgment",
    "acknowledgement",
    "reference",
    "bibliography",
    "dataavailability",
    "codeavailability",
    "funding",
    "pre-publicationhistory",
    "ethicstatement",
    "ethicsstatement",
    "grantinformation",
    "competinginterests",
    "conflictsofinterest",
    "supplementarymaterial",
    "disclosurestatement",
    "abbreviation",
    "appendix",
    "howtoreference",
    "cited",
    "contributionstatement",
    "modelavailability",
    "codeavailability",
    "supportinginformation",
    "declarationofinterest",
    "citationinformation",
    "orcid",
    "notesoncontributors",
    "forpeerreview",
    "appendice",
    "nomenclature",
    "glossary",
    "notation",
    "symbol",
    "openaccess",
]


def _normalize_header(header: str) -> str:
    """
    Normalize section header text using the 8-step surface cleaning pipeline:

    1. Strip whitespace
    2. Remove unicode/parser garbage
    3. Strip pipe / bullet prefix from the start only: | * #
    4. Fix OCR mid-word spaces conservatively
    5. Strip roman numeral prefixes
    6. Strip digit prefixes
    7. Strip leading/trailing punctuation
    8. Lowercase + final strip
    """
    if not isinstance(header, str):
        return ""

    # Step 1: strip whitespace
    header = header.strip()
    if not header:
        return ""

    # Step 2: remove unicode/parser garbage
    # NBSP -> space; strip replacement char, soft hyphen, zero-widths, BOM
    header = header.replace("\u00a0", " ")
    header = re.sub(r"[\uFFFD\u00AD\u200B-\u200D\uFEFF]", "", header)

    # Strip standalone mojibake tokens (e.g. "â", "Ã", "ï", "Â", "â¢").
    # These appear as isolated tokens surrounded by whitespace when UTF-8 has
    # been double-decoded. We only remove them when they are NOT adjacent to
    # alphabetic characters, so legitimate accented words like "café" survive.
    mojibake_chars = "\u00e2\u00c3\u00ef\u00c2"  # â Ã ï Â
    mojibake_token_re = re.compile(rf"(?:(?<=^)|(?<=\s))[{mojibake_chars}][^\sA-Za-z0-9]*(?=\s|$)")
    header = mojibake_token_re.sub("", header)

    # Normalize dash variants to improve prefix matching
    header = header.replace("–", "-").replace("—", "-").replace("−", "-")

    # Base normalization
    header = _normalize_text(header)
    if not header:
        return ""

    # Step 3: strip pipe / bullet prefix from START only
    header = re.sub(r"^\s*[|*#]+\s*", "", header)
    if not header:
        return ""

    # Step 4: fix OCR mid-word spaces conservatively
    # Stopwords that signal a genuine multi-word phrase — never merge across them.
    _STOPWORDS = frozenset(["and", "or", "of", "the", "in", "for", "to", "a", "an", "with", "by"])

    def _looks_like_fragmented_ocr(text: str) -> bool:
        tokens = text.split()
        if len(tokens) < 2:
            return False
        if not all(re.fullmatch(r"[A-Za-z]+", t) for t in tokens):
            return False
        # If any token is a stopword the string is a real multi-word phrase,
        # not an OCR-fragmented single word (e.g. "MATERIAL S AND ME THODS").
        if any(t.lower() in _STOPWORDS for t in tokens):
            return False

        all_upper = all(t.upper() == t for t in tokens)
        merged_len = sum(len(t) for t in tokens)
        has_tiny = any(len(t) <= 3 for t in tokens)

        # All-caps fragments where at least one token is suspiciously short
        # (≤3 chars) AND the merged result is plausibly one word (≤12 chars).
        # e.g. "RE SULTS" (RE=2), "D ISCUSS I ON" (D=1, I=1), "DISCUSS ION" (ION=3).
        # We require has_tiny so we don't collapse real two-word phrases like
        # "DATA ANALYSIS" (4+8=12) or "STUDY AREA" (5+4=9) or "RELATED WORK"
        # (7+4=11) which have no tokens short enough to be OCR fragments.
        if all_upper and has_tiny and merged_len <= 12:
            return True

        short_count = sum(1 for t in tokens if len(t) <= 4)
        tiny_count = sum(1 for t in tokens if len(t) <= 2)
        upperish_count = sum(1 for t in tokens if t.upper() == t)

        return (
            short_count >= 2
            and (tiny_count >= 1 or short_count >= max(2, len(tokens) - 1))
            and upperish_count >= max(2, len(tokens) - 1)
        )

    def _repair_fragmented_ocr(text: str) -> str:
        prev = None
        cur = text
        while cur != prev and _looks_like_fragmented_ocr(cur):
            prev = cur
            cur = "".join(cur.split())
        return cur

    def _repair_fragmented_ocr_phrase(text: str) -> str:
        """
        Handle phrases like "MATERIAL S AND ME THODS" where OCR has split
        individual words but stopwords prevent whole-string merging.
        Split on stopwords, repair each segment independently, then rejoin.
        """
        tokens = text.split()
        if not any(t.lower() in _STOPWORDS for t in tokens):
            return _repair_fragmented_ocr(text)

        # Split into runs separated by stopword tokens, repair each run.
        result_parts: list[str] = []
        current_run: list[str] = []

        def flush_run():
            if current_run:
                result_parts.append(_repair_fragmented_ocr(" ".join(current_run)))
                current_run.clear()

        for token in tokens:
            if token.lower() in _STOPWORDS:
                flush_run()
                result_parts.append(token.lower())
            else:
                current_run.append(token)
        flush_run()

        return " ".join(result_parts)

    header = _repair_fragmented_ocr_phrase(header)

    # Step 5: strip roman numeral prefix
    # Require an explicit punctuation separator (., -, :, closing paren/bracket)
    # between the numeral and the rest. We deliberately do NOT strip on bare
    # whitespace alone (e.g. "MIX Methods") because real words like "MIX",
    # "DID", "CIVIL" are all valid roman numerals and would be misclassified.
    roman_prefix_pattern = re.compile(
        r"""
        ^\s*
        (?:
            \([IVXLCDM]+\)              |   # (III)
            \[[IVXLCDM]+\]              |   # [III]
            [IVXLCDM]+\s*[.\-:\)]           # III. / III- / III: / III)
        )
        \s*
        (?=[A-Za-z])
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    header = roman_prefix_pattern.sub("", header)

    # Step 6: strip digit prefix
    # Match: "1.", "2.1", "3.2.1", "(1)", "[2.1]", optionally followed by
    # trailing punctuation, and a separator that is either whitespace OR a
    # letter boundary (handles "1.Introduction" with no space).
    digit_prefix_pattern = re.compile(
        r"""
        ^\s*
        (?:
            \(\d+(?:\.\d+)*\)       |   # (1) or (2.1)
            \[\d+(?:\.\d+)*\]       |   # [1] or [2.1]
            \d+(?:\.\d+)*               # 1 or 2.1 or 3.2.1
        )
        \s*[.\-:\)]?\s*
        (?=[A-Za-z])
        """,
        re.VERBOSE,
    )
    header = digit_prefix_pattern.sub("", header)

    # Step 7: strip leading/trailing punctuation only
    header = re.sub(r'^[\s\.,;:!\?\-\[\]\(\)\{\}"\'`]+', "", header)
    header = re.sub(r'[\s\.,;:!\?\-\[\]\(\)\{\}"\'`]+$', "", header)

    # Step 8: lowercase + final strip
    header = header.lower().strip()

    return header


def _header_is_noise(header: str) -> bool:
    """
    Determine if a header represents noise rather than a meaningful section header.
    """
    if not header:
        return True

    normalized = _normalize_header(header)
    lowered = normalized.lower()
    compact = re.sub(r"\s+", "", lowered)

    if not normalized:
        return True

    # enumeration fragments like "v.", "ii", "a)"
    if re.fullmatch(r"[ivxlcdm]+[.)]?", lowered):
        return True
    if re.fullmatch(r"[a-zA-Z][.)]?", normalized):
        return True

    # table / figure labels
    if re.fullmatch(r"(table|fig|figure)\s*[-.]?\s*\d*", lowered):
        return True

    # mostly symbols / numbers
    alpha_count = len(re.findall(r"[A-Za-z]", normalized))
    if alpha_count < 2:
        return True

    # reject mojibake / decomposition artifacts (e.g. "ï¨ ï" → "i̋¨ i̋" after NFD)
    # that inflate alpha_count with isolated letters from combining sequences
    if not re.search(r"[A-Za-z]{2,}", normalized):
        return True

    if not is_string_valid(normalized):
        return True

    # noisy one-token fragments that are not likely real section headers
    if len(normalized.split()) == 1 and len(normalized) <= 3:
        return True

    # catch normalized "table", "figure", etc.
    if any(j in compact for j in unneeded_sections_no_skip_remaining):
        if len(normalized.split()) <= 3:
            return True

    return False


def _content_is_substantive(content: str) -> bool:
    """
    Determine if content is substantial enough to be considered a real section.
    """
    content = _normalize_text(content)
    if len(content) < MIN_CONTENT_CHARS:
        return False

    alpha_chars = len(re.findall(r"[A-Za-z]", content))
    if alpha_chars < MIN_ALPHA_CHARS:
        return False

    return True


def _line_spacing_resembles_header(line: str, splitlines: list[str], index: int) -> bool:
    """
    Determine if line spacing resembles a header based on surrounding blank lines.
    """
    if index < 2 or index >= len(splitlines) - 1:
        return False
    if (
        len(line.split()) >= 1
        and len(line.split()) < 15
        and not len(splitlines[index - 1])
        and not len(splitlines[index - 2])
        and not len(splitlines[index + 1])
    ):
        return True
    elif (
        len(line.split()) >= 1
        and not len(splitlines[index - 1])
        and not len(splitlines[index - 2])
        and "abstract" in line.lower()
    ):
        return True
    return False
