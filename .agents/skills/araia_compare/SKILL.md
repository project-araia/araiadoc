---
name: araia-compare
description: Compare two araiadoc datasets (typically two sectionized corpus directories or two ID lists) to surface overlap, cloning, drift, or mislabeling. Query context is optional — supply a query identifier from src/araiadoc/searches.py to additionally check whether each dir is a plausible subset of that query's results.
---

# `araia-compare` Skill

Diff two datasets to surface accidental cloning, packaging bugs,
unexpected overlap or divergence between corpora, and stale snapshots.
Each invocation appends a new dated round to `araia_compare.md` at the
repo root.

If you want to evaluate a **single corpus against its source Solr
query**, use the `araia-review` skill instead. The two skills are
deliberately separate.

Use this skill any time the user asks to:

- "are these two dirs actually different?",
- "compare `<dir1>` and `<dir2>`",
- "diff the resilience vs utility corpora",
- "did sectionization mislabel the output?", or
- "what's the overlap between these two ID lists?".

## Inputs the user must supply (or infer from context)

1. **Two datasets to compare.** Each can be either:
   - a directory tree of per-paper sectionized `.json` files
     (`data/<name>_sectionized/<bucket>/<corpus_id>.json`), or
   - an `ids.txt`-style file (one corpus_id per line), or
   - a raw JSONL.GZ batches directory (legacy schema; treat each record's
     `corpus_id` as the identity).
2. **(Optional) A query identifier** from `src/araiadoc/searches.py`
   (`q`, `q2_chunks`, etc.). If supplied, the skill also reports whether
   each dataset's IDs are subsets / supersets / disjoint with the
   expected ID list for that query, when an ID list for it is available
   on disk (e.g. `data/titanv_all_*_results_*/.../ids.txt`).
3. **(Optional) sample size N** (default 30) for the byte-equality check
   on overlapping IDs.

## Output

Append a new dated section to `araia_compare.md` at the repo root:

```
## Round N — YYYY-MM-DD

### Datasets compared
- A: <path>  (kind: sectionized-dir | ids.txt | jsonl.gz)
- B: <path>  (kind: …)
- Query context (optional): <q identifier>

### File-system level
- File counts
- Sizes on disk
- Inode distinctness

### ID overlap
- |A|, |B|, |A ∩ B|, |A ∪ B|, |A − B|, |B − A|
- Jaccard

### Byte-equality of overlapping files
- For sectionized dirs: hash K random files present in both dirs;
  report N/K identical.

### Query cross-reference (only if a query context was supplied)
- |A ∩ Q-ids|, |B ∩ Q-ids|, |Q-ids − A|, |Q-ids − B|
- Verdict: A and B are both subsets / one is a clone of Q / one is
  disjoint / etc.

### Findings
- Numbered list of conclusions (e.g. "the two dirs are byte-identical
  clones", "B contains the wrong corpus", "A has 17 k more IDs than B
  because of download attrition").

### Open questions for next round
- e.g. "should the bad clone be deleted?", "where is the missing
  upstream data?".

### Relevant files
- both dataset paths
- any ids.txt referenced
- this SKILL.md
```

Do **not** rewrite earlier rounds — only append.

## Step-by-step procedure

### 1. Identify and capture totals for each dataset

For a sectionized dir:

```bash
find <dir> -name '*.json' -not -name 'failures.json' | wc -l
du -sh <dir>
```

For an `ids.txt`:

```bash
wc -l <ids.txt>
```

For a JSONL.GZ batches dir:

```bash
ls <dir>/*.jsonl.gz | wc -l
du -sh <dir>
```

### 2. Extract the ID set from each dataset

Sectionized-dir IDs:

```python
import os, glob
def ids_in(root):
    return {os.path.basename(f).replace('.json','')
            for f in glob.glob(f'{root}/*/*.json')
            if not f.endswith('failures.json')}
```

`ids.txt` IDs:

```python
ids = set(open(path).read().split())
```

JSONL.GZ IDs:

```python
import gzip, json
def ids_in_batches(dir_):
    ids = set()
    for gz in glob.glob(f'{dir_}/*.jsonl.gz'):
        with gzip.open(gz, 'rt') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    cid = rec.get('corpus_id') or rec.get('corpusid')
                    if cid:
                        ids.add(str(cid))
                except Exception:
                    pass
    return ids
```

### 3. Set-theory cross-reference

```python
A, B = ids_in(dir1), ids_in(dir2)
print(f'|A|={len(A)}  |B|={len(B)}')
print(f'|A ∩ B|={len(A & B)}  |A ∪ B|={len(A | B)}')
print(f'|A − B|={len(A - B)}  |B − A|={len(B - A)}')
jacc = len(A & B) / max(1, len(A | B))
print(f'Jaccard={jacc:.4f}')
```

### 4. Byte-equality of overlapping files (sectionized dirs only)

This is the **most-important sanity check**. Earlier rounds discovered
two corpora that were byte-identical clones. Run it every time.

```python
import hashlib, random, os
random.seed(7)
overlap = sorted(A & B)
sample = random.sample(overlap, min(30, len(overlap)))
identical = 0
diffs = []
for cid in sample:
    bucket = cid[-2:].zfill(2)  # or however the dir is sharded
    fa = f'{dir1}/{bucket}/{cid}.json'
    fb = f'{dir2}/{bucket}/{cid}.json'
    ha = hashlib.md5(open(fa, 'rb').read()).hexdigest()
    hb = hashlib.md5(open(fb, 'rb').read()).hexdigest()
    if ha == hb:
        identical += 1
    else:
        diffs.append(cid)
print(f'{identical}/{len(sample)} byte-identical; diffs: {diffs[:5]}')
```

If 30/30 match: declare the two dirs clones in the findings.
If some match: report the rate and flag candidates for inspection.

### 5. (Optional) Query cross-reference

Only if the user supplied a query identifier. Look for a corresponding
`ids.txt` on disk:

```bash
find data -maxdepth 5 -type f \( -name 'ids.txt' -o -name '*_ids.txt' \) | head
```

Map common queries to their canonical ID lists:

- `q` (all-weather) →
  `data/titanv_all_weather_results_*/all_weather/ids.txt`
- `q2_chunks` (all-utility) →
  `data/titanv_all_utility_results_*/all_utility/ids.txt`
  (or the user-built `data/utility_ids.txt` derived from the sectionized
  utility corpus).

Cross-reference:

```python
Q = set(open(query_ids_path).read().split())
print(f'A ⊆ Q? {A.issubset(Q)}  (A − Q = {len(A - Q)})')
print(f'B ⊆ Q? {B.issubset(Q)}  (B − Q = {len(B - Q)})')
print(f'Q ∩ A only: {len(Q & A - B)}')
print(f'Q ∩ B only: {len(Q & B - A)}')
```

This is how Round 2 caught that both `*_06-15_sectionized/` dirs were
subsets of the **weather** ID list and disjoint from the **utility** ID
list, regardless of their folder names.

### 6. Findings

State the bottom line plainly. Useful templates:

- "A and B are **byte-identical clones** (30/30 hash match)."
- "A is a **strict subset** of B (|A − B| = 0, |B − A| = N)."
- "A and B are **disjoint** (Jaccard = 0)."
- "Both A and B are subsets of the `q` ID list (`A − Q-ids = 0`,
  `B − Q-ids = 0`); the directory labelled `<name>` does not contain
  the corpus its name implies."
- "B has K more IDs than were eventually sectionized; the gap is
  download attrition / failures.json / language filtering."

### 7. Open questions

End each round with concrete next-iteration questions, e.g.:

- "should the bad clone be deleted?",
- "rebuild B from its real upstream?",
- "where did the K missing docs go?".

### 8. Append to `araia_compare.md`

Use `edit` to append the new round below the last round. Do **not**
overwrite the file. Increment the round number. Date is today.

## Notes and lessons learned (carry these into every round)

These lessons are intentionally duplicated in `araia-review`/SKILL.md
because both workflows need them.

- **The two-folder-identity bug:** in an earlier round,
  `resilience_06-15_sectionized` and `utility_06-15_sectionized` were
  byte-identical clones (75,681 files each, 2.5 GB each, 30/30 MD5
  match on random sample). Always run the cloning check in step 4
  before drawing any conclusions about precision or content.
- **A directory's name lies more often than you'd expect.** The
  `utility_06-15_sectionized/` folder was actually weather data. Use
  the ID-list cross-reference (step 5) whenever a query identifier is
  available.
- **The sectionized JSON schema is flat** (`title` + one key per
  section header). There is no nested `sections` dict, no separate
  `abstract` field guaranteed — the abstract is just whatever section
  sorts first (often `introduction` or `abstract`).
- **Word boundaries always**, lowercased for case-insensitive terms,
  case-sensitive for acronyms. Substring matching falsely scored hits
  on `iso` (inside *isolate*, *isotope*), `feeder` (nematode feeder
  guilds), `frost` (the surname), and `MWh`/`kWh` units in chemistry
  papers. Relevant when computing topical overlap signals between two
  corpora.
- **Legacy vs v2 schema:** raw batches under
  `titanv_all_*_results_*/all_*/batches/*.jsonl.gz` are in the legacy
  Solr schema (`corpus_id`, `paragraph` [list], `sectionheader` [list]).
  Per `AGENTS.md`, do **not** run the v2 sectionizer on them. When
  computing IDs from these, use `corpus_id` (with underscore), not
  `corpusid`.
- **Failures file:** every sectionized dir contains a `failures.json`
  at the top level. Always exclude it from ID extraction and counts.
