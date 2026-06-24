# Auditing & Verification

To maintain data integrity across thousands of documents, `araiadoc` provides two distinct auditing systems: **internal run reports** and **external round-trip verification**. These systems solve different problems and are not interchangeable.

---

## Internal Reporting vs. Round-Trip Verification

### Sectionization Reports (Internal Accounting)

Every execution of `section-dataset-*` automatically creates a `sectionization_report.json` (aggregate statistics) and a `sectionization_report.jsonl.gz` (per-document breakdown) in the output folder.

- **Purpose:** Fast, corpus-complete summary of item-level sectionizer choices. It details kept or dropped sections and characters grouped by reason (`DROP_REASONS`).
- **Limitation:** It is purely internal. It tracks what the sectionizer *decided* to do, but cannot detect downstream bugs where section content was truncated, mangled in encoding, or overwritten on disk.

### Round-Trip Audit (Verification)

The standalone CLI command `verify-sectionization` is an external verification tool.

```bash
araiadoc verify-sectionization RAW_DIR SECT_DIR [OPTIONS]
```

- **Purpose:** Checks the actually written files on disk. It reads a random sample of sectionized outputs, reconstructs the expected ground-truth sections *directly* from raw paragraph/header span coordinates, and verifies that the first 50 characters of each expected section successfully substring-matches into the written outputs.
- **When to use:** Run `verify-sectionization` before trusting any sectionizer modifications, or during "content-loss" investigations to verify files were written correctly.

**Example:**
```bash
araiadoc verify-sectionization data/s2orc_v2_shards data/sectionized_out -n 1000 --fail-threshold 5.0
```

---

## Detailed Report Rows (`--detailed-report`)

By default, per-doc rows in `sectionization_report.jsonl.gz` do not detail individual section structures to save space. Specifying the `--detailed-report` flag adds a detailed `sections` block:

```json
"sections": [
  {"header": "Introduction", "chars": 1500, "paragraphs": 3, "outcome": "kept"},
  {"header": "Acknowledgements", "chars": 200, "paragraphs": 1, "outcome": "unneeded_skip_remaining"}
]
```

- **Performance Tip:** Threading this info is designed to be free when the flag is disabled. The helper `_hdr(name)` returns the header string only when `capture_section_detail=True`, and `None` otherwise.
- **Code Convention:** When adding new `record_kept()` or `record_dropped()` call sites in `sectionize.py` or other pipelines, you must pass `header=_hdr(name)` or the section will be omitted from the detailed reports.

---

## Failures & Title Recovery (`failures.json`)

If a document fails to parse, it is recorded in `failures.json` along with its corpus ID, titles, external IDs, and error traces.

Recovering titles can be challenging because `s2orc_v2` has no top-level `title` key, and `s2orc_v1` embeds it inside annotations. `araiadoc` uses robust title-recovery helpers in `sectionize.py`:

1. `_best_effort_title(doc)`: Tries looking up (1) top-level `title`, (2) projected annotation spans (`title`, `papertitle`, `paper_title`, `doctitle`), or (3) the first non-empty line of the text body. It is fully wrapped in error handling and safe to run on `None` or partial documents.
2. `_best_effort_external_ids(doc)`: Extracts any available `externalids`/`external_ids` (removing `None` values) so that DOIs or ArXiv IDs survive to the failure log even if a title cannot be recovered.

**Code Convention:** When catching exceptions inside workers (`_sectionize_one_file*` or `_sectionize_batch_file*`), bind the document reference to a variable declared *outside* the `try` block so it is accessible in the `except` handler for the title recovery call.

---

## Drop Reasons Contract

The reasons for excluding or truncating content are defined under the `DROP_REASONS` vocabulary in `sectionize_report.py`.

Because these reasons are rendered directly into the console tables and written as keys in the on-disk report files, **renaming any of these keys is a breaking change for downstream aggregation tools**.

### Historical Rename Notice

- **Old Key:** `unneeded_skip_truncation`
- **New Key:** `unneeded_skip_remaining` (aligns with `unneeded_sections_skip_remaining` in `text_quality/content_assessment.py`). This counts only the section that triggered the discard; any trailing truncated content is logged as `post_break_truncated`.
