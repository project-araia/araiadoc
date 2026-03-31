---
name: crawl-epa
description: Asynchronously crawl EPA NEPIS document result pages using the climpdf tool.
---

# `crawl-epa` Skill

Asynchronously crawl the EPA NEPIS (National Environmental Publications Information System) database for documents matching specified search terms. Downloads unformatted OCR text documents and stores them in timestamped output directories.

## Usage

```bash
pixi run -e climpdf climpdf crawl-epa [OPTIONS] START_IDX STOP_IDX
```

### Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `START_IDX` | integer | The starting document index (0-based) |
| `STOP_IDX` | integer | The ending document index (exclusive) |

### Options

| Flag | Description |
|------|-------------|
| `-t, --search-term TEXT` | Search term(s) to query EPA NEPIS. Can be specified multiple times for parallel crawling. |

## Examples

- Crawl documents 0-200 for "Flooding":
  ```bash
  pixi run -e climpdf climpdf crawl-epa 0 200 -t Flooding
  ```

- Crawl documents 0-500 for multiple climate terms (runs in parallel):
  ```bash
  pixi run -e climpdf climpdf crawl-epa 0 500 -t "Heat Wave" -t Flooding -t Drought
  ```

- Crawl a small batch for "Wildfire":
  ```bash
  pixi run -e climpdf climpdf crawl-epa 0 50 -t Wildfire
  ```

## How It Works

1. Constructs NEPIS search URLs for each document index in the specified range
2. Uses crawl4ai with Chromium to browse result pages
3. Extracts internal PDF/text document links from search results
4. Downloads unformatted OCR text documents via direct HTTP requests
5. Stores results in `data/EPA_{START_IDX}_{STOP_IDX}_{SEARCH_TERM}/` with filenames like `P{TOKEN}.txt`

## Output

- **Location**: `data/EPA_{START_IDX}_{STOP_IDX}_{SEARCH_TERM}/`
- **Format**: Plain text (.txt) files
- **Naming**: Token extracted from URL (e.g., `P10001.txt`)

## Notes

- Documents are downloaded as unformatted OCR text from `nepis.epa.gov`
- When multiple search terms are provided, crawling runs concurrently
- Uses persistent Chromium context in `data/browser_data/` for session continuity
- Failed crawls are logged but do not stop the process
- Output directories are automatically timestamped
