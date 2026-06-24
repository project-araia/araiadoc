# Processing & Ingestion

Once documents are collected or downloaded, they undergo conversion, filtering, sectionization, and relevance assessment.

---

## Document Schema

The target internal schema for processed full-text documents is represented by `ParsedDocumentSchema`:

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

---

## PDF Conversion & Ingestion

### Standard Conversion

Converts PDF, PNG, and TIFF documents into schema-conforming JSON structure using **Grobid** or **Open Parse**.

```bash
araiadoc convert SOURCE [OPTIONS]
```

- **Options:**
  - `-o, --output-dir TEXT`: Destination directory.
  - `-g, --grobid_service TEXT`: URL of the Grobid service (e.g. `http://localhost:8080`).

**Example:**
```bash
araiadoc convert data/EPA_downloads --grobid_service http://localhost:8080
```

### EPA OCR conversion

Converts EPA's OCR full-text outputs into our internal JSON schema format.

```bash
araiadoc epa-ocr-to-json SOURCE_DIR
```

---

## Pre-Sectionization Filtering

Before dividing a dataset into individual sections, we can filter out unrelated documents based on title, abstract, or body-text regex matches. This generates a clean, filtered copy of the source files.

```bash
araiadoc filter-dataset SOURCE [OPTIONS]
```

- **Options:**
  - `--file FILE`: Path to `.txt` file containing one regex pattern per line.
  - `--patterns TEXT`: Comma-separated regex patterns.
  - `-o, --output-dir PATH`: Filtered copy destination (defaults to `SOURCE_filtered`).

**Example:**
```bash
araiadoc filter-dataset data/s2orc_v2_shards --file data/filter.txt
```

---

## Sectionization

Sectionizers split parsed document full-text strings into dictionary key-value pairs mapping canonical section headers to paragraph texts.

### s2orc_v2 Sectionizer (Recommended)

Operates on Semantic Scholar `s2orc_v2` bulk shards or extracted per-document directories.

```bash
araiadoc section-dataset-s2orc SOURCE [OPTIONS]
```

- **Options:**
  - `--detailed-report`: Log individual section metadata (header, char count, paragraphs, keep/drop outcome) inside `sectionization_report.jsonl.gz`.
  - `--exclude-patterns TEXT` / `--exclude-file PATH`: Exclude records with regex matching titles or body text prior to splitting.

#### s2orc_v2 Schema Gotchas

- **JSON Span Offsets:** `doc["body"]["text"]` is a flat string. Paragraph boundaries and section headers are defined by lists of JSON-encoded coordinate spans (`["body"]["annotations"]["paragraph"]` and `["section_header"]`). These coordinates are sorted by `start` offset.
- **Abstract Promotion:** The dataset contains no dedicated `abstract` key; any paragraphs located prior to the very first `section_header` span are promoted to the `abstract` field.
- **Section Assignment:** Paragraphs are assigned to the most recent preceding header whose `end` offset is less than or equal to the paragraph's `start` offset.

### Legacy Sectionizers

- `section-dataset`: Basic header and subsection scanner.
- `section-dataset-v2`: Tailored for legacy Solr/TitanV schemas where section headers and paragraph arrays were flattened, making section assignment fragile. Keep intact for legacy workflows only.

---

## Agentic Relevance Judgment

Use OpenAI-compatible models (or ALCF Sophia/vLLM endpoints) to judge the relevance of sectionized document corpora against custom prompt rubrics.

```bash
araiadoc agentic-judge-dataset SOURCE --prompt PROMPT_FILE [OPTIONS]
```

- **Options:**
  - `--model TEXT`: Model name.
  - `--base-url TEXT`: Target API endpoint base URL.
  - `--api-key TEXT`: API auth key (can also be read from `OPENAI_API_KEY` or `API_KEY`).
  - `--mode [requests|provider-batch]`: Bounded concurrent direct API requests or asynchronous provider-side bulk batching.
  - `--concurrency INTEGER`: Local request concurrency level (defaults to `4`).
  - `--dry-run`: Renders and prints sample prompts to stdout without submitting calls to the model endpoint.
  - `--copy-kept`: Copies kept documents into `OUTPUT_DIR/kept/`.

**Example:**
```bash
araiadoc agentic-judge-dataset data/all_weather_sectionized \
  --prompt prompts/weather_utility.md \
  --concurrency 4
```
