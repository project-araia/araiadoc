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

### Subprocess stderr draining

Any route that spawns a child process and reads from its `stdout` must also drain `stderr`, even if the output is not needed. Failing to do so can cause the child process to block waiting for the pipe buffer to clear, resulting in a deadlock. Use:

```ts
childProcess.stderr.resume();
```

---

## s2orc_v2 pipeline (replacement for TitanV/Solr)

The old `get-from-titanv` / `section-dataset-v2` pipeline reads from a Solr index whose schema flattens `body_text[].section` into two independent multi-valued fields (`paragraph`, `sectionheader`). This destroys per-paragraph section membership; the `zip()` in `_sectionize_item_v2` silently misassigns headers and drops trailing paragraphs. **Do not extend that pipeline** — use the new s2orc_v2 commands instead. The old commands are kept intact only for when the Solr dev environment returns.

New commands live in `src/araiadoc/s2orc.py` and `src/araiadoc/sectionize.py`:

- `download-s2orc -k <S2_API_KEY> -o <DIR> [-n N]` — downloads the Semantic Scholar `s2orc_v2` bulk dataset (~30 shards × ~1.07 GB compressed). `S2_API_KEY` env var works as an alternative to `-k`.
- `get-from-local-s2orc` — query a local download by corpus-ID list, full-text keyword, or pre-defined `--all-weather` / `--all-utility` Solr-style queries.
- `section-dataset-s2orc` — sectionize raw `.gz` shards or per-document `.json` directories. Resumable via `batch_checkpoint.json`.

### s2orc_v2 schema gotchas

- `doc["body"]["text"]` is a single string; `doc["body"]["annotations"]["paragraph"]` and `["section_header"]` are **JSON-encoded strings** of `[{"start": int, "end": int, "attributes": …}]` span lists. Decode with `json.loads()` then sort by `start`.
- There is **no** `abstract` annotation key. Paragraphs that appear before the first `section_header` span are promoted to a top-level `abstract` field by `_sectionize_item_s2orc_v2`.
- Correct header→paragraph mapping: for each paragraph span, the owning section is the most recent `section_header` whose `end ≤ paragraph["start"]`. Duplicate headers append rather than overwrite.

### Solr boolean query parser

`get-from-local-s2orc --query "…"` uses a recursive-descent parser (`_tokenize_solr` / `_SolrParser` / `_eval_solr_ast` in `s2orc.py`) supporting `AND`, `OR`, implicit AND, `NOT`/`-`, parens, and quoted phrases. **Do not replace it with flat-AND-over-all-terms** — the real `q` in `searches.py` is `(hazard terms OR …) AND (impact terms OR …)`, which a flat AND would never match.

### download-s2orc resume semantics

- Each shard downloads to `<name>.gz.part` and is atomically renamed on success.
- The skip-if-exists check tries `HEAD` first to get `Content-Length`, but S3 presigned URLs from the S2 Datasets API are method-bound (signed for `GET` only) and return no `Content-Length` on `HEAD`. The code falls back to a streaming `GET` closed immediately after the response headers arrive. **Do not remove the GET fallback** — without it every existing shard is flagged as a size mismatch (`expected = 0`) and re-downloaded. Truncated files (real size mismatches) are deleted and re-downloaded automatically.
- `_download_shard` uses `timeout=(30, 300)` (connect, read). A stalled per-chunk read for >300 s raises and triggers the 5-attempt retry loop with exponential backoff.
- After the streaming loop, `downloaded` is checked against `Content-Length`; a mismatch raises `RuntimeError` so the `.part` file is cleaned up rather than renamed.
- Resume is at the **shard level**, not within a shard — an interrupted shard restarts from byte 0 on retry.
