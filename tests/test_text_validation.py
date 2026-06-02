"""
Tests for araiadoc.text_quality.text_validation:
  - _normalize_text
  - is_string_valid
  - is_english

Run with:
    pixi run -e dev python tests/test_text_validation.py
"""

from araiadoc.text_quality.text_validation import _normalize_text, is_english, is_string_valid

# ---------------------------------------------------------------------------
# (input, expected, description)
# ---------------------------------------------------------------------------

NORMALIZE_TEXT_CASES = [
    # Basic whitespace collapsing
    ("hello   world", "hello world", "Collapse internal spaces"),
    ("  hello\tworld  ", "hello world", "Strip edges + collapse tab"),
    ("line1\nline2", "line1 line2", "Newline → space"),
    ("a\n\n\nb", "a b", "Multiple newlines collapsed"),
    # HTML entities
    ("Smith &amp; Jones", "Smith & Jones", "HTML amp entity"),
    ("&lt;tag&gt;", "<tag>", "HTML lt/gt entities"),
    ("&quot;quoted&quot;", '"quoted"', "HTML quote entity"),
    # Unicode NFD normalization (accented chars decompose but re-combine visually)
    ("café", "cafe\u0301", "NFD decomposes accented char"),
    # Non-string input → empty string
    (None, "", "None input"),
    (42, "", "Int input"),
    ([], "", "List input"),
    # Empty / whitespace-only
    ("", "", "Empty string"),
    ("   ", "", "Whitespace-only string"),
    # Mixed: HTML + whitespace
    ("hello  &amp;  world  ", "hello & world", "HTML + extra whitespace"),
]

IS_STRING_VALID_CASES = [
    # Clean prose → valid
    ("This is a normal sentence.", True, "Normal prose"),
    ("Introduction", True, "Single word"),
    # High digit percentage → invalid  (>30%)
    ("1234567890abc", False, "High digit ratio"),
    ("90210 90210 90210", False, "Many digits"),
    # Special chars only but NO digits → digit guard not entered → valid
    # (is_string_valid only checks special-char ratio when digits are present)
    ("!@#$%^&*()abcde", True, "High special-char but no digits → passes"),
    # Borderline: some digits but under threshold → valid
    ("Year 2023 was good", True, "Few digits, valid"),
    ("Section 3.2 results", True, "Section number, valid"),
    # Empty string (total_count == 0 branch after digit check skipped)
    ("", True, "Empty string — no digits, passes trivially"),
    # No digits → special-char check skipped entirely → valid
    ("---...---...---!", True, "All specials but no digits → passes"),
    # Digits present + high special ratio → invalid
    ("1!@#$%^&*()", False, "Digits present + high special-char ratio"),
    # Normal with a few specials
    ("Hello, world!", True, "Comma + exclamation, valid"),
]

IS_ENGLISH_CASES = [
    # English text
    ("The quick brown fox jumps over the lazy dog.", True, "Classic English sentence"),
    (
        "This study investigates the effect of temperature on reaction rates.",
        True,
        "Academic English",
    ),
    # Non-English text
    ("Este es un texto en español.", False, "Spanish text"),
    ("Dies ist ein deutscher Text.", False, "German text"),
    # Edge cases that return False
    ("", False, "Empty string"),
    ("   ", False, "Whitespace only"),
    # Numeric/symbol-only triggers LangDetectException → False
    ("12345 67890 !!!", False, "Numbers and symbols only"),
]


def _run_suite(label: str, cases: list, fn) -> tuple[int, int]:
    passes = fails = 0
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    for inp, expected, note in cases:
        actual = fn(inp)
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passes += 1
        else:
            fails += 1
        print(f"[{status}] {note!r:55s} {inp!r:40s} -> {actual!r} (expected {expected!r})")
    return passes, fails


def main() -> int:
    total_pass = total_fail = 0

    p, f = _run_suite("_normalize_text", NORMALIZE_TEXT_CASES, _normalize_text)
    total_pass += p
    total_fail += f

    p, f = _run_suite("is_string_valid", IS_STRING_VALID_CASES, is_string_valid)
    total_pass += p
    total_fail += f

    p, f = _run_suite("is_english", IS_ENGLISH_CASES, is_english)
    total_pass += p
    total_fail += f

    print(f"\nTotal: {total_pass + total_fail}, Passed: {total_pass}, Failed: {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
