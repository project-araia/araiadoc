# climpdfgetter

A large suite of tools and scripts for downloading and processing documents for the ARAIA project.

The primary utility is the `climpdf` command-line tool, with the following commands:

```bash
Usage: climpdf [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  complete-semantic-scholar  Download documents from Semantic Scholar that match a given input file containing document ID.
  convert                    Convert PDFs in a given directory ``source`` to json.
  count-local                Count the number of downloaded files from a given source. Creates a checkpoint file.
  count-remote-osti          Count potentially downloadable files from OSTI, for any number of search terms. Leave blank for all.
  crawl-epa                  Asynchronously crawl EPA result pages.
  crawl-osti                 Asynchronously crawl OSTI result pages.
  epa-ocr-to-json            Convert EPA's OCR fulltext to similar json format as internal schema.
  extract-refs               Extract references from JSON files in a directory.
  get-from-titanv            Download from TitanV database or perform an all-terms search.
  get-metadata-from-database Grabs metadata from a postgresql database.
  section-dataset            Preprocess full-text files in s2orc/pes2o format into headers and subsections.
  section-dataset-v2         Preprocess full-text files into header:paragraph JSON dictionaries.
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

### Complete Semantic Scholar

```bash
Usage: climpdf complete-semantic-scholar [OPTIONS] INPUT_FILE

Options:
  -i, --input_format [csv|checkpoint|pes2o|combined]
  -m, --input_metadata_file PATH
  -o, --output_format [metadata|pdf|combined]
  -n, -nproc INTEGER
```

Given an input file containing Semantic Scholar corpus IDs, this command downloads documents. Supports CSV files with columns (`lineno`, `abstract`, `score`, `year`, `field`, `title`, `paper_id`, `authors`), `.json` checkpoint files, or pes2o directories.

For instance:

```climpdf complete-semantic-scholar paper_ids.csv```
```climpdf complete-semantic-scholar corpus_ids.json --input_format checkpoint```

### Convert documents

```bash
Usage: climpdf convert [OPTIONS] SOURCE

Options:
  -i, --images-tables
  -o, --output-dir TEXT
  -g, --grobid_service TEXT
```

Converts PDFs in a given directory to JSON. Non-PDF documents (png, tiff, etc.) are first converted to PDF. Extracts text using [Grobid](https://github.com/kermitt2/grobid) or [Open Parse](https://github.com/Filimoa/open-parse). Optionally extracts images and tables using [Layout Parser](https://github.com/Layout-Parser/layout-parser).

For instance:

```climpdf convert data/EPA_2024-12-18_15:09:27```
```climpdf convert data/EPA_2024-12-18_15:09:27 --grobid_service http://localhost:8080```

### Count downloaded files

```bash
Usage: climpdf count-local SOURCE
```

Counts the number of downloaded files from a given source. Directories prefixed with `SOURCE` are assumed to contain downloaded files. Also creates a `SOURCE_docs_ids.json` checkpoint file.

```climpdf count-local EPA```
```climpdf count-local OSTI```

### Count remote OSTI results

```bash
Usage: climpdf count-remote-osti [OPTIONS] START_YEAR STOP_YEAR

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Counts potentially downloadable files from OSTI for any number of search terms. Helps adjust year ranges before crawling.

```climpdf count-remote-osti 2010 2025```
```climpdf count-remote-osti 2000 2025 -t "Heat Waves" -t Tornado```

### Crawl EPA

```bash
Usage: climpdf crawl-epa START_IDX STOP_IDX

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Asynchronously crawls EPA result pages. Specify the stop and start index out of search results, then any number of search terms.

```climpdf crawl-epa 100 0 -t Flooding```

### Crawl OSTI

```bash
Usage: climpdf crawl-osti START_YEAR

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Asynchronously crawls OSTI result pages. Specify the start year range for document publishing, then any number of `-t <term>`. OSTI limits results to 1000 per term.

```climpdf crawl-osti 2010 2025 -t Blizzard -t Tornado -t "Heat Waves"```

Use `climpdf count-remote-osti` to help adjust year ranges. Run `climpdf count-local OSTI` between searches to update the checkpoint file and prevent downloading duplicates.

### EPA OCR to JSON

```bash
Usage: climpdf epa-ocr-to-json SOURCE
```

Converts EPA's OCR fulltext to similar JSON format as internal schema.

```climpdf epa-ocr-to-json data/EPA_ocr_output```

### Extract references

```bash
Usage: climpdf extract-refs DIRECTORY
```

Extracts references from JSON files in a directory. Looks for files matching `*_processed.json`.

```climpdf extract-refs data/processed_documents```

### Get from TitanV

```bash
Usage: climpdf get-from-titanv [OPTIONS]

Options:
  -s, --source PATH        Input dataset containing corpus IDs
  -a, --all-terms          Perform an all-terms search
  -o, --output-dir PATH    Optional output directory (resumes from checkpoint)
```

Downloads from TitanV database or performs an all-terms search. Use one option at a time.

```climpdf get-from-titanv --all-terms```
```climpdf get-from-titanv --source data/corpus_ids.json```

### Get metadata from database

```bash
Usage: climpdf get-metadata-from-database SOURCE_DIR DBNAME USER PASSWORD HOST PORT TABLE_NAME
```

Associates metadata with documents from a PostgreSQL database. Entries matching the JSON schema below are expected.

```climpdf get-metadata-from-database data/OSTI_documents mydb myuser mypass localhost 5432 metadata_table```

### Get metadata from Semantic Scholar

```bash
Usage: climpdf get-metadata-from-semanticscholar SOURCE_DIR
```

Associates metadata with documents from Semantic Scholar.

```climpdf get-metadata-from-semanticscholar data/OSTI_documents```

### Sectionize dataset

```bash
Usage: climpdf section-dataset SOURCE
```

Preprocesses full-text files in s2orc/Grobid format into headers and subsections. Scans for titles, headers, and associated subsections. Rejects headers that are too short/long, non-English, or contain special characters.

```climpdf section-dataset data/OSTI_2024-12-18_15:09:27```

### Sectionize dataset v2

```bash
Usage: climpdf section-dataset-v2 SOURCE
```

Preprocesses full-text files into header:paragraph JSON dictionaries. Supports both legacy per-document JSON files and batched JSONL.GZ output.

```climpdf section-dataset-v2 data/all_terms/batches```

### Agent Skills

Agent Skills are available in the `.agents/skills` directory. Supported skills include:
  - `crawl_epa`: Crawl EPA result pages
  - `crawl_osti`: Crawl OSTI result pages
  - `get_metadata_from_database`: Get metadata from database
  - `get_from_titanv`: Download from TitanV (S2ORC) database
  - `sectionize_dataset_v2`: Sectionize dataset v2

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
