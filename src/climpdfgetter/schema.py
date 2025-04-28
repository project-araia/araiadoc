from pydantic import BaseModel


class ParsedDocumentSchema(BaseModel):
    source: str = ""
    title: str = ""
    text: list[str] = []
    abstract: str = ""
    authors: list[str] = []
    publisher: str = ""
    date: int | str = 0
    unique_id: str = ""
    doi: str = ""
