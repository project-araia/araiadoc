from pydantic import BaseModel


class ParsedDocumentSchema(BaseModel):
    source: str = ""
    title: str = ""
    text: dict[str, str] = {}  # keys are section headings, values are text
    abstract: str = ""
    authors: list[str] = []
    publisher: str = ""
    date: int | str = 0
    unique_id: str = ""
    doi: str = ""
    references: str = ""
