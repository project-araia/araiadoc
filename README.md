# climpdfgetter

A large suite of tools and scripts for downloading and processing documents for the ARAIA project.

The primary utility is the `climpdf` command-line tool, with the following commands:

```bash
Usage: climpdf [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  convert                    Convert PDFs in a given directory ``source`` to json.
  count-local                Count the number of downloaded files from a given source. Creates a checkpoint file.
  count-remote-osti          Count potentially downloadable files from OSTI, for any number of search terms. Leave blank for all.
  crawl-epa                  Asynchronously crawl EPA result pages.
  crawl-osti                 Asynchronously crawl OSTI result pages.
  complete-semantic-scholar  Download documents from Semantic Scholar that match a given input file containing document ID.
  epa-ocr-to-json            Convert EPA's OCR fulltext to similar json format as internal schema.
  section-dataset            Preprocess full-text files in s2orc/pes2o format into headers and subsections.
  get-metadata-from-database Grabs metadata from a postgresql database.
```

These will be described in more detail below.

The `scripts` directory contains additional tools for associating metadata with documents and for updating checkpoint files.

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
any number of `-t <term>`. For instance:

```climpdf crawl-osti 2010 2025 -t Blizzard -t Tornado -t "Heat Waves"```

Notes:
- OSTI limits search results to 1000 for each term.
Use ```climpdf count-remote-osti [OPTIONS] START_YEAR STOP_YEAR``` to help adjust year ranges.
- Corresponding metadata is also downloaded.
- Run ```climpdf count-local OSTI``` between searches to determine the number of documents downloaded from OSTI, *and* update the local
checkpoint file. The checkpoint prevents downloading duplicates.

#### EPA [Needs maintenance]

```Usage: climpdf crawl-epa [OPTIONS] STOP_IDX START_IDX```

Specify the *stop index* and *start index* out of the search results, then any
number of `-t <term>`, for instance:

```climpdf crawl-epa 100 0 -t Flooding```


### Counting results

```Usage: climpdf count-local [OPTIONS] SOURCE```

Specify a source to count the number of downloaded files. Directories prefixed with `SOURCE` are
assumed to contain downloaded files corresponding to that source.

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
  2. Extract text using [Grobid - recommended](https://github.com/kermitt2/grobid) or [Open Parse](https://github.com/Filimoa/open-parse).
  3. [In active development] Extract images and tables from text using [Layout Parser](https://github.com/Layout-Parser/layout-parser)
  4. Dump text to `<output_dir>.json`.
  5. If 3. is enabled, save tables and images to a per-document directory.

For instance:

```climpdf convert data/EPA_2024-12-18_15:09:27``` or
```climpdf convert data/EPA_2024-12-18_15:09:27 --grobid_service http://localhost:8080```.

Eligible documents are collected from subdirectories.

Problematic documents are noted as-such for future conversion attempts.

### Sectionizing

```bash
Usage: climpdf section-dataset [OPTIONS] SOURCE

  Preprocess full-text files in s2orc/grobid format into headers and subsections.

```

This utility scans a directory for files presumably in the [s2orc](https://github.com/allenai/s2orc) format;
that have been processed by [Grobid](https://github.com/kermitt2/grobid) as the original authors of `s2orc` did, and like
`climpdf convert --grobid_service`.

For instance:

```climpdf section-dataset data/OSTI_2024-12-18_15:09:27```

The parsed documents are scanned for titles, headers, and associated subsections. A heuristic rejects headers and subsections
that are too short, too long, aren't english, and/or contain too many special characters.

Additional subsections and headers are rejected if they likely don't correspond with natural language text. For instance,
ASCII-representations of tables are rejected.

Fields without referenceable content like ``"author affiliations"``, ``"disclaimer"``, ``"acknowledgements"``, and
others are rejected.

The resulting output is a dictionary containing relevant headers as keys and subsections as values.

### Metadata association


```bash
Usage: climpdf get-metadata-from-database [OPTIONS] SOURCE

  Grabs metadata from a postgresql database.
```

Given a directory of documents, this utility will attempt to associate metadata with each document from a postgresql database.

For instance:

```climpdf get-metadata-from-database data/OSTI_2024-12-18_15:09:27 db_name db_user db_password hostname.addr.io 5432 table_name```

Metadata entries matching the below schema are expected to be found in the database. The document contents are set to the "text" field of
the below schema.

#### JSON Schema

```python
class ParsedDocumentSchema(BaseModel):
    source: str = ""
    title: str = ""
    text: dict[str, str] = {}  # keys are section headings, values are text
    abstract: str = ""
    authors: list[str] | str = []
    publisher: str = ""
    date: int | str = 0
    unique_id: str = ""
    doi: str = ""
    references: str = ""
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
