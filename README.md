# araiadoc

A large suite of tools and scripts for downloading and processing documents for the ARAIA project.

The primary utility is the `araiadoc` command-line tool, with the following commands:

```bash
Usage: araiadoc [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  agentic-judge-dataset      Judge relevance of a sectionized corpus with an OpenAI-compatible model.
  complete-semantic-scholar  Download documents from Semantic Scholar that match a given input file containing document ID.
  convert                    Convert PDFs in a given directory ``source`` to json.
  count-local                Count the number of downloaded files from a given source. Creates a checkpoint file.
  count-remote-osti          Count potentially downloadable files from OSTI, for any number of search terms. Leave blank for all.
  crawl-epa                  Asynchronously crawl EPA result pages.
  crawl-osti                 Asynchronously crawl OSTI result pages.
  download-s2orc             Download Semantic Scholar's s2orc_v2 bulk dataset (~30 shards).
  epa-ocr-to-json            Convert EPA's OCR fulltext to similar json format as internal schema.
  filter-dataset             Copy a raw dataset while excluding documents that match regex patterns.
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

### Filter dataset

```bash
Usage: araiadoc filter-dataset [OPTIONS] SOURCE

Options:
  --file FILE            Path to .txt file with one regex pattern per line.
                         Empty lines and lines starting with # are ignored.
  --patterns TEXT        Comma-separated regex patterns. Documents matching
                         ANY pattern are excluded.
  -o, --output-dir PATH  Directory for the filtered copy. Defaults to
                         SOURCE_filtered.
```

Copies a raw pre-sectionization dataset while excluding documents whose title, abstract, paragraph text, or s2orc body text matches any exclusion regex. The original dataset is never modified. Kept per-document `.json` files are copied with relative paths preserved; `.jsonl`, `.jsonl.gz`, and plain `.gz` JSONL shards are streamed and rewritten with only kept rows.

The default output directory is `SOURCE_filtered`. If `--output-dir` is provided, it must be outside `SOURCE` so filtering cannot mutate or reread its own input. Every run writes `filter_report.json` in the output directory with kept/excluded counts and matches by pattern.

Use this when you want keyword-based exclusion before sectionization:

```bash
araiadoc filter-dataset data/s2orc_v2_shards --file data/filter.txt
araiadoc filter-dataset data/all_weather --patterns "genomics,nanoparticle synthesis" -o data/all_weather_filtered
araiadoc section-dataset-s2orc data/all_weather_filtered
```

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

When `--exclude-patterns` or `--exclude-file` is used, the `sectionization_report.jsonl.gz` includes which specific pattern(s) matched in the `error` field of excluded documents (e.g. `"Excluded by pattern(s): nanoparticle synthesis, quantum dot"`). For reusable raw filtered datasets, prefer `filter-dataset` before sectionization.

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

Sectionizes s2orc_v2 documents using span-annotation offsets in `body.text`. `SOURCE` may be a directory of `.gz` JSONL shards (from `download-s2orc`) or a directory of per-document `.json` files (from `get-from-local-s2orc`). v1-shape records are normalized to v2 transparently. Resumable via `batch_checkpoint.json`.

Every run writes `sectionization_report.json` (corpus aggregates) and `sectionization_report.jsonl.gz` (per-doc rows). With `--detailed-report`, each per-doc row also carries a `sections` array (header, chars, paragraphs, outcome) — roughly doubles row size, off by default.

With `--exclude-patterns` or `--exclude-file`, excluded documents report which pattern(s) matched in their `error` field. For reusable raw filtered datasets, prefer `filter-dataset` before sectionization.

```araiadoc section-dataset-s2orc data/s2orc_v2_shards```
```araiadoc section-dataset-s2orc data/all_weather --detailed-report```
```araiadoc section-dataset-s2orc data/s2orc_v2_shards --exclude-file data/filter.txt```

### Download s2orc

```bash
Usage: araiadoc download-s2orc [OPTIONS]

Options:
  -k, --api-key TEXT     Semantic Scholar API key (or set S2_API_KEY env var).  [required]
  -o, --output-dir PATH  Directory in which to save the downloaded .gz shards.  [required]
  -n, --shards INTEGER   Download only the first N shards (omit to download all ~30).
```

Downloads the Semantic Scholar s2orc_v2 bulk dataset. Each shard is a gzip-compressed JSONL file (~6 GB each, ~180 GB total). Already-present shards are skipped so the command is safely re-runnable. Obtain an API key at https://www.semanticscholar.org/product/api.

```araiadoc download-s2orc -k $S2_API_KEY -o data/s2orc_v2```
```araiadoc download-s2orc -k $S2_API_KEY -o data/s2orc_v2 -n 5```

### Get from local s2orc

```bash
Usage: araiadoc get-from-local-s2orc [OPTIONS]

Options:
  -d, --data-dir PATH    Directory containing the downloaded s2orc_v2 .gz shard files.  [required]
  -o, --output-dir PATH  Output directory for extracted JSON documents (created if absent).
  -s, --source PATH      File of corpus IDs to look up: a JSON array of integers, or a .txt file with one integer ID per line.
  -a, --all-weather      Extract all documents matching the weather/climate keyword search.
  -u, --all-utility      Extract all documents matching the utility/electricity keyword search.
  -q, --query TEXT       Ad-hoc Solr-style query string. Supports AND, OR, NOT, parens, and quoted phrases.
```

Queries a local s2orc_v2 download using DuckDB. Use exactly one of `--source`, `--all-weather`, `--all-utility`, or `--query`. Produces one JSON file per matching document sharded by the last two digits of the corpus ID — the same layout consumed by `section-dataset-s2orc`. Resumable: completed shards are recorded in `duckdb_checkpoint.json` so re-running with the same `--output-dir` skips them. v1 shards (with `content.text` instead of `body.text`) are detected automatically per shard.

```araiadoc get-from-local-s2orc -d data/s2orc_v2 -s resilience_ids.txt```
```araiadoc get-from-local-s2orc -d data/s2orc_v2 -o data/all_weather --all-weather```
```araiadoc get-from-local-s2orc -d data/s2orc_v2 -q '"adsorption refrigeration"'```

### Agentic judge dataset

```bash
Usage: araiadoc agentic-judge-dataset [OPTIONS] [SOURCE]

Options:
  --model TEXT                    OpenAI-compatible chat model name.
                                  [default: openai/gpt-oss-20b]
  --base-url TEXT                 OpenAI-compatible API base URL.  [default:
                                  https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1]
  --api-key TEXT                  API key/token. Also read from API_KEY or
                                  OPENAI_API_KEY.
  --prompt FILE                   Rubric prompt file. Must emphasize a 0-3
                                  score and corresponding relevance criteria.
                                  Required except with --resubmit-existing.
  -o, --artifact-dir, --output-dir PATH
                                  Directory for araiadoc artifacts/work files
                                  (request chunks, manifest, checkpoints,
                                  results, summary). Defaults to SOURCE_judged.
                                  --output-dir is a legacy alias.
  --mode [requests|alcf-batch-submit|alcf-batch-status|alcf-batch-collect]
                                  requests: judge each document via chat
                                  completions (works on any OpenAI-compatible
                                  endpoint). alcf-batch-submit: build the
                                  batch request JSONL + manifest and POST an
                                  ALCF filesystem-based batch job.
                                  alcf-batch-status: poll the ALCF gateway for
                                  the batches recorded in
                                  batch_submit_checkpoint.json (add --wait to
                                  block until all finish). alcf-batch-collect:
                                  fold an ALCF batch output file/folder back
                                  into judge artifacts.  [default: requests]
  --concurrency INTEGER RANGE     Concurrent requests for --mode requests.
                                  [default: 4; x>=1]
  --max-tokens INTEGER RANGE      Maximum generated tokens.  [default: 512; x>=1]
  --temperature FLOAT             Sampling temperature.  [default: 0.0]
  --timeout FLOAT RANGE           Per-request timeout in seconds.
                                  [default: 120.0; x>=1.0]
  --limit INTEGER RANGE           Judge at most N documents. No limit by
                                  default.  [x>=1]
  --dry-run                       Build and print prompt samples without
                                  calling the model.
  --max-input-chars INTEGER RANGE
                                  Maximum document payload characters included
                                  in each prompt.  [default: 20000; x>=100]
  --copy-kept                     Copy documents with kept decisions into
                                  OUTPUT_DIR/kept.
  --keep-decisions TEXT           Comma-separated decisions copied by
                                  --copy-kept.  [default: relevant]
  --resume / --no-resume          Skip completed stable job keys from
                                  judge_checkpoint.json.  [default: resume]
  --batch-request-dir, --batch-input-dir TEXT
                                  [alcf-batch-submit] ALCF filesystem folder
                                  containing request JSONL chunk file(s) for
                                  the endpoint to read (e.g.
                                  /eagle/.../requests/). The tool submits one
                                  batch per chunk using the SAME filenames it
                                  wrote locally (batch_requests.jsonl, or
                                  batch_requests_000.jsonl, …). --batch-input-
                                  dir is a legacy alias.
  --batch-input-file TEXT         [alcf-batch-submit] DEPRECATED for multi-
                                  chunk runs; use --batch-request-dir. ALCF
                                  filesystem path the inference service reads a
                                  SINGLE-chunk request JSONL from (e.g.
                                  /eagle/argonne_tpc/you/input.jsonl). Errors
                                  if the run produced more than one chunk.
  --batch-result-dir, --batch-output-folder TEXT
                                  [alcf-batch-submit] ALCF filesystem folder
                                  where the inference service writes batch
                                  result/progress files (e.g.
                                  /eagle/.../batch_results/). --batch-output-
                                  folder is a legacy alias.
  --collect-batch-output PATH     [alcf-batch-collect] Path to the ALCF batch
                                  output .jsonl file, or a folder containing
                                  output .jsonl files, to fold into judge
                                  artifacts.
  --max-batch-mb FLOAT RANGE      [alcf-batch-submit] Maximum size in MB per
                                  request JSONL chunk. When all requests fit
                                  within this limit a single
                                  batch_requests.jsonl is written; otherwise
                                  numbered chunk files are written and one
                                  batch job is submitted per chunk. Default
                                  (9 MB) stays comfortably under the ALCF
                                  10 MB payload limit.
                                  [default: 9; x>=0.001]
  --max-active-batches INTEGER RANGE
                                  [alcf-batch-submit] Maximum number of active
                                  (pending/running) ALCF batches at once.
                                  Submission is throttled to stay within this;
                                  ALCF currently caps users at 2 active
                                  batches.  [default: 2; x>=1]
  --poll-interval FLOAT RANGE     [alcf-batch-submit / alcf-batch-status]
                                  Seconds to wait between polls (active-batch
                                  slot check during submit; result check during
                                  status --wait).  [default: 30.0; x>=1.0]
  --resubmit-existing             [alcf-batch-submit] Submit the
                                  batch_requests*.jsonl already written to
                                  --artifact-dir/--output-dir instead of
                                  regenerating them. Skips reading SOURCE /
                                  the prompt / re-chunking; the submit model
                                  is derived from body.model inside the
                                  existing JSONL, and --max-batch-mb is
                                  ignored. Use to resume after a partial or
                                  failed submission without rebuilding.
  --wait                          [alcf-batch-status] Block and keep polling
                                  every --poll-interval seconds until all
                                  recorded batches reach a terminal state
                                  (completed/failed) instead of printing a
                                  single status snapshot and exiting.
```

Judges a sectionized corpus produced by `section-dataset-s2orc` or `section-dataset-v2`. Input documents are flat JSON files containing fields such as `title`, `abstract`, `introduction`, `methods`, and `results`. Corpus-level JSON files such as `sectionization_report.json`, `failures.json`, and checkpoints are skipped.

The command preserves source data and writes judgment artifacts outside the input directory:

```text
SOURCE_judged/
  judge_results.jsonl.gz
  judge_summary.json
  judge_checkpoint.json
  failures.json
  batch_requests.jsonl          # ALCF batch: single chunk (fits within --max-batch-mb)
  batch_requests_000.jsonl      # ALCF batch: first chunk when split across multiple chunks
  batch_requests_001.jsonl      # ALCF batch: second chunk, etc.
  batch_manifest.json           # ALCF batch: custom_id → doc map (always a single file)
  batch_submit_checkpoint.json  # ALCF batch: remote input → batch_id, for resume/throttling
  kept/                         # only when --copy-kept is used
```

Use `--dry-run --limit 3` first to inspect prompt payloads before spending inference time:

```bash
araiadoc agentic-judge-dataset data/all_weather_sectionized \
  --prompt prompts/climate_resilience_relevance.md \
  --dry-run \
  --limit 3
```

#### Request mode (default)

Request mode uses OpenAI-compatible chat completions with bounded local concurrency, and works on any OpenAI-compatible endpoint. The default model/base URL target ALCF Sophia/vLLM (`openai/gpt-oss-20b` at `/resource_server/sophia/vllm/v1`), but both should be overridden together when targeting another endpoint:

```bash
araiadoc agentic-judge-dataset data/all_weather_sectionized \
  --prompt prompts/climate_resilience_relevance.md \
  --api-key "$API_KEY" \
  --concurrency 4
```

#### ALCF batch mode

The ALCF inference gateway batch API is **not** the OpenAI Files/Batches API: there is no file upload. A single `POST {base_url}/batches` references an input JSONL and an output folder that both live on **ALCF shared storage** (e.g. Eagle, `/eagle/argonne_tpc/...`), which the inference service reads and writes directly. Because of that, ALCF batch judging is split into two phases bracketing a file transfer to/from ALCF storage.

**Payload limit:** ALCF caps each batch request at 10 MB. `--max-batch-mb` (default 9) keeps chunks safely under that limit. When the full corpus fits in one chunk a single `batch_requests.jsonl` is written (backward-compatible). When it doesn't, numbered chunk files (`batch_requests_000.jsonl`, `batch_requests_001.jsonl`, …) are written and one batch job is submitted per chunk, all sharing the same output folder. A single shared `batch_manifest.json` covers all chunks, and collect is unchanged — it already accepts a folder of output files.

**Absolute paths required:** `--batch-request-dir`, `--batch-input-file`, and `--batch-result-dir` must be **absolute** paths on ALCF storage (e.g. `/eagle/argonne_tpc/<you>/...`). The inference service reads/writes them on Sophia's filesystem, not the machine running this command, so a *relative* path like `63_judged_input/` resolves to nothing on the node and every batch fails within seconds (`status: failed`). The tool now rejects relative paths up front, and warns if an absolute path isn't under `/eagle` or `/lus`. Legacy aliases `--batch-input-dir` and `--batch-output-folder` are still accepted.

**Active-batch quota:** ALCF also limits each user to a small number of *active* (pending/running) batches (currently 2). Multi-chunk submission is therefore throttled to `--max-active-batches` (default 2): before each submit the gateway is polled every `--poll-interval` seconds until a slot frees, and a `quota_exceeded` rejection triggers an automatic back-off and retry rather than aborting. Submitted chunks are recorded in `batch_submit_checkpoint.json`, so re-running resumes where it left off instead of double-submitting — and it also reconciles against the live batch list (matching on `input_file`) to adopt batches submitted before checkpointing existed. `--poll-interval` is also reused by `alcf-batch-status --wait` to control the result-check cadence.

1. **Submit.** First build the request JSONL chunk(s) and manifest locally (omitting ALCF paths stages files only and prints next steps):

   ```bash
   araiadoc agentic-judge-dataset data/all_weather_sectionized \
     --prompt prompts/climate_resilience_relevance.md \
     --mode alcf-batch-submit --artifact-dir data/all_weather_judged \
     --model google/gemma-3-27b-it
   ```

   Copy the chunk file(s) from `data/all_weather_judged/` into a single ALCF storage folder — **keep the filenames as-is, no renaming** — then submit, pointing `--batch-request-dir` at that folder. The tool submits one batch per chunk, reusing each chunk's filename (`batch_requests_000.jsonl`, …) under that folder:

   ```bash
   araiadoc agentic-judge-dataset data/all_weather_sectionized \
     --prompt prompts/climate_resilience_relevance.md \
     --mode alcf-batch-submit --artifact-dir data/all_weather_judged \
     --model google/gemma-3-27b-it \
     --api-key "$API_KEY" \
     --batch-request-dir /eagle/argonne_tpc/you/requests/ \
     --batch-result-dir /eagle/argonne_tpc/you/output/
   ```

   For a single-chunk run you may instead pass the legacy `--batch-input-file /eagle/.../input.jsonl` (one explicit path). It errors if the run produced more than one chunk — use `--batch-request-dir` in that case.

   **Resuming a partial/failed submission.** Because the requests are already baked into `batch_requests*.jsonl` in `--artifact-dir`, you don't need to re-specify `SOURCE`, `--prompt`, `--model`, or `--max-batch-mb` to resubmit — pass `--resubmit-existing` instead. It reads the existing chunk files (and `batch_manifest.json`) straight from `--artifact-dir`, never regenerating them, derives the ALCF submit model from `body.model` inside the JSONL, and submits only chunks not already recorded in `batch_submit_checkpoint.json` (also reconciling against the live gateway batch list):

   ```bash
   araiadoc agentic-judge-dataset \
     --mode alcf-batch-submit --artifact-dir data/all_weather_judged \
     --api-key "$API_KEY" --resubmit-existing \
     --batch-request-dir /eagle/argonne_tpc/you/requests/ \
     --batch-result-dir /eagle/argonne_tpc/you/output/
   ```

2. **Check status.** Poll the ALCF gateway for every batch recorded in `batch_submit_checkpoint.json` without leaving the terminal:

   ```bash
   # Single snapshot — print current state of all submitted batches and exit.
   araiadoc agentic-judge-dataset \
     --mode alcf-batch-status --artifact-dir data/all_weather_judged \
     --api-key "$API_KEY"
   ```

   Each batch is classified into one of four states based on the gateway's `/batches/<id>/result` response:

   | State | Meaning |
   |---|---|
   | `completed` | Results are ready in `--batch-result-dir`. |
   | `ongoing` | Job is still running; results not ready yet. |
   | `failed` | Job failed; the last line of the worker traceback is printed (e.g. `FileNotFoundError` for a bad path). |
   | `unknown` | Unexpected error code from the gateway. |

   Output looks like:
   ```text
   Batch status (3/3 polled):
     [completed] b0a1c2d3-...  <- /eagle/.../batch_requests_000.jsonl
     [  ongoing] b1e2f3a4-...  <- /eagle/.../batch_requests_001.jsonl
     [   failed] b2c3d4e5-...  <- /eagle/.../batch_requests_002.jsonl
                 FileNotFoundError: 'relative/path/input.jsonl'
     => completed=1, failed=1, ongoing=1
   ```

   Add `--wait` to block until all batches finish, re-polling every `--poll-interval` seconds (default 30). Already-terminal batches are skipped on subsequent passes:

   ```bash
   araiadoc agentic-judge-dataset \
     --mode alcf-batch-status --artifact-dir data/all_weather_judged \
     --api-key "$API_KEY" \
     --wait --poll-interval 60
   ```

   When all batches complete successfully the command prints the ready-to-run `alcf-batch-collect` command.

3. **Collect.** When all jobs finish, copy the output back and fold it into the same judge artifacts. The single `batch_manifest.json` written during submit maps every `custom_id` across all chunks back to its document:

   ```bash
   araiadoc agentic-judge-dataset data/all_weather_sectionized \
     --prompt prompts/climate_resilience_relevance.md \
     --mode alcf-batch-collect --artifact-dir data/all_weather_judged \
     --model google/gemma-3-27b-it \
     --collect-batch-output /eagle/argonne_tpc/you/output/ \
     --copy-kept
   ```

`--collect-batch-output` accepts either a single `.jsonl` file or a folder of `.jsonl` files (one per chunk is fine). Output rows whose `custom_id` is missing from the manifest, and manifest entries with no matching output row, are recorded in `failures.json`.

Not all ALCF models support batch processing — see the [ALCF inference endpoints docs](https://docs.alcf.anl.gov/services/inference-endpoints/#available-models). When in doubt, request mode works everywhere.

#### Result schema and resume

Each result row in `judge_results.jsonl.gz` includes `doc_id`, `source_path`, title, model, base URL, prompt and input hashes, decision, score, rationale, raw response, parse status, and timestamp. Unparseable model responses are preserved as rows with `parsed=false` and `raw_response` for auditability.

Resume is enabled by default. Completed work is keyed by source path, document ID, input hash, prompt hash, model, and base URL, so changing the prompt/model/endpoint/document content forces re-judgment. `--artifact-dir` / `--output-dir` must be outside `SOURCE` so the command cannot recurse into its own artifacts.

When `--copy-kept` is set, documents whose parsed decision is in `--keep-decisions` are copied to `OUTPUT_DIR/kept/` with relative paths preserved. The default keeps only `relevant`; use `--keep-decisions relevant,maybe` to also retain uncertain matches.

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

Round-trip audit that reads written sectionized JSON back from disk, reconstructs ground-truth section bounds from raw span annotations independently of the production sectionizer, and verifies each section's first-paragraph 50-char probe survived to disk. Catches bugs that `sectionization_report.json` cannot — silent overwrites on duplicate canonical headers, output truncation, encoding mangling. When `--exclude-patterns` or `--exclude-file` is supplied, missing documents are re-checked against the patterns; matches are attributed to `excluded_by_pattern` (tallied per pattern in the `excluded_by_pattern_reasons` key of the JSON report) rather than `skipped_missing_sect`.

```araiadoc verify-sectionization data/s2orc_v2_shards data/s2orc_v2_shards_sectionized```
```araiadoc verify-sectionization raw/ sectionized/ -n 5000 --report-json audit.json --fail-threshold 5.0```
```araiadoc verify-sectionization raw/ sectionized/ --exclude-file data/filter.txt```

### Agent Skills

Agent Skills are available in the `.agents/skills` directory. Supported skills include:
  - `crawl-epa`: Crawl EPA result pages
  - `crawl-osti`: Crawl OSTI result pages
  - `get-from-titanv`: Download from TitanV (S2ORC) database
  - `section-dataset-v2`: Sectionize dataset v2
  - `section-dataset-s2orc`: Sectionize s2orc_v2 documents from span annotations
  - `araia-review`: Review a sectionized corpus against its generating Solr query
  - `araia-compare`: Compare two sectionized corpora for overlap / drift
  - `araia-verify`: Round-trip audit of a sectionized corpus against its raw input

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
