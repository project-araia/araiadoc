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
]

needed_sections_but_skip_remaining = ["conclusion"]

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
    Normalize header text by removing trailing punctuation and extra whitespace.
    """
    header = _normalize_text(header)
    header = re.sub(r"\s*[:.\-–—]+\s*$", "", header).strip()
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
