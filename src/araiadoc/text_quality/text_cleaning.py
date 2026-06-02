import re

# regex from https://www.geeksforgeeks.org/python-check-url-string/ - cant answer any questions about it :)
URL_RE = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"  # noqa


def _is_url_dominant(text: str) -> bool:
    """if more than a third of the characters in the subsection belong to URLs, return True"""
    all_urls = re.findall(URL_RE, text)
    all_urls_chars = "".join([i[0] for i in all_urls])
    if len(all_urls_chars) > len(text) / 3:
        return True
    return False


def _strip_urls(text: str) -> str:
    """remove URLs from text"""
    all_urls = re.findall(URL_RE, text)
    all_urls = [i[0] for i in all_urls]
    for i in all_urls:
        text = text.replace(i, "")
    return text


def _strip_phone_numbers(text: str) -> str:
    """remove phone numbers from text"""
    all_phone_numbers = re.findall(
        r"(\d{3}[-.]?\d{3}[-.]?\d{4}|\(\d{3}\)\s*\d{3}[-.]?\d{4}|\d{3}[-.]?\d{4})",
        text,
    )
    for i in all_phone_numbers:
        text = text.replace(i, "")
    return text


def _strip_sequential_nonalphanumeric(text: str) -> str:
    """remove groups of 3+ consecutive non-alphanumeric characters from text"""
    all_groups = re.findall("[^a-zA-Z0-9]{3,}", text)
    for i in all_groups:
        text = text.replace(i, " ")
    return text


def _clean_subsections(sub_sections: list[str]) -> list[str]:
    cleaned_subsections = []

    for section in sub_sections:
        cleaned = "".join([i.strip() for i in section.split("\n") if len(i)])
        if len(cleaned) and not _is_url_dominant(cleaned):
            cleaned = _strip_urls(cleaned)
            cleaned = _strip_phone_numbers(cleaned)
            cleaned = _strip_sequential_nonalphanumeric(cleaned)
            cleaned_subsections.append(cleaned)

    return cleaned_subsections
