# Document Collection

This section covers the tools and commands used to query, search, and download documents and metadata into the `araiadoc` pipeline.

## CLI Flag Conventions

All `araiadoc` commands that accept a search term use `--search-term` (long form) or `-t` (short form), **not** `--term`. This applies to:

- `crawl-epa START_IDX STOP_IDX [-t/--search-term TEXT]`
- `crawl-osti START_YEAR [-t/--search-term TEXT]`
- `count-remote-osti START_YEAR STOP_YEAR [-t/--search-term TEXT]`

Both short form `-t` and long form `--search-term` are valid. Do not use `--term`.

---

## Commands Reference

### Crawling EPA (NEPIS)

The EPA crawler downloads document results from the EPA NEPIS database asynchronously.

```bash
araiadoc crawl-epa START_IDX STOP_IDX [OPTIONS]
```

- **Options:**
  - `-t, --search-term TEXT`: The search term to query (can be repeated for multiple terms).

**Example:**
```bash
araiadoc crawl-epa 0 100 -t Flooding
```

### Crawling OSTI

The OSTI crawler asynchronously gathers document metadata and result pages from the Office of Scientific and Technical Information.

```bash
araiadoc crawl-osti START_YEAR [OPTIONS]
```

- **Options:**
  - `-t, --search-term TEXT`: Search term (can be repeated).

**Example:**
```bash
araiadoc crawl-osti 2010 -t Blizzard -t Tornado -t "Heat Waves"
```

To optimize crawler bounds, always run `count-remote-osti` beforehand to estimate matching results, and `count-local OSTI` between searches to sync checkpoints.

### Estimating Remote OSTI Results

```bash
araiadoc count-remote-osti START_YEAR STOP_YEAR [OPTIONS]
```

- **Options:**
  - `-t, --search-term TEXT`: Search term (can be repeated).

**Example:**
```bash
araiadoc count-remote-osti 2010 2025 -t "Heat Waves" -t Tornado
```

### Local Document Counting

Generates a document checkpoint file to track already-downloaded document IDs and ensure we do not download duplicates.

```bash
araiadoc count-local SOURCE
```

**Example:**
```bash
araiadoc count-local EPA
araiadoc count-local OSTI
```

---

## Semantic Scholar Bulk (s2orc_v2) Pipeline

For large-scale, high-fidelity operations, `araiadoc` utilizes the Semantic Scholar `s2orc_v2` bulk dataset.

### Bulk Downloading Shards

```bash
araiadoc download-s2orc -k <S2_API_KEY> -o <DIR> [-n N]
```

Downloads compressed `.gz` shards from Semantic Scholar (~30 shards, ~1.07 GB each compressed).
- **Options:**
  - `-k, --api-key TEXT`: Semantic Scholar API Key (alternatively, set `S2_API_KEY` env var).
  - `-o, --output-dir PATH`: Directory where downloaded shards are saved.
  - `-n, --shards INTEGER`: Limit to downloading the first N shards.

Downloads are fully resumable at the **shard level**; incomplete downloads (`.part` files) are cleaned up and restarted.

### Extracting from Local s2orc_v2

Query downloaded shards locally using a vectorized DuckDB-backed search engine.

```bash
araiadoc get-from-local-s2orc -d <DATA_DIR> -o <OUTPUT_DIR> [QUERY_OPTION]
```

- **Query Options (Use exactly one):**
  - `-s, --source PATH`: A JSON array of corpus IDs or a `.txt` file with one ID per line.
  - `-a, --all-weather`: Predefined climate/weather keyword query.
  - `-u, --all-utility`: Predefined utility/electricity keyword query.
  - `-q, --query TEXT`: Ad-hoc Solr-style query (supports `AND`, `OR`, implicit AND, `NOT`/`-`, parenthesized groupings, and quoted phrases).

**Examples:**
```bash
araiadoc get-from-local-s2orc -d data/s2orc_v2 -s paper_ids.txt
araiadoc get-from-local-s2orc -d data/s2orc_v2 -o data/all_weather --all-weather
araiadoc get-from-local-s2orc -d data/s2orc_v2 -q '"adsorption refrigeration"'
```

- **Resume Semantics:** Shards are processed sequentially with a progress bar. Successfully queried shards are recorded in `<output_dir>/duckdb_checkpoint.json` and skipped on subsequent runs.
- **DuckDB Vectorized Engine:** Query terms are translated into highly efficient regular expression checks processed inside DuckDB.
- **s2orc_v1 vs v2 Schema Auto-detection:** The query engine automatically detects whether each shard is v1-shape (`content.text` and `sectionheader`) or v2-shape (`body.text` and `section_header`) to construct the appropriate DuckDB query.
