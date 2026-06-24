import re

# Import from our own modules
from .text_validation import (
    MIN_ALPHA_CHARS,
    MIN_CONTENT_CHARS,
    _normalize_text,
    is_string_valid,
)

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
    "references",
]

needed_sections_but_skip_remaining = ["conclusion"]

# ---------------------------------------------------------------------------
# Synonym table: maps normalized header variants → canonical header string.
# Keys are the *output* of _normalize_header (lowercase, no prefixes, etc.).
# Values are the canonical form that should appear in the sectionized output.
# Organized by semantic group for readability.
# ---------------------------------------------------------------------------
HEADER_SYNONYMS: dict[str, str] = {
    # -- title / abstract ----------------------------------------------------
    # Q4: foreign-language abstracts → abstract
    "resumo": "abstract",
    "resumen": "abstract",
    # -- introduction --------------------------------------------------------
    "introduccion": "introduction",
    # -- results (singular) --------------------------------------------------
    "result": "results",
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
    # methodology-shaped variants
    "materials and methodology": "materials and methods",
    "material and methodology": "materials and methods",
    "methods & materials": "materials and methods",
    "materials and methods section": "materials and methods",
    # chemistry synonyms
    "materials and reagents": "materials and methods",
    "materials and chemicals": "materials and methods",
    "reagents and materials": "materials and methods",
    "chemicals and materials": "materials and methods",
    # -- method (singular) ---------------------------------------------------
    "method": "methods",
    # bare "methods" variants that imply the same section
    "experimental methods": "methods",
    "experimental": "methods",
    "experimental section": "methods",
    "experimental procedures": "methods",
    "experimental procedure": "methods",
    # -- methodology ---------------------------------------------------------
    "methodology": "methodology",
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
    "statistical": "statistical analysis",
    "analysis of variance": "statistical analysis",
    # -- data analysis -------------------------------------------------------
    "data analyses": "data analysis",
    # -- data and methods ----------------------------------------------------
    "data and method": "data and methods",
    "data and methodology": "data and methods",
    "data and methodologies": "data and methods",
    "data & methods": "data and methods",
    # -- data collection -----------------------------------------------------
    "data collection and analysis": "data collection",
    "data collection and processing": "data collection",
    "data collection methods": "data collection",
    # -- data processing -----------------------------------------------------
    # (standalone canonical — no variants in the wild yet)
    # -- study area ----------------------------------------------------------
    "study areas": "study area",
    "study site": "study area",
    "study sites": "study area",
    "study region": "study area",
    "study regions": "study area",
    "study location": "study area",
    "the study area": "study area",
    "site": "study area",
    "site description": "study area",
    "site descriptions": "study area",
    "site characteristics": "study area",
    "study site description": "study area",
    "description of the study area": "study area",
    "description of study area": "study area",
    "description of the study site": "study area",
    "overview of the study area": "study area",
    "study area description": "study area",
    "study area and data": "study area",
    "study area and datasets": "study area",
    "study area and dataset": "study area",
    "study area and sampling": "study area",
    "study area and data collection": "study area",
    "study area and materials": "study area",
    "study area and data sources": "study area",
    "area of study": "study area",
    # -- related work --------------------------------------------------------
    "related works": "related work",
    # -- literature review ---------------------------------------------------
    "literature search": "literature review",
    "literature survey": "literature review",
    "review of literature": "literature review",
    # -- background ----------------------------------------------------------
    # (standalone canonical — no variants in the wild yet)
    # -- summary -------------------------------------------------------------
    "summary and conclusions": "summary",
    "summary and conclusion": "summary",
    "summary and discussion": "summary",
    "summary and outlook": "summary",
    # (summary and conclusions was previously mapped to conclusion; summary
    # is the better canonical since these sections open with a summary before
    # any concluding statement)
    # -- plant material ------------------------------------------------------
    "plant materials": "plant material",
    "plant material and growth conditions": "plant material",
    "plant materials and growth conditions": "plant material",
    "plant material and experimental design": "plant material",
    "plant materials and experimental design": "plant material",
    "plant materials and treatments": "plant material",
    "plant material and treatments": "plant material",
    "plant materials and stress treatments": "plant material",
    "plant materials and growing conditions": "plant material",
    "plant material and growing conditions": "plant material",
    "plant growth conditions": "plant material",
    # -- experimental design -------------------------------------------------
    "experimental designs": "experimental design",
    "design of experiments": "experimental design",
    "experiment design": "experimental design",
    "experimental design and treatments": "experimental design",
    "experimental design and statistical analysis": "experimental design",
    "treatments and experimental design": "experimental design",
    # -- experimental setup --------------------------------------------------
    "experimental set-up": "experimental setup",
    # -- sample preparation --------------------------------------------------
    # (standalone canonical — no variants in the wild yet)
    # -- sample collection ---------------------------------------------------
    # (standalone canonical — no variants in the wild yet)
    # -- sensitivity analysis ------------------------------------------------
    "sensitivity analyses": "sensitivity analysis",
    # -- model ---------------------------------------------------------------
    "model description": "model",
    "model development": "model",
    "model setup": "model",
    "model structure": "model",
    "model overview": "model",
    # -- model validation ----------------------------------------------------
    "model calibration": "model validation",
    "model calibration and validation": "model validation",
    "calibration and validation": "model validation",
    # -- sampling ------------------------------------------------------------
    "sampling design": "sampling",
    "sampling procedure": "sampling",
    "sampling procedures": "sampling",
    "sampling methods": "sampling",
    "sampling method": "sampling",
    "sampling strategy": "sampling",
    # -- study design --------------------------------------------------------
    "study design and setting": "study design",
    "study design and participants": "study design",
    "study design and population": "study design",
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
    # -- case study ----------------------------------------------------------
    "case studies": "case study",
    # -- objectives ----------------------------------------------------------
    "objective": "objectives",
    "objectives of the study": "objectives",
    "research objectives": "objectives",
    # -- implications --------------------------------------------------------
    "policy implications": "implications",
    "practical implications": "implications",
    # -- recommendations -----------------------------------------------------
    "conclusions and recommendations": "recommendations",
    "conclusion and recommendations": "recommendations",
    "conclusions and recommendation": "recommendations",
    "conclusion and recommendation": "recommendations",
    # -- miscellaneous standalones -------------------------------------------
    "characterizations": "characterization",
    "chemicals and reagents": "chemicals",
    "reagents": "chemicals",
    "treatments": "treatment",
    "procedures": "procedure",
    "measures": "measurements",
    "experiments": "experiment",
    "datasets": "dataset",
    "samples": "sample",
}


def apply_synonyms(header: str) -> str:
    """
    Map a normalized header to its canonical form using HEADER_SYNONYMS.

    This is applied *after* _normalize_header. `_normalize_header` may now retain
    a leading enumeration prefix (e.g. "3. introduction") when readable text
    follows it. To keep canonicalization stable, the synonym lookup is performed
    against the enumeration-stripped key. If a synonym exists, its canonical
    value is returned (numeral dropped); otherwise the original header is
    returned unchanged so the numeral is preserved in the stored output.
    """
    if header in HEADER_SYNONYMS:
        return HEADER_SYNONYMS[header]
    stripped = _strip_enumeration_prefix(header).strip()
    if stripped != header and stripped in HEADER_SYNONYMS:
        return HEADER_SYNONYMS[stripped]
    return header


unneeded_sections_skip_remaining = [
    "acknowledgment",
    "acknowledgement",
    "workscited",
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
    "openaccess",
]


# Enumeration prefixes: roman numeral, single-letter, and digit forms.
# Each requires an explicit punctuation separator (., -, :, closing paren /
# bracket) or a letter boundary between the marker and the rest, and a
# following alphabetic char. Order matters: roman before single-letter before
# digit (a lone "I." is a roman numeral, not a single letter).
_ENUM_PREFIX_PATTERNS: tuple[re.Pattern, ...] = (
    # roman numeral: III. / III- / III: / III) / (III) / [III]
    re.compile(
        r"""
        ^\s*
        (?:
            \([IVXLCDM]+\)              |
            \[[IVXLCDM]+\]              |
            [IVXLCDM]+\s*[.\-:\)]
        )
        \s*
        (?=[A-Za-z])
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    # single-letter subsection: A. Methods / B) Results
    re.compile(r"^\s*[A-Za-z]\s*[.\-:)\]]\s*(?=[A-Za-z])"),
    # digit: 1. / 2.1 / 3.2.1 / (1) / [2.1], optionally trailing punct, then a
    # letter boundary (handles "1.Introduction" with no space).
    re.compile(
        r"""
        ^\s*
        (?:
            \(\d+(?:\.\d+)*\)       |
            \[\d+(?:\.\d+)*\]       |
            \d+(?:\.\d+)*
        )
        \s*[.\-:\)]?\s*
        (?=[A-Za-z])
        """,
        re.VERBOSE,
    ),
)


def _strip_enumeration_prefix(header: str) -> str:
    """Unconditionally strip a leading roman / single-letter / digit prefix.

    Applies each enumeration pattern at most once, in priority order. Used to
    build the comparison / synonym-lookup key so that keeping the numeral in the
    *stored* header (see `_conditionally_strip_enumeration_prefix`) does not
    change filtering or canonicalization behavior.
    """
    if not isinstance(header, str):
        return ""
    for pat in _ENUM_PREFIX_PATTERNS:
        new = pat.sub("", header, count=1)
        if new != header:
            return new
    return header


def _has_readable_text(text: str) -> bool:
    """True if `text` contains a run of >=2 consecutive ASCII letters."""
    return bool(re.search(r"[A-Za-z]{2,}", text))


# Captures the bare marker (digits like "3.2.1" or a roman numeral) from a
# leading enumeration prefix, discarding any surrounding brackets / separators
# so the retained marker is rendered cleanly as "<marker> <remainder>".
_ENUM_MARKER_RE = re.compile(
    r"""
    ^\s*
    [\(\[]?\s*
    (?P<marker>
        \d+(?:\.\d+)*           |   # 3 / 2.1 / 3.2.1
        [IVXLCDM]+                  # roman numeral
    )
    \s*[.\-:\)\]]*\s*
    (?P<rest>[A-Za-z].*)$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _conditionally_strip_enumeration_prefix(header: str) -> str:
    """Strip a leading enumeration prefix ONLY when nothing readable remains.

    Keeps the numeral for headers like "3. Introduction" (readable remainder)
    while collapsing pure enumerations like "3." or "IV:" to empty so they are
    dropped downstream. When the numeral is kept, surrounding bracket / separator
    noise is normalized so the result is "<marker> <remainder>"
    (e.g. "(2) Background" -> "2 Background", "[III] Results" -> "III Results").
    """
    stripped = _strip_enumeration_prefix(header)
    if stripped == header:
        return header
    # If removing the prefix leaves readable text, keep the numeral but tidy
    # the marker punctuation to a canonical "<marker>. <remainder>" form. We
    # keep an explicit "." separator (rather than a bare space) so that the
    # enumeration prefix remains strippable by `_strip_enumeration_prefix` when
    # building the comparison / synonym-lookup key — a bare-space roman marker
    # ("IV Results") is intentionally NOT strippable there to avoid clipping
    # real words that look like roman numerals (e.g. "MIX Methods").
    if _has_readable_text(stripped):
        m = _ENUM_MARKER_RE.match(header)
        if m:
            return f"{m.group('marker')}. {m.group('rest')}"
        return header
    # Otherwise the prefix was the whole header — keep it stripped (-> empty/noise).
    return stripped


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

    # Steps 5/5b/6: enumeration prefixes (roman numeral / single-letter /
    # digit). Historically these were always stripped. We now KEEP a leading
    # numeral when the rest of the header still contains readable text, so
    # "3. Introduction" -> "3. introduction" and "IV: Methods" -> "iv: methods".
    # A header that is *entirely* an enumeration ("3.", "IV:") has no readable
    # remainder, so the prefix is stripped to empty and dropped downstream by
    # `_header_is_noise`. `_strip_enumeration_prefix` performs the unconditional
    # strip used to build the comparison / synonym lookup key elsewhere.
    header = _conditionally_strip_enumeration_prefix(header)

    # Step 7: strip leading/trailing punctuation only
    header = re.sub(r'^[\s\.,;:!\?\-\[\]\(\)\{\}"\'`]+', "", header)
    header = re.sub(r'[\s\.,;:!\?\-\[\]\(\)\{\}"\'`]+$', "", header)

    # Step 8: lowercase + final strip
    header = header.lower().strip()

    return header


def _header_is_structural_noise(header: str) -> bool:
    """
    Subset of `_header_is_noise`: True only for headers that look like
    *intra-section markup* (bullet glyphs, lone enumeration markers like
    "2.", "i)", "1.1.", single letters, strings with fewer than two
    consecutive alpha chars) rather than legitimate-but-unwanted real
    sections (e.g. "References", "Figure 1", "Keywords").

    The sectionizer's span walk uses this to decide whether a header
    span should be *swallowed* (paragraphs fold into the preceding real
    section, as a human reader would expect for bulleted list items) vs.
    *opened as its own section* and then dropped by the downstream filter
    loop (which is what we still want for "References" et al.).

    Keep this strictly narrower than `_header_is_noise`: anything that
    might be a real section's title — even one we ultimately want to drop —
    must NOT be classified as structural noise, because doing so would
    silently merge its body content into the previous kept section.
    """
    if not header:
        return True

    normalized = _normalize_header(header)
    if not normalized:
        return True

    lowered = normalized.lower()

    # enumeration fragments like "v.", "ii", "a)"
    if re.fullmatch(r"[ivxlcdm]+[.)]?", lowered):
        return True
    # single-letter "headers" like "a)" or "X."
    if re.fullmatch(r"[a-zA-Z][.)]?", normalized):
        return True

    # mostly symbols / numbers (covers bullet glyphs like U+201A, "--", "*",
    # bare digits "3", multi-digit "11.", subsection numbers "1.1.").
    alpha_count = len(re.findall(r"[A-Za-z]", normalized))
    if alpha_count < 2:
        return True

    # mojibake / decomposition artifacts with no real word-run
    if not re.search(r"[A-Za-z]{2,}", normalized):
        return True

    # very-short one-token fragments ("ab", "ix", "xi")
    if len(normalized.split()) == 1 and len(normalized) <= 3:
        return True

    return False


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

    # All structural-noise cases (enumeration fragments, single letters,
    # mostly-symbols, tiny tokens) are also noise.
    if _header_is_structural_noise(header):
        return True

    # table / figure labels
    if re.fullmatch(r"(table|fig|figure)\s*[-.]?\s*\d*", lowered):
        return True

    if not is_string_valid(normalized):
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
