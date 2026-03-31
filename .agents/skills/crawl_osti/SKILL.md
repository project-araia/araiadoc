---
name: crawl-osti
description: Asynchronously crawl OSTI (Office of Scientific and Technical Information) result pages using the climpdf tool.
---

# `crawl-osti` Skill

Asynchronously crawl the OSTI (DOE Office of Scientific and Technical Information) database for scientific journal articles matching specified search terms within a year range. Downloads available full-text PDFs.

## Usage

```bash
pixi run -e climpdf climpdf crawl-osti [OPTIONS] START_YEAR [STOP_YEAR]
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `START_YEAR` | integer | required | The starting year for document publication date |
| `STOP_YEAR` | integer | 2025 | The ending year for document publication date |

### Options

| Flag | Description |
|------|-------------|
| `-t, --search-term TEXT` | Search term(s) to query OSTI. Can be specified multiple times for parallel crawling. |

## Examples

- Crawl OSTI for "Blizzard" documents from 2010 to 2025:
  ```bash
  pixi run -e climpdf climpdf crawl-osti 2010 2025 -t Blizzard
  ```

- Crawl for multiple climate terms from 2000 to present:
  ```bash
  pixi run -e climpdf climpdf crawl-osti 2000 -t "Heat Wave" -t Flooding -t Drought
  ```

- Search only recent documents (2020-2025):
  ```bash
  pixi run -e climpdf climpdf crawl-osti 2020 2025 -t "Sea Level Rise"
  ```

## How It Works

1. Queries the OSTI API (`https://www.osti.gov/api/v1/records`) with search parameters
2. Filters for journal articles with available full-text
3. Saves the API response metadata to `OSTI.GOV-metadata.json`
4. Downloads PDF files from available `fulltext` links
5. Skips documents already in `OSTI_doc_ids.json` checkpoint file
6. Stores results in timestamped output directories

## Output

- **Location**: `data/OSTI_{START_YEAR}_{STOP_YEAR}_{SEARCH_TERM}/`
- **Files**:
  - `OSTI.GOV-metadata.json` - Full API response with document metadata
  - `{TOKEN}.pdf` - Downloaded full-text PDFs

## Notes

- Only downloads documents that have `availability:fulltext` and `product_type:Journal Article`
- Automatically skips known documents via checkpoint file at `data/OSTI_doc_ids.json`
- Each search term crawls in parallel when multiple are provided
- Uses 60-second timeout per document download
- Failed downloads are logged with exceptions captured
