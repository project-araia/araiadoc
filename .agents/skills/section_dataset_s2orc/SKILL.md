---
name: section_dataset_s2orc
description: Sectionize s2orc_v2 documents into header:paragraph JSON dictionaries using the araiadoc tool. Reconstructs section structure from span-annotation offsets in body.text.
---

# `section-dataset-s2orc` Skill

Preprocess s2orc_v2 full-text documents into structured
`{title, header: text, …}` JSON dictionaries by slicing `body.text` with
the `paragraph` and `section_header` annotation span offsets. Use this
**instead of** `section-dataset-v2` whenever the input came from the
s2orc_v2 dataset (per `AGENTS.md`, the v2 sectionizer's `zip(paragraph,
sectionheader)` over Solr's flattened lists silently mis-aligns headers).

## Usage

```bash
pixi run -e araiadoc araiadoc section-dataset-s2orc SOURCE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SOURCE` | Directory of `.gz` JSONL shards **or** a directory of per-document `.json` files |

No options. Output dir is always `SOURCE_sectionized/`.

## Examples

- Sectionize raw shards downloaded by `download-s2orc`:
  ```bash
  pixi run -e araiadoc araiadoc section-dataset-s2orc data/s2orc
  ```

- Sectionize per-document `.json` files produced by
  `get-from-local-s2orc` (corpus-ID lookups, full-text keyword searches,
  or `--all-weather` / `--all-utility` predicates):
  ```bash
  pixi run -e araiadoc araiadoc section-dataset-s2orc data/utility_06-15
  ```

## Input Format

Two layouts are auto-detected:

### 1. Sharded `.gz` JSONL (from `download-s2orc` or `get-from-local-s2orc`)

```
data/s2orc/
  s2orc_v2_part_000.gz
  s2orc_v2_part_001.gz
  …
```

Or the nested TitanV layout:

```
data/<name>_results_<ts>/
  <name>/
    batches/
      batch_c01_000001.jsonl.gz
      …
```

Each JSON record is the raw s2orc_v2 shape:

```jsonc
{
  "corpusid": 12345,
  "title": "…",
  "body": {
    "text": "<single concatenated string>",
    "annotations": {
      "paragraph":      "[{\"start\":…,\"end\":…}, …]",  // JSON-encoded string
      "section_header": "[{\"start\":…,\"end\":…}, …]"   // JSON-encoded string
    }
  }
}
```

### 2. Per-document `.json` files (s2orc-v1 shape from `get-from-local-s2orc`)

```
data/<corpus_dir>/
  <bucket>/
    <corpus_id>.json
```

Each file has the **v1** shape with `content` instead of `body`:

```jsonc
{
  "corpusid": 12345,
  "externalids": {…},
  "content": {
    "text": "<single concatenated string>",
    "annotations": {
      "paragraph":     "[{\"start\":…,\"end\":…}, …]",
      "sectionheader": "[{\"start\":…,\"end\":…}, …]"   // note: no underscore in v1
    }
  }
}
```

`_normalize_to_v2()` (`sectionize.py:71`) coerces v1 → v2 automatically
before sectionization: maps `content` → `body`, renames `sectionheader`
→ `section_header`, and infers a `title` from annotation spans or the
first non-empty line of `content.text` if the v1 record lacks a
top-level `title`.

## How It Works

1. **Auto-detects input format**: prefers `*.gz` shards if any are
   present anywhere under `SOURCE` (uses `rglob`); falls back to
   per-document `.json` files via `_collect_from_path`.
2. **Normalizes legacy v1 records** to v2 shape (`_normalize_to_v2`).
3. **Parses span lists**: `annotations.paragraph` and
   `annotations.section_header` are **JSON-encoded strings** of
   `[{"start": int, "end": int, "attributes": …}]`. Decoded with
   `json.loads`, then sorted by `start`.
4. **Maps paragraphs → owning header**: for each paragraph span, the
   owning section is the most recent `section_header` span whose
   `end ≤ paragraph.start`. Paragraphs preceding the first header are
   buffered under a `__pre_header__` sentinel and promoted to a
   top-level `abstract` field in the output (s2orc_v2 has no separate
   `abstract` annotation key).
5. **Concatenates duplicates**: multiple paragraphs under the same
   canonical header are joined; repeated headers append rather than
   overwrite.
6. **Quality filters**: same as `section-dataset-v2`:
   - language detection (English only, `langdetect`),
   - per-section min length (≥40 chars, ≥20 alpha chars),
   - >30% numeric/special chars → dropped,
   - noise-header normalization + synonym mapping.
7. **Section gating**:
   - **Stops processing at** `conclusion` (last kept section).
   - **Terminates at** `acknowledgment`, `reference`, `bibliography`,
     `funding`, `dataavailability`, `codeavailability`, `appendix`,
     `disclosurestatement`, `conflictsofinterest`.
   - **Skips but continues past** `abstract`, `caption`, `figure`,
     `table`.

## Output

- **Location**: `{SOURCE}_sectionized/`
- **Layout**: sharded by last two digits of corpus_id
  (`{bucket}/{corpus_id}.json`).
- **Schema** (flat — no nested `sections` dict):

  ```json
  {
    "title": "Document Title",
    "abstract": "Pre-header text promoted here…",
    "introduction": "Previous research has shown…",
    "methods": "We analyzed data from…",
    "results": "Our findings indicate…",
    "discussion": "These results suggest…",
    "conclusion": "…"
  }
  ```

- **Checkpoint** (shard mode only): `batch_checkpoint.json` tracks
  completed `.gz` shards for resumable runs.
- **Failures** (per-document mode): collected into `failures.json` at
  the output root (`[{corpus_id, error}, …]`). Shard mode logs failures
  into the checkpoint file's `failures` array.

## Notes

- **Always use this command, not `section-dataset-v2`, on s2orc_v2
  data.** The v2 sectionizer's flat `zip(paragraph, sectionheader)`
  silently mis-assigns headers and drops trailing paragraphs (see
  `AGENTS.md`).
- Parallel: uses all available CPU cores via `joblib.Parallel(n_jobs=-1)`.
- Idempotent: existing output files are skipped (`skipped_existing`
  counter).
- Resumable: shard mode persists `batch_checkpoint.json` after each
  completed shard. Per-document mode is naturally resumable via the
  skip-if-exists check.
- Expected throughput: ~60 k per-document `.json` files sectionize in
  ~7 min on a local parallel pool (observed on `data/utility_06-15/`,
  4.3 GB input → 1.7 GB output, 189 failures out of 60,859).

## Common failure modes

- `"Empty body text"` — record's `body.text` (or `content.text`) is
  empty.
- `"No paragraph annotations"` — record has body text but no usable
  paragraph spans.
- `"No valid content sections found"` — every candidate section was
  filtered out by the quality gates (length, language, noise).

All failures are non-fatal; the run continues and writes the partial
output for the rest of the corpus.

## Schema quick-reference (output)

The output is the flat dict consumed by `araia-review`, `araia-compare`,
and any downstream analysis:

```python
{
  "title": str,         # may be inferred from first body line for v1 input
  "abstract": str,      # optional; pre-header paragraphs concatenated
  "<header>": str,      # one key per canonical section header
  …
}
```

There is **no** nested `sections` dict and **no** guaranteed `abstract`
field (it only appears if pre-header paragraphs existed).
