# araiadoc

A large suite of tools and scripts for downloading and processing documents for the ARAIA project.

The primary utility is the `araiadoc` command-line tool, with the following commands:

```bash
Usage: araiadoc [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  complete-semantic-scholar  Download documents from Semantic Scholar that match a given input file containing document ID.
  convert                    Convert PDFs in a given directory ``source`` to json.
  count-local                Count the number of downloaded files from a given source. Creates a checkpoint file.
  count-remote-osti          Count potentially downloadable files from OSTI, for any number of search terms. Leave blank for all.
  crawl-epa                  Asynchronously crawl EPA result pages.
  crawl-osti                 Asynchronously crawl OSTI result pages.
  download-s2orc             Download Semantic Scholar's s2orc_v2 bulk dataset (~30 shards).
  epa-ocr-to-json            Convert EPA's OCR fulltext to similar json format as internal schema.
  get-from-local-s2orc       Query a local s2orc_v2 download by corpus-ID list, full-text keyword, or pre-defined search.
  get-from-titanv            Download from TitanV database or perform a pre-defined search (legacy; prefer get-from-local-s2orc).
  get-metadata-from-database Grabs metadata from a postgresql database.
  get-metadata-from-semanticscholar  Packages pre-fetched Semantic Scholar metadata into output files.
  section-dataset            Preprocess full-text files in s2orc/pes2o format into headers and subsections.
  section-dataset-v2         Preprocess full-text files into header:paragraph JSON dictionaries (legacy TitanV/Solr schema).
  section-dataset-s2orc      Sectionize s2orc_v2 documents (raw .gz shards or per-document JSON) using span annotations.
  verify-sectionization      Round-trip audit: sample sectionized outputs and verify against raw input.
```

These will be described in more detail below.

The `scripts` directory contains additional tools for associating metadata with documents and for updating checkpoint files.

## Installation

```bash
git clone https://github.com/project-araia/araiadoc.git
cd araiadoc
```

Then either:

**Recommended**: Use [Pixi](https://pixi.sh/latest/) to take advantage of the included, guaranteed-working environment:

```bash
curl -fsSL https://pixi.sh/install.sh | sh
pixi shell -e araiadoc
```

*Or*:

```bash
pip install -e .
```

Note that dependency resolution issues are much less likely with Pixi.

## Basic Usage

### Complete Semantic Scholar

```bash
Usage: araiadoc complete-semantic-scholar [OPTIONS] INPUT_FILE

Options:
  -i, --input_format [csv|checkpoint|pes2o|combined]
  -m, --input_metadata_file PATH
  -o, --output_format [metadata|pdf|combined]
  -n, -nproc INTEGER
```

Given an input file containing Semantic Scholar corpus IDs, this command downloads documents. Supports CSV files with columns (`lineno`, `abstract`, `score`, `year`, `field`, `title`, `paper_id`, `authors`), `.json` checkpoint files, or pes2o directories.

For instance:

```araiadoc complete-semantic-scholar paper_ids.csv```
```araiadoc complete-semantic-scholar corpus_ids.json --input_format checkpoint```

### Convert documents

```bash
Usage: araiadoc convert [OPTIONS] SOURCE

Options:
  -o, --output-dir TEXT
  -g, --grobid_service TEXT
```

Converts PDFs in a given directory to JSON. Non-PDF documents (png, tiff, etc.) are first converted to PDF. Extracts text using [Grobid](https://github.com/kermitt2/grobid) or [Open Parse](https://github.com/Filimoa/open-parse). Optionally extracts images and tables using [Layout Parser](https://github.com/Layout-Parser/layout-parser).

For instance:

```araiadoc convert data/EPA_2024-12-18_15:09:27```
```araiadoc convert data/EPA_2024-12-18_15:09:27 --grobid_service http://localhost:8080```

### Count downloaded files

```bash
Usage: araiadoc count-local SOURCE
```

Counts the number of downloaded files from a given source. Directories prefixed with `SOURCE` are assumed to contain downloaded files. Also creates a `SOURCE_docs_ids.json` checkpoint file.

```araiadoc count-local EPA```
```araiadoc count-local OSTI```

### Count remote OSTI results

```bash
Usage: araiadoc count-remote-osti [OPTIONS] START_YEAR STOP_YEAR

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Counts potentially downloadable files from OSTI for any number of search terms. Helps adjust year ranges before crawling.

```araiadoc count-remote-osti 2010 2025```
```araiadoc count-remote-osti 2000 2025 -t "Heat Waves" -t Tornado```

### Crawl EPA

```bash
Usage: araiadoc crawl-epa START_IDX STOP_IDX

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Asynchronously crawls EPA result pages. Specify the stop and start index out of search results, then any number of search terms.

```araiadoc crawl-epa 0 100 -t Flooding```

### Crawl OSTI

```bash
Usage: araiadoc crawl-osti START_YEAR

Options:
  -t, --search-term TEXT  (multiple allowed)
```

Asynchronously crawls OSTI result pages. Specify the start year range for document publishing, then any number of `-t <term>`. OSTI limits results to 1000 per term.

```araiadoc crawl-osti 2010 -t Blizzard -t Tornado -t "Heat Waves"```

Use `araiadoc count-remote-osti` to help adjust year ranges. Run `araiadoc count-local OSTI` between searches to update the checkpoint file and prevent downloading duplicates.

### EPA OCR to JSON

```bash
Usage: araiadoc epa-ocr-to-json SOURCE
```

Converts EPA's OCR fulltext to similar JSON format as internal schema.

```araiadoc epa-ocr-to-json data/EPA_ocr_output```

### Get from TitanV

```bash
Usage: araiadoc get-from-titanv [OPTIONS]

Options:
  -s, --source PATH        Input dataset containing corpus IDs (CSV or JSON)
  -a, --all-weather        Perform the pre-defined weather/climate search
  -u, --all-utility        Perform the pre-defined utility/electricity search
  -o, --output-dir PATH    Optional output directory (resumes from checkpoint)
```

Downloads from TitanV database or performs a pre-defined search. Use one option at a time.

```araiadoc get-from-titanv --all-weather```
```araiadoc get-from-titanv --all-utility```
```araiadoc get-from-titanv --source data/corpus_ids.json```

### Get metadata from database

```bash
Usage: araiadoc get-metadata-from-database SOURCE_DIR DBNAME USER PASSWORD HOST PORT TABLE_NAME
```

Associates metadata with documents from a PostgreSQL database. Entries matching the JSON schema below are expected.

```araiadoc get-metadata-from-database data/OSTI_documents mydb myuser mypass localhost 5432 metadata_table```

### Get metadata from Semantic Scholar

```bash
Usage: araiadoc get-metadata-from-semanticscholar SOURCE_DIR
```

Associates metadata with documents from Semantic Scholar.

```araiadoc get-metadata-from-semanticscholar data/OSTI_documents```

### Sectionize dataset

```bash
Usage: araiadoc section-dataset SOURCE
```

Preprocesses full-text files in s2orc/Grobid format into headers and subsections. Scans for titles, headers, and associated subsections. Rejects headers that are too short/long, non-English, or contain special characters.

```araiadoc section-dataset data/OSTI_2024-12-18_15:09:27```

### Sectionize dataset v2

```bash
Usage: araiadoc section-dataset-v2 [OPTIONS] SOURCE

Options:
  --detailed-report       Capture per-section detail in sectionization_report.jsonl.gz.
  --exclude-patterns TEXT  Comma-separated regex patterns. Documents matching ANY pattern
                          in title, abstract, or body text are excluded before sectionization.
  --exclude-file PATH     Path to .txt file with one regex pattern per line. Empty lines
                          and lines starting with # are ignored.
```

Preprocesses full-text files into header:paragraph JSON dictionaries. Supports both legacy per-document JSON files and batched JSONL.GZ output. Built for the TitanV/Solr schema — for new work prefer `section-dataset-s2orc`.

When `--exclude-patterns` or `--exclude-file` is used, the `sectionization_report.jsonl.gz` includes which specific pattern(s) matched in the `error` field of excluded documents (e.g. `"Excluded by pattern(s): nanoparticle synthesis, quantum dot"`).

```araiadoc section-dataset-v2 data/all_terms/batches```
```araiadoc section-dataset-v2 data/all_terms/batches --exclude-file data/filter.txt```

### Sectionize dataset s2orc

```bash
Usage: araiadoc section-dataset-s2orc [OPTIONS] SOURCE

Options:
  --detailed-report       Capture per-section detail in sectionization_report.jsonl.gz.
  --exclude-patterns TEXT  Comma-separated regex patterns. Documents matching ANY pattern
                          in title or body text are excluded before sectionization.
  --exclude-file PATH     Path to .txt file with one regex pattern per line. Empty lines
                          and lines starting with # are ignored.
```

Sectionizes s2orc_v2 documents using span-annotation offsets in `body.text`. `SOURCE` may be a directory of `.gz` JSONL shards (from `download-s2orc`) or a directory of per-document `.json` files (from `get-from-local-s2orc`). v1-shape records (with `content.text` and `sectionheader`) are normalized to v2 transparently. Resumable via `batch_checkpoint.json`.

Every run writes `sectionization_report.json` (corpus aggregates) and `sectionization_report.jsonl.gz` (per-doc rows). With `--detailed-report`, each per-doc row also carries a `sections` array (header, chars, paragraphs, outcome) — roughly doubles row size, off by default.

With `--exclude-patterns` or `--exclude-file`, excluded documents report which pattern(s) matched in their `error` field.

```araiadoc section-dataset-s2orc data/s2orc_v2_shards```
```araiadoc section-dataset-s2orc data/all_weather --detailed-report```
```araiadoc section-dataset-s2orc data/s2orc_v2_shards --exclude-file data/filter.txt```

### Verify sectionization

```bash
Usage: araiadoc verify-sectionization [OPTIONS] RAW_DIR SECT_DIR

Options:
  -n, --sample INTEGER         Sample size; 0 = all docs.  [default: 1000]
  --seed INTEGER               RNG seed for reproducible sampling.  [default: 0]
  --report-json PATH           Write a JSON audit report to this path.
  --include-docs               Include per-document detail (including title) in --report-json output.
  --fail-threshold FLOAT       Exit nonzero if corpus content loss % exceeds this.
  --exclude-patterns TEXT      Comma-separated regex patterns used during sectionization.
  --exclude-file PATH          Path to .txt file with one regex pattern per line.
```

Round-trip audit that reads written sectionized JSON back from disk, reconstructs ground-truth section bounds directly from raw span annotations, and verifies each section's first-paragraph 50-char probe survived to disk. Missing sections are attributed to the same drop reasons the production sectionizer would have used. Catches a class of bugs the internal `sectionization_report.json` cannot — silent overwrites on duplicate canonical headers, output truncation, encoding mangling.

When `--exclude-patterns` or `--exclude-file` is supplied and a document has no sectionized output file, the verifier re-applies the patterns against the raw document's title and body text. Documents that match any pattern are attributed to `excluded_by_pattern` (separate from `skipped_missing_sect`) and each matching pattern is tallied individually. The summary table includes an `Excluded by pattern` row, and an `Excluded-by-pattern breakdown` table lists which patterns excluded how many documents. This information also appears in the JSON report under `excluded_by_pattern` (count) and `excluded_by_pattern_reasons` (pattern → count dict).

```araiadoc verify-sectionization data/s2orc_v2_shards data/s2orc_v2_shards_sectionized```
```araiadoc verify-sectionization raw/ sectionized/ -n 5000 --report-json audit.json --fail-threshold 5.0```
```araiadoc verify-sectionization raw/ sectionized/ --exclude-file data/filter.txt```

### Agent Skills

Agent Skills are available in the `.agents/skills` directory. Supported skills include:
  - `crawl_epa`: Crawl EPA result pages
  - `crawl_osti`: Crawl OSTI result pages
  - `get_from_titanv`: Download from TitanV (S2ORC) database
  - `section_dataset_v2`: Sectionize dataset v2
  - `section_dataset_s2orc`: Sectionize s2orc_v2 documents from span annotations
  - `araia_review`: Review a sectionized corpus against its generating Solr query
  - `araia_compare`: Compare two sectionized corpora for overlap / drift

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

``araiadoc`` uses:

- [crawl4ai](https://crawl4ai.com/mkdocs/) as its primary webcrawler
library. Downloads are at "human speeds" to try avoiding being blocked
or rate-limited.

- [openparse](https://github.com/Filimoa/open-parse) for text-extraction and formatting.
