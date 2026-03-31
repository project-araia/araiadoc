---
name: get-from-titanv
description: Download documents from TitanV (S2ORC) database or perform an all-terms search using the climpdf tool.
---

# `get-from-titanv` Skill

Download documents from the S2ORC (Semantic Scholar Open Research Corpus) database (hosted on the ARAIA project's TitanV server) by corpus ID, or perform a comprehensive "all terms" search covering multiple climate-related queries.

## Usage

```bash
pixi run -e climpdf climpdf get-from-titanv [OPTIONS]
```

### Options

| Flag | Short | Description |
|------|-------|-------------|
| `--source PATH` | `-s` | Input dataset containing corpus IDs (CSV or JSON file) |
| `--all-terms` | `-a` | Perform the pre-defined "all terms" climate search |
| `--output-dir PATH` | `-o` | Existing or new output directory (resumes from checkpoint if directory exists) |

## Examples

- Download documents using corpus IDs from a JSON file:
  ```bash
  pixi run -e climpdf climpdf get-from-titanv --source data/corpus_ids.json
  ```

- Download documents from a CSV file (with header row):
  ```bash
  pixi run -e climpdf climpdf get-from-titanv --source data/papers.csv
  ```

- Perform an all-terms climate search:
  ```bash
  pixi run -e climpdf climpdf get-from-titanv --all-terms
  ```

- Resume an all-terms search from checkpoint:
  ```bash
  pixi run -e climpdf climpdf get-from-titanv --all-terms --output-dir data/titanv_all_terms_results_v2_2024-01-15/
  ```

## All Terms Search Coverage

The `--all-terms` option queries for documents matching climate-related terms including:

- **Temperature extremes**: heat wave, cold wave, urban heat island, wet-bulb temperature
- **Precipitation**: flood, drought, flash flood, extreme rainfall, storm surge
- **Storms**: hurricane, typhoon, tornado, thunderstorm, blizzard, derecho
- **Climate impacts**: sea level rise, permafrost thaw, ocean acidification, wildfire
- **Cross-cutting**: climate, weather, hazard, resilience, adaptation, vulnerability

## How It Works

### By Source File

1. Reads corpus IDs from input CSV (column index 6) or JSON (array of IDs)
2. Splits work into 8 concurrent chunks
3. Queries TitanV Solr API for each corpus ID
4. Saves responses as JSON files per document
5. Maintains checkpoint to resume interrupted runs

### All Terms Mode

1. Uses cursor-based pagination on Solr to iterate through all matching documents
2. Downloads in batches of 1000 documents
3. Flushes to gzip-compressed JSONL files every 50 pages
4. Creates checkpoint for resumable downloads
5. Writes corpus IDs to `ids.txt`

## Output

### Source Mode
- **Location**: `data/titanv_id_results_v2/`
- **Format**: JSON files per document
- **Checkpoint**: `data/titanv_checkpoint.json`

### All Terms Mode
- **Location**: `{OUTPUT_DIR}/all_terms/`
- **Files**:
  - `batches/batch_000001.jsonl.gz` - Gzipped JSONL with document data
  - `ids.txt` - List of corpus IDs
  - `checkpoint.json` - Resume state (cursor mark, page index)

## Notes

- Rate limited to 180 requests per second
- 5-second timeout per individual request
- All terms search uses 120-second timeout per page
- Automatically resumes from checkpoint files
- Requires network access to `titanv.gss.anl.gov:8983`
