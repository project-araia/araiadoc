---
name: get_from_titanv
description: Download documents from TitanV (S2ORC) database or perform an all-terms search using the araiadoc tool.
---

# `get-from-titanv` Skill

Download documents from the S2ORC (Semantic Scholar Open Research Corpus) database (hosted on the ARAIA project's TitanV server) by corpus ID, or perform a comprehensive pre-defined search covering climate-weather or utility/electricity queries.

## Usage

```bash
pixi run -e araiadoc araiadoc get-from-titanv [OPTIONS]
```

### Options

| Flag | Short | Description |
|------|-------|-------------|
| `--source PATH` | `-s` | Input dataset containing corpus IDs (CSV or JSON file) |
| `--all-weather` | `-a` | Perform the pre-defined weather/climate Solr search |
| `--all-utility` | `-u` | Perform the pre-defined utility/electricity Solr search |
| `--ids-only` | `-i` | Only download matching `corpus_id`s (no full documents). Requires `--all-weather` or `--all-utility`; cannot be combined with `--source`. |
| `--output-dir PATH` | `-o` | Existing or new output directory (resumes from checkpoint if directory exists) |

Use **one option at a time** — `--source`, `--all-weather`, or `--all-utility`.

`--ids-only` is a modifier for the weather/utility search modes. When set, only the `corpus_id` field is fetched from Solr (via `fl=corpus_id`), no `batches/*.jsonl.gz` files are written, and the output goes to a separate `<search_name>_ids/` subdirectory so its checkpoint cannot be confused with a full-document run.

**Note**: the `_ids` suffix is appended to the inner `<search_name>` subdirectory *unconditionally* in ids-only mode — even when `--output-dir` is explicitly supplied. So `--all-weather --ids-only --output-dir data/my_run/` writes to `data/my_run/all_weather_ids/`, **not** `data/my_run/all_weather/`. This is intentional and prevents an ids-only checkpoint from being mistaken for a completed full-document run when the same `--output-dir` is reused across modes.

## Examples

- Download documents using corpus IDs from a JSON file:
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --source data/corpus_ids.json
  ```

- Download documents from a CSV file (with header row):
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --source data/papers.csv
  ```

- Perform the pre-defined weather/climate search:
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --all-weather
  ```

- Perform the pre-defined utility/electricity search:
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --all-utility
  ```

- Resume a search from a specific checkpoint directory:
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --all-weather --output-dir data/titanv_all_weather_results_2024-01-15_12:00:00/
  ```

- Fetch only the matching corpus IDs (no document bodies):
  ```bash
  pixi run -e araiadoc araiadoc get-from-titanv --all-weather --ids-only
  pixi run -e araiadoc araiadoc get-from-titanv --all-utility --ids-only
  ```

## Search Coverage

### `--all-weather`
Queries for documents matching climate/weather terms including:
- **Temperature extremes**: heat wave, cold wave, urban heat island, wet-bulb temperature
- **Precipitation**: flood, drought, flash flood, extreme rainfall, storm surge
- **Storms**: hurricane, typhoon, tornado, thunderstorm, blizzard, derecho
- **Climate impacts**: sea level rise, permafrost thaw, ocean acidification, wildfire
- **Cross-cutting**: climate, weather, hazard, resilience, adaptation, vulnerability

### `--all-utility`
Queries for documents matching electricity/utility infrastructure terms, split across multiple Solr sub-queries (q2_chunks) to avoid HTTP 414 errors. Uses cached `fq` filter queries for performance.

## How It Works

### By Source File

1. Reads corpus IDs from input CSV (column index 6) or JSON (array of IDs)
2. Splits work into 8 concurrent chunks
3. Queries TitanV Solr API for each corpus ID
4. Saves responses as JSON files per document
5. Maintains checkpoint to resume interrupted runs

### Weather / Utility Search Mode

1. Uses cursor-based pagination on Solr to iterate through all matching documents
2. Downloads in batches of 500 documents per page
3. Flushes to gzip-compressed JSONL files every 50 pages
4. Creates per-chunk checkpoint files for resumable downloads
5. Writes corpus IDs to `ids.txt`
6. Deduplicates across sub-queries using a shared `seen_ids` set

## Output

### Source Mode
- **Location**: `data/titanv_id_results_v2_<timestamp>/`
- **Format**: JSON files per document (`<corpus_id>.json`)
- **Checkpoint**: `data/titanv_checkpoint.json`

### Weather / Utility Search Mode
- **Location**: `{OUTPUT_DIR}/all_weather/` or `{OUTPUT_DIR}/all_utility/`
- **Files**:
  - `batches/batch_c01_000001.jsonl.gz` — Gzipped JSONL with document data (one per chunk)
  - `ids.txt` — List of corpus IDs written so far
  - `checkpoint_1.json`, `checkpoint_2.json`, … — Resume state per sub-query chunk

### Weather / Utility Search Mode (`--ids-only`)
- **Location**: `data/titanv_all_weather_results_ids_<timestamp>/all_weather_ids/` (or `..._utility...`)
- **Files**:
  - `ids.txt` — List of corpus IDs written so far
  - `checkpoint_1.json`, `checkpoint_2.json`, … — Resume state per sub-query chunk
- No `batches/` directory is created.

## Notes

- Rate limited to 180 requests per second (source mode)
- 5-second timeout per individual corpus-ID request
- Weather/utility search uses 300-second timeout per cursor page
- Automatically resumes from checkpoint files
- Requires network access to `titanv.gss.anl.gov:8983`
