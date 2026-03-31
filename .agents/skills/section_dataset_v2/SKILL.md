---
name: section-dataset-v2
description: Sectionize documents into header:paragraph JSON dictionaries using the climpdf tool.
---

# `section-dataset-v2` Skill

Preprocess full-text documents into structured header:paragraph JSON dictionaries. Supports both individual JSON files and batched JSONL.GZ files from TitanV downloads. Extracts and organizes content by section headers.

## Usage

```bash
pixi run -e climpdf climpdf section-dataset-v2 [OPTIONS] SOURCE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SOURCE` | Directory containing documents to sectionize |

### Options

| Flag | Description |
|------|-------------|
| `--dump_rejected` | Dump rejected sections to a separate file (default: False) |

## Examples

- Sectionize a directory of individual JSON files:
  ```bash
  pixi run -e climpdf climpdf section-dataset-v2 data/titanv_documents
  ```

- Process TitanV batch output (JSONL.GZ files):
  ```bash
  pixi run -e climpdf climpdf section-dataset-v2 data/titanv_all_terms_results
  ```

- Sectionize with rejected sections dump:
  ```bash
  pixi run -e climpdf climpdf section-dataset-v2 data/documents --dump_rejected
  ```

## Input Format

The tool accepts two input formats:

### 1. Legacy Per-Document JSON
```
data/documents/
  corpus_123.json
  corpus_456.json
```
Each file contains one document with fields: `abstract`, `paragraph` (list), `title`, `sectionheader` (list)

### 2. Batched JSONL.GZ (from TitanV)
```
data/titanv_results/
  all_terms/
    batches/
      batch_000001.jsonl.gz
      batch_000002.jsonl.gz
```

## How It Works

1. **Detects input format**: Checks for `.jsonl.gz` batch files or legacy JSON files
2. **Extracts corpus ID**: From document field or filename fallback
3. **Normalizes headers**: Cleans whitespace, removes noise patterns
4. **Filters content**:
   - Removes: acknowledgments, references, funding, ethics statements
   - Stops at: conclusions, abbreviations
   - Keeps: introduction, methods, results, discussion, etc.
5. **Validates content**: Ensures sufficient alpha characters and valid text
6. **Language detection**: Filters out non-English content using langdetect

## Section Processing Rules

### Sections That Stop Processing
- `conclusion` - Processing ends after this section

### Sections That Are Skipped But Continue
- `abstract`, `caption`, `figure`, `table` - Skipped but don't stop

### Sections That Terminate Processing
- `acknowledgment`, `reference`, `bibliography`, `funding`
- `dataavailability`, `codeavailability`, `appendix`
- `disclosurestatement`, `conflictsofinterest`

## Output

- **Location**: `{SOURCE}_sectionized/`
- **Format**: JSON files with header:content key-value pairs
- **Checkpoint**: `batch_checkpoint.json` for resumable processing

### Example Output
```json
{
  "title": "Document Title",
  "abstract": "This study examines...",
  "Introduction": "Previous research has shown...",
  "Methods": "We analyzed data from...",
  "Results": "Our findings indicate...",
  "Discussion": "These results suggest..."
}
```

## Notes

- Parallel processing using all available CPU cores
- Automatically skips existing output files (idempotent)
- Maintains batch checkpoint for interrupted runs
- Filters out content with >30% numeric/special characters
- Requires minimum 40 characters and 20 alpha characters per section
- Batch mode streams gzipped files line-by-line (memory efficient)
