---
name: araia-verify
description: Round-trip audit of a sectionized araiadoc corpus against its raw s2orc input. Samples sectionized outputs, reconstructs ground truth from raw header/paragraph span annotations, and verifies each section survived to disk. Catches silent bugs the internal sectionization_report.json cannot — duplicate-header overwrites, output truncation, encoding mangling.
---

# `araia-verify` Skill

Independent disk-level correctness check for `section-dataset-s2orc` output.
Where `sectionization_report.json` records what the sectionizer *decided*,
`verify-sectionization` checks what actually *hit disk* — reading written JSON
back and comparing it against ground truth reconstructed directly from raw span
annotations.

If you want to evaluate topical fit of a corpus against its source query, use
`araia-review` instead. If you want to compare two corpora for overlap or
drift, use `araia-compare`.

Use this skill any time the user asks to:

- "verify the sectionization",
- "audit the corpus",
- "did the sectionizer drop content",
- "round-trip check the s2orc output",
- "how much content was lost", or
- "validate a sectionizer change before shipping it".

## Inputs the user must supply (or infer from context)

1. **`RAW_DIR`** — the raw input directory. Auto-detected as either:
   - a directory of `.gz` JSONL shards (from `download-s2orc` or
     `get-from-local-s2orc`), or
   - a directory of per-document `.json` files sharded as
     `<bucket>/<corpus_id>.json`.
2. **`SECT_DIR`** — the corresponding sectionized output directory (typically
   `<raw>_sectionized/`), sharded the same way.
3. **(Optional)** sample size `-n` (default 1000; use 0 for all docs), `--seed`
   for reproducibility, `--report-json` for a machine-readable report,
   `--fail-threshold` for CI gating, and `--exclude-patterns` /
   `--exclude-file` if patterns were used during the original sectionization.

## Usage

```bash
pixi run -e araiadoc araiadoc verify-sectionization RAW_DIR SECT_DIR [OPTIONS]
```

### Examples

```bash
# Basic audit — 1000-doc sample
pixi run -e araiadoc araiadoc verify-sectionization \
    data/s2orc_v2_shards data/s2orc_v2_shards_sectionized

# Large sample with JSON report and CI threshold
pixi run -e araiadoc araiadoc verify-sectionization \
    raw/ sectionized/ -n 5000 --report-json audit.json --fail-threshold 5.0

# With exclude patterns (must match those used during sectionization)
pixi run -e araiadoc araiadoc verify-sectionization \
    raw/ sectionized/ --exclude-file data/filter.txt

# Full corpus audit (slow — only for small dirs or final gates)
pixi run -e araiadoc araiadoc verify-sectionization \
    raw/ sectionized/ -n 0 --report-json full_audit.json
```

## How It Works

1. **Discover raw docs.** If any `.gz` files are found under `RAW_DIR`
   (recursively), they are treated as JSONL.GZ shards. Otherwise per-document
   `.json` files are collected.

2. **Sample.** For shards, reservoir sampling (`_reservoir_sample_gz_docs`,
   `verify.py:379`) streams the full corpus without materializing it. For
   per-doc JSON, `random.Random(seed).sample` is used. `-n 0` audits
   every document.

3. **Normalize.** Each raw document is normalized from v1 to v2 shape via
   `_normalize_to_v2` (`sectionize.py`), the same helper the production
   sectionizer uses.

4. **Reconstruct ground truth.** `_build_ground_truth_sections`
   (`verify.py:103`) walks the raw `section_header` and `paragraph` span
   annotations *independently* of the production sectionizer's walking logic.
   Paragraphs before the first header are grouped as an `abstract` section.

5. **Probe.** For each ground-truth section with at least one paragraph, the
   first 50 characters of its first paragraph (after `_normalize_text`) are
   checked as a substring against the joined sectionized output values
   (`_PRESENCE_PROBE_LEN = 50`, `verify.py:60`). This length is long enough
   to avoid boilerplate false-positives while tolerating minor whitespace
   normalization differences.

6. **Attribute missing sections.** `_diagnose_missing` (`verify.py:159`)
   replays the same filter helpers the production loop uses to assign a
   `DROP_REASONS` bucket to each missing section:
   - `noise_header` — header failed `_header_is_noise`
   - `unneeded_skip_remaining` — header in `unneeded_sections_skip_remaining`
   - `unneeded_no_skip` — header in `unneeded_sections_no_skip_remaining`
   - `non_substantive` — content failed `_content_is_substantive`
   - `non_english_or_invalid` — failed language/validity checks
   - `unknown_after_break` — catch-all; section was not filtered but did not
     survive to disk (investigate further)

7. **Re-apply exclude patterns (if supplied).** For documents with no
   sectionized output file, the verifier checks raw title + body text against
   `--exclude-patterns` / `--exclude-file`. Matches are counted under
   `excluded_by_pattern` (separate from `skipped_missing_sect`).

## Output

### Console tables

Three Rich tables are printed:

**`Sectionization audit (sampled)`**

| Metric | Value |
|--------|-------|
| Sampled docs | N |
| Audited (sect file found) | n |
| Skipped (no sect file) | n |
| Excluded by pattern | n |
| Errors | n |
| Sections (raw) | n |
| Sections present | n |
| Sections missing | n |
| Section loss % | x.xx |
| Raw content chars | n |
| Missing content chars | n |
| Content loss % | x.xx |

**`Missing sections by attributed reason`** — reason, count, % of missing.

**`Excluded-by-pattern breakdown`** — pattern string, docs excluded. Only
printed when `--exclude-patterns` / `--exclude-file` is supplied and at least
one document matched.

### JSON report (`--report-json`)

Written when `--report-json PATH` is supplied. Top-level keys:

```jsonc
{
  "raw_dir": "…",
  "sect_dir": "…",
  "sampled": 1000,
  "audited": 870,
  "skipped_missing_sect": 95,
  "excluded_by_pattern": 35,
  "errors": 0,
  "sections_total": 12450,
  "sections_present": 11800,
  "sections_missing": 650,
  "raw_chars": 45000000,
  "missing_chars": 1200000,
  "loss_pct": 2.67,
  "section_loss_pct": 5.22,
  "missing_by_reason": {
    "unneeded_skip_remaining": 380,
    "noise_header": 120,
    "non_substantive": 95,
    "unknown_after_break": 55
  },
  "excluded_by_pattern_reasons": {
    "nanoparticle synthesis": 22,
    "quantum dot": 13
  }
}
```

With `--include-docs`, a `"docs"` array is added — one entry per sampled
document including `corpus_id`, `title`, per-section detail, and `error` (if
any).

## Reading the Results

- **`loss_pct` vs `section_loss_pct`**: `loss_pct` is the share of raw
  *characters* that went missing; `section_loss_pct` is the share of raw
  *sections*. Sections filtered by the quality gates (noise, too short,
  non-English) appear in `missing_by_reason` and are expected loss — they are
  working as designed.

- **`unknown_after_break`** is the diagnostic catch-all. A non-trivial count
  here means sections passed all known filters but still didn't survive to
  disk. Investigate: check for duplicate canonical headers (silent overwrites),
  `_normalize_text` over-stripping, or encoding issues. This is the bug class
  the production `sectionization_report.json` cannot surface.

- **`skipped_missing_sect`** without `excluded_by_pattern` context means the
  sectionizer produced no output file for that document at all — could be a
  genuine failure (empty body, no valid sections) or an earlier crash mid-run.
  Cross-reference with `failures.json` in the sectionized directory.

- **`excluded_by_pattern`** are *expected* omissions when `--exclude-file` was
  used during sectionization. They are not content loss. Pass the same patterns
  to the verifier so they are separated out correctly.

- **`--fail-threshold`**: useful in CI to gate a pipeline on `loss_pct`. Exit
  code 1 when the threshold is exceeded. A threshold of 5.0 is a reasonable
  starting point for s2orc corpora.

## Relationship to `sectionization_report.json`

These two systems answer different questions (see `AGENTS.md` —
"Sectionization reporting vs. verification"):

| | `sectionization_report.json` | `verify-sectionization` |
|---|---|---|
| When produced | During every sectionization run | Standalone, after the run |
| Coverage | All docs (corpus-complete) | Sampled (configurable) |
| What it checks | What the sectionizer *decided* | What actually *hit disk* |
| Bug class caught | Drops the sectionizer knew about | Silent overwrites, truncation, encoding drift |
| Cost | Zero extra IO | Reads shard + output files |

Use `sectionization_report.json` for cheap corpus-wide stats during or after
every run. Reach for `verify-sectionization` to investigate content loss, or
as a validation gate before shipping a sectionizer change.

## Common Pitfalls

- **Mismatched sharding**: `RAW_DIR` and `SECT_DIR` must both use the
  last-two-digits bucket layout (`_sharded_path`, `verify.py:343`). Passing
  an unrelated `SECT_DIR` gives a near-100% `skipped_missing_sect` count —
  check that file counts roughly agree before reading results.

- **Exclude patterns mismatch**: `--exclude-patterns` / `--exclude-file` must
  match exactly what was used during sectionization. Different patterns will
  mis-bucket documents between `excluded_by_pattern` and
  `skipped_missing_sect`.

- **`-n 0` on large corpora**: auditing every document in a corpus of hundreds
  of thousands of docs is slow (reads all shards + all output files). Reserve
  for small dirs or final release gates.

- **v1 vs v2 shape**: `_normalize_to_v2` handles both automatically, but the
  raw dir must be homogeneous (all v1 or all v2). Mixed layouts are not
  supported.

## Relevant Files

- `src/araiadoc/processing/verify.py:453` — Click entry point
  (`verify_sectionization`)
- `src/araiadoc/processing/verify.py:103` — ground-truth reconstruction
  (`_build_ground_truth_sections`)
- `src/araiadoc/processing/verify.py:159` — drop-reason attribution
  (`_diagnose_missing`)
- `src/araiadoc/processing/verify.py:379` — reservoir sampling for gz shards
  (`_reservoir_sample_gz_docs`)
- `src/araiadoc/sectionize_report.py` — `DROP_REASONS` vocabulary (on-disk
  contract; renames are breaking changes)
- `AGENTS.md` — "Sectionization reporting vs. verification"
