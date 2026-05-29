import html
import re
import unicodedata

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

NUMERIC_SPECIAL_THRESHOLD = 30
MIN_CONTENT_CHARS = 40
MIN_ALPHA_CHARS = 20


def is_english(text: str) -> bool:
    """
    Returns True if the text is detected as English, False otherwise.
    Handles exceptions for numeric/symbol-only strings or empty text: returns False in those cases.
    """
    if not text or text.strip() == "":
        return False
    try:
        # detect() can throw an exception for numeric/symbol-only text
        return detect(text) == "en"
    except LangDetectException:
        return False


def is_string_valid(string: str) -> bool:
    if re.search(r"\d", string):
        digit_count = len(re.findall(r"\d", string))
        total_count = len(string)
        if total_count == 0:
            return False

        numeric_percentage = (digit_count / total_count) * 100
        if numeric_percentage > NUMERIC_SPECIAL_THRESHOLD:
            return False

        special_count = len(re.findall(r"[^a-zA-Z0-9]", string))
        special_percentage = (special_count / total_count) * 100
        if special_percentage > NUMERIC_SPECIAL_THRESHOLD:
            return False

    return True


def _normalize_text(text: str) -> str:
    """
    Normalize Unicode strings and clean whitespace. Necessary for text which contains non-ASCII characters.
    """
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFD", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
