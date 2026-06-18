# Agent Notes — araiadoc

Lessons learned and conventions to keep in mind when working in this repo.

---

## CLI flag conventions

All `araiadoc` commands that accept a search term use `--search-term` (long form) or `-t` (short form), **not** `--term`. This applies to:

- `crawl-epa START_IDX STOP_IDX [-t/--search-term TEXT]` — can be repeated for parallel crawling
- `crawl-osti START_YEAR [-t/--search-term TEXT]` — can be repeated for parallel crawling
- `count-remote-osti START_YEAR STOP_YEAR [-t/--search-term TEXT]`

The short form `-t` and long form `--search-term` are both valid. Do not use `--term`.

## Skill files are authoritative for CLI flags

When writing webapp form components (or any code that builds CLI argument lists), **always verify flag names against the corresponding SKILL.md** in `.agents/skills/` before trusting your own knowledge. The skill files are kept in sync with the actual Click definitions in `src/araiadoc/crawl.py`.


### Output directory detection

`_prep_output_dir()` in `src/araiadoc/utils.py` echoes the output path to stdout:

```
Output directory: /absolute/path/to/data/...
```

The webapp's `CrawlEpa` component parses this line from the job's log buffer (prefixed as `[stdout] Output directory: ...`) to construct the zip download URL after a successful run.

---

## s2orc_v2 pipeline (replacement for TitanV/Solr)

The old `get-from-titanv` / `section-dataset-v2` pipeline reads from a Solr index whose schema flattens `body_text[].section` into two independent multi-valued fields (`paragraph`, `sectionheader`). This destroys per-paragraph section membership; the `zip()` in `_sectionize_item_v2` silently misassigns headers and drops trailing paragraphs. **Do not extend that pipeline** — use the new s2orc_v2 commands instead. The old commands are kept intact only for when the Solr dev environment returns.

New commands live in `src/araiadoc/s2orc.py` and `src/araiadoc/sectionize.py`:

- `download-s2orc -k <S2_API_KEY> -o <DIR> [-n N]` — downloads the Semantic Scholar `s2orc_v2` bulk dataset (~30 shards × ~1.07 GB compressed). `S2_API_KEY` env var works as an alternative to `-k`.
- `get-from-local-s2orc` — query a local download by corpus-ID list, full-text keyword, or pre-defined `--all-weather` / `--all-utility` Solr-style queries.
- `section-dataset-s2orc` — sectionize raw `.gz` shards or per-document `.json` directories. Resumable via `batch_checkpoint.json`.
- `verify-sectionization` — round-trip audit of a sectionized corpus against its raw input. See "Sectionization reporting vs. verification" below.

### s2orc_v2 schema gotchas

- `doc["body"]["text"]` is a single string; `doc["body"]["annotations"]["paragraph"]` and `["section_header"]` are **JSON-encoded strings** of `[{"start": int, "end": int, "attributes": …}]` span lists. Decode with `json.loads()` then sort by `start`.
- There is **no** `abstract` annotation key. Paragraphs that appear before the first `section_header` span are promoted to a top-level `abstract` field by `_sectionize_item_s2orc_v2`.
- Correct header→paragraph mapping: for each paragraph span, the owning section is the most recent `section_header` whose `end ≤ paragraph["start"]`. Duplicate headers append rather than overwrite.

### s2orc_v1 vs s2orc_v2 schema compatibility

Older s2orc_v1 shards use a different top-level shape than v2:

- **v2:** `body.text` (string), `body.annotations.{paragraph,section_header}` (JSON-encoded span lists).
- **v1:** `content.text` (string), `content.annotations.{paragraph,sectionheader,…}` (same JSON-encoded span format; note `sectionheader` without underscore).

`get-from-local-s2orc` probes each shard's top-level columns via `DESCRIBE SELECT * FROM read_ndjson(...)` (see `_detect_body_column` in `s2orc.py`) and rebuilds the SQL WHERE clause per shard against either `body.text` or `content.text`. **Do not assume `body.text` is always present** — hardcoding it breaks v1 shards with `Binder Error: Referenced table "body" not found`. `corpusid` is present in both schemas, so `_lookup_ids_duckdb` needs no probe.

Downstream, `sectionize.py` already normalises v1 → v2 (see `_sectionize_item_s2orc_v2` and the `content` → `body` / `sectionheader` → `section_header` shim around line 92), so docs extracted by `get-from-local-s2orc` from a v1 source feed straight into `section-dataset-s2orc` without further conversion.

### Solr boolean query parser

`get-from-local-s2orc --query "…"` uses a recursive-descent parser (`_tokenize_solr` / `_SolrParser` in `s2orc.py`) supporting `AND`, `OR`, implicit AND, `NOT`/`-`, parens, and quoted phrases. The parsed AST is translated to a DuckDB SQL `WHERE` clause via `_solr_ast_to_sql` (terms compile to `regexp_matches(lower(body.text), '\bterm\b')`), so all filtering happens inside DuckDB's vectorized engine rather than in Python. **Do not replace the parser with flat-AND-over-all-terms** — the real `q` in `searches.py` is `(hazard terms OR …) AND (impact terms OR …)`, which a flat AND would never match.

### get-from-local-s2orc is DuckDB-only

There is no pure-Python fallback path. The previous Python-predicate scanner (`_eval_solr_ast`, `_scan_predicate_parallel`, `_lookup_ids_parallel`, `_lookup_ids_streaming`) was ~50× slower for the weather/utility queries (~24 ms/doc vs. ~0.5 ms/doc) because it re-ran each of 100+ regex terms separately per document. It was removed along with the `--use-duckdb` flag (`duckdb` is a required dep). If a future use case genuinely needs a Python-side predicate (e.g. structural matches on annotation spans that DuckDB can't express in SQL), restore it as a separate code path — don't graft it back onto `_query_with_duckdb`.

### get-from-local-s2orc resume semantics

- Shards are processed one per `read_ndjson(?, …)` query so a `rich.Progress` bar advances per shard.
- After each successful shard, the shard filename is appended to `<output_dir>/duckdb_checkpoint.json` (atomic write via `.tmp` + replace). On startup, completed shards are filtered out of the pending list and the progress bar is pre-advanced.
- Mid-shard failures leave the shard *unmarked*, so a re-run retries it from the start. `_write_doc` overwrites by `corpusid.json`, so resume is safe and idempotent.
- Resume is keyed by `--output-dir`. Reusing the same `-o` against a *different* `--data-dir` is undefined behavior; use a fresh output dir if you change shard sources.

### download-s2orc resume semantics

- Each shard downloads to `<name>.gz.part` and is atomically renamed on success.
- The skip-if-exists check tries `HEAD` first to get `Content-Length`, but S3 presigned URLs from the S2 Datasets API are method-bound (signed for `GET` only) and return no `Content-Length` on `HEAD`. The code falls back to a streaming `GET` closed immediately after the response headers arrive. **Do not remove the GET fallback** — without it every existing shard is flagged as a size mismatch (`expected = 0`) and re-downloaded. Truncated files (real size mismatches) are deleted and re-downloaded automatically.
- `_download_shard` uses `timeout=(30, 300)` (connect, read). A stalled per-chunk read for >300 s raises and triggers the 5-attempt retry loop with exponential backoff.
- After the streaming loop, `downloaded` is checked against `Content-Length`; a mismatch raises `RuntimeError` so the `.part` file is cleaned up rather than renamed.
- Resume is at the **shard level**, not within a shard — an interrupted shard restarts from byte 0 on retry.

---

## Sectionization reporting vs. verification

Two distinct accounting systems live in `src/araiadoc/sectionize_report.py` and `src/araiadoc/processing/verify.py`. They answer different questions and are **not interchangeable**.

### `sectionization_report.{json,jsonl.gz}` (internal accounting)

Produced by every `section-dataset-*` run. Records what the item-level sectionizers (`_sectionize_item_s2orc_v2`, `_sectionize_item_v2`) *decided* for each document — kept/dropped chars, paragraphs, sections, bucketed by `DROP_REASONS`. This is fast (zero extra IO over what the run already does) and corpus-complete, but it is **internal-only**: it cannot detect bugs where the sectionizer thinks it kept a section but the bytes never reached disk (silent overwrites on duplicate canonical headers, `_normalize_text` over-stripping, output truncation, encoding mangling).

### `verify-sectionization` (round-trip audit)

Standalone CLI. Reads a sample of written sectionized files back from disk, reconstructs ground-truth section bounds *directly from the raw header/paragraph span annotations* (independent of the production walking logic), and verifies that each ground-truth section's first-paragraph 50-char probe substring-matches into the joined output values. Missing sections are attributed to the same `DROP_REASONS` by replaying the production filter helpers; anything that doesn't match a known filter is bucketed as `unknown_after_break`.

Use `verify-sectionization` whenever you're investigating "where did the content go" or before trusting a new sectionizer change. Reach for the report JSON for cheap corpus-wide stats during/after every run.

### `--detailed-report` flag (opt-in per-section rows)

All three `section-dataset-*` commands accept `--detailed-report`. When set, every row in `sectionization_report.jsonl.gz` carries a `sections: [{header, chars, paragraphs, outcome}, …]` array — one entry per section the sectionizer observed for that doc. The outcome is either `"kept"` or one of `DROP_REASONS`. **This roughly doubles per-doc row size**; default is off so production runs are unaffected.

Implementation detail: `DocReport.record_kept` / `record_dropped` accept an optional `header=` kwarg. Inside `_sectionize_item_s2orc_v2` / `_sectionize_item_v2` we thread it via a local `_hdr(name)` helper that returns the header string when `capture_section_detail=True` and `None` otherwise — so the row append is completely free when the flag is off. **If you add a new `record_kept`/`record_dropped` call site, you must pass `header=_hdr(...)` or that section will silently miss the detail rows even with the flag on.**

### `DROP_REASONS` vocabulary is the on-disk contract

`DROP_REASONS` in `sectionize_report.py` is rendered verbatim into the CLI "Drops by reason" table *and* persisted as keys inside `drops_by_reason` in every `sectionization_report.json` / `.jsonl.gz`. Renames are therefore breaking changes for historical reports — old files keep the old keys, new runs write the new ones, and any downstream tooling that aggregates across both needs to rename on read.

Historical rename: `unneeded_skip_truncation` → `unneeded_skip_remaining` (parallel to its sibling `unneeded_no_skip`; both reflect the source list names `unneeded_sections_skip_remaining` / `unneeded_sections_no_skip_remaining` in `text_quality/content_assessment.py`). The bucket counts only the trigger section itself — the discarded tail that follows lives in `post_break_truncated`.

## `failures.json` title recovery

`failures.json` (written by `_sectionize_workflow` and `_sectionize_workflow_s2orc_v2`) records one entry per failed document with `corpus_id`, `title`, `external_ids`, and `error`. Title recovery is non-trivial because **s2orc_v2 records have no top-level `title` field** and v1 records only expose it via annotation spans.

Two helpers in `sectionize.py` handle this:

- `_best_effort_title(doc)` — tries (1) a populated top-level `title`, (2) `title`/`papertitle`/`paper_title`/`doctitle` annotation spans projected onto `body.text` (v2) or `content.text` (v1), and (3) the first non-empty line of body text. Wrapped in `try/except` end-to-end so it's safe to call from exception handlers with a partially-parsed or `None` doc.
- `_best_effort_external_ids(doc)` — pulls `externalids`/`external_ids`/`externalIds` (strips `None` values) so failure rows carry a DOI/ARXIV identifier even when no title can be recovered.

**When adding a new failure-record call site** (in either the per-doc workers `_sectionize_one_file*` or the batch workers `_sectionize_batch_file*`), call `_best_effort_title(doc)` rather than `doc.get("title") or ""` — including (especially!) inside `except` arms. Hold the raw `doc` / `item` in a variable initialized to `None` *outside* the `try` so the `except` can still see whatever was parsed before the failure. Normalize-then-lookup is also fine for the success path; `_normalize_to_v2` is idempotent on already-v2 records.
