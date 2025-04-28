# climpdfgetter

Download and convert climate pdfs from EPA and OSTI.

## Installation

```bash
git clone https://git-out.gss.anl.gov/araia/climpdfgetter.git
cd climpdfgetter
```

Then either:

**Recommended**: Use [Pixi](https://pixi.sh/latest/) to take advantage of the included, guaranteed-working environment:

```bash
curl -fsSL https://pixi.sh/install.sh | sh
pixi shell -e climpdf
```

*Or*:

```bash
pip install -e .
```

Note that dependency resolution issues are much less likely with Pixi.

## Basic Usage

### Downloading documents

Multiple provided search terms are collected in parallel.

#### OSTI

```Usage: climpdf crawl-osti [OPTIONS] START_YEAR STOP_YEAR```

Specify the *start year* and *stop year* range for document publishing, then
any number of `-t <term>`, for instance:

```climpdf crawl-osti 2010 2025 -t Blizzard -t Tornado -t "Heat Waves"```

Notes:
- OSTI limits search results to 1000 for each term.
Use ```climpdf count-remote-osti [OPTIONS] START_YEAR STOP_YEAR``` to help adjust year ranges.
- Corresponding metadata is also downloaded.
- Run ```climpdf count-local OSTI``` between searches to avoid downloading already-collected documents.

#### EPA

```Usage: climpdf crawl-epa [OPTIONS] STOP_IDX START_IDX```

Specify the *stop index* and *start index* out of the search results, then any
number of `-t <term>`, for instance:

```climpdf crawl-epa 100 0 -t Flooding```


### Counting results

```Usage: climpdf count-local [OPTIONS] SOURCE```

Specify a source to count the number of downloaded files.
Also creates a ```SOURCE_docs_ids.json``` in the data directory.

For instance:

````bash
$ climpdf count-local EPA
2342
````

### Document conversion

```Usage: climpdf convert [OPTIONS] SOURCE```

Collects downloaded files in a given directory and:
  1. Convert non-PDF documents to PDF if eligible (png, tiff, etc.).
  2. Extract text, using either standard PDF text extraction or OCR as a fallback.
  3. Clean text of extraneous URLs, phone numbers, whitespace, etc.
  4. Match text with any collected corresponding metadata.
  5. Concatenate all information together in the below schema and dump.

For instance:

```climpdf convert data/EPA_2024-12-18_15:09:27```

or:

```climpdf convert data```

Problematic documents are noted as-such for future conversion attempts.

#### JSON Schema

```python
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
```

## Development

Development and package management is done with [Pixi](https://pixi.sh/latest/).

Enter the development environment with:

```pixi shell -e dev```

## Additional information

``climpdf`` uses:

- [crawl4ai](https://crawl4ai.com/mkdocs/) as its primary webcrawler
library. Downloads are at "human speeds" to try avoiding being blocked
or rate-limited.

- [pymupdf](https://pymupdf.readthedocs.io/en/latest/index.html) as its initial tool for extracting
text from PDFs.

- [pdf2json](https://github.com/nesar/pdf2json/), via [nougat](https://github.com/facebookresearch/nougat),
as its fallback OCR method if `pymupdf` doesn't work.
