from pydantic import BaseModel


class ParsedDocumentSchema(BaseModel):
    source: str = ""
    title: str = ""
    text: list[str] = []
    abstract: str = ""
    authors: list[str] = []
    origin_format: str = ""
    publisher: str = ""
    year: int = 0
    unique_id: str = ""
