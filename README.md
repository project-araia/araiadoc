# climpdfgetter

A large suite of tools and scripts for downloading and processing documents for the ARAIA project.

The primary utility is the `climpdf` command-line tool, with the following commands:

```bash
Usage: climpdf [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  convert            Convert PDFs in a given directory ``source`` to json.
  count-local        Count the number of downloaded files from a given...
  count-remote-osti  Count potentially downloadable files from OSTI, for...
  crawl-epa          Asynchronously crawl EPA result pages:
  crawl-osti         Asynchronously crawl OSTI result pages:
  epa-ocr-to-json    Convert EPA's OCR fulltext to similar json format as...
  section-dataset    Preprocess full-text files in s2orc/pes2o format.
```

These will be described in more detail below.

The `scripts` directory contains additional tools for associating metadata with documents, and for updating checkpoint files.

## Installation

```bash
git clone https://github.com/project-araia/climpdfgetter.git
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
- Run ```climpdf count-local OSTI``` between searches to determine the number of documents downloaded from OSTI, *and* update the local
checkpoint file. The checkpoint prevents downloading duplicates.

#### EPA

```Usage: climpdf crawl-epa [OPTIONS] STOP_IDX START_IDX```

Specify the *stop index* and *start index* out of the search results, then any
number of `-t <term>`, for instance:

```climpdf crawl-epa 100 0 -t Flooding```


### Counting results

```Usage: climpdf count-local [OPTIONS] SOURCE```

Specify a source to count the number of downloaded files.
Also creates a ```SOURCE_docs_ids.json``` in the data directory.
This file is treated as a checkpoint file, and is referenced by ```climpdf crawl-osti``` and ```climpdf crawl-epa```.

For instance:

````bash
$ climpdf count-local EPA
2342
````

### Document conversion

```bash
Usage: climpdf convert [OPTIONS] SOURCE

  Convert PDFs in a given directory ``source`` to json. If the input files are
  of a different format, they'll first be converted to PDF.

Options:
  -i, --images-tables
  -o, --output-dir TEXT
  -g, --grobid_service TEXT
```

Collects downloaded files in a given directory and:
  1. Convert non-PDF documents to PDF if eligible (png, tiff, etc.).
  2. Extract text using [Open Parse](https://github.com/Filimoa/open-parse).
  3. [In active development] Extract images and tables from text using [Layout Parser](https://github.com/Layout-Parser/layout-parser)
  4. Format text with headers as keys, and their subsections as values.
  5. Concatenate text together with metadata in the below schema and dump.
  6. Save tables and images to a per-document directory.

For instance:

```climpdf convert data/EPA_2024-12-18_15:09:27```

or:

```climpdf convert data --images```

Eligible documents and metadata are concatenated from subdirectories.

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

- [openparse](https://github.com/Filimoa/open-parse) for text-extraction and formatting.
