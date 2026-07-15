---
name: araia-review
description: Review a single sectionized araiadoc corpus against the Solr boolean query in src/araiadoc/searches.py that was supposed to generate it. Judge topical fit, surface recurring failure modes, and feed insights back into iterating the literal query.
---

# `araia-review` Skill

Iterative workflow for judging how well a literal Solr query in
`src/araiadoc/searches.py` matches the topical *intent* of the sectionized
corpus it produced. Each invocation appends a new dated round to
`araia-review.md` at the repo root.

If you instead want to compare **two corpora to each other** (overlap,
cloning, divergence), use the `araia-compare` skill. The two skills are
deliberately separate.

Use this skill any time the user asks to:

- "review the resilience / utility / weather corpus",
- "compare the sectionized data to the q / Q2 / q2_chunks query",
- "do another round of araia review", or
- "sample N docs from `<dir>` and tell me if they fit `<query>`".

## Inputs the user must supply (or infer from context)

1. **One corpus directory.** Resolution order (use the first that applies):
   a. A path the user mentioned **in the conversation before invoking the
      skill** — check the message history for any directory path (absolute
      or relative to the repo root) that looks like a sectionized corpus.
      Prefer an explicit path over any inferred one.
   b. A path inferable from context (e.g. the user said "the resilience
      corpus" and only one `*resilience*_sectionized` dir exists under
      `data/` or at the repo root).
   c. **Fallback only:** scan `data/` and the repo root for
      `*_sectionized` directories and ask the user to confirm which one to
      use before proceeding.

   The directory is a tree of per-paper sectionized `.json` files like
   `data/<name>_sectionized/<bucket>/<corpus_id>.json`. The schema produced
   by `sectionize.py` is flat:
   `{title: str, "<section_header>": "<concatenated paragraph text>", …}`.
2. **One query identifier** from `src/araiadoc/searches.py` (e.g. `q`,
   `q2_chunks`, `Q2_AND_BLOCK`).
3. **Sample size N** (default 10) and whether sampling should be
   reproducible (`random.seed(...)`) or truly random (no seed).
4. **Comparison axis:** topical fit (the usual answer) vs literal-term fit.
   Topical fit means: read title + section headers + first-section snippet
   and judge whether the paper looks like the kind of paper the query was
   *trying* to find, even if a specific term happens not to appear.

## Output

Append a new dated section to `araia-review.md` at the repo root with this
structure:

```
## Round N — YYYY-MM-DD

### Methodology
- Sampling parameters (N, seed, dir, exclusions like `failures.json`)
- Schema check note
- Per-doc fields extracted (title, headers, snippet, hit groups)

### Sample — <dir>
| corpus_id | Title | <Query> groups hit | Context hits | Topical verdict | Notes |
(end the table with a summary line: `n ON-TOPIC, n BORDERLINE, n OFF-TOPIC
out of N` and both precision bounds — strict and generous)

### Broadened coverage check (optional)
- Larger N (e.g. 50) random sample
- Word-boundary hit rate against a curated shortlist

### False-positive drivers (recommended)
- Ranked table of which term/group fired in the OFF-TOPIC docs

### Findings
- Numbered list of conclusions

### Open questions for next round
- Followups, e.g. recompute precision after a query change, draft a tighter
  query, etc.

### Relevant files
- searches.py line refs for the query
- sectionize.py for the schema
- the corpus dir
- this SKILL.md
```

Do **not** rewrite earlier rounds — only append.

## Step-by-step procedure

### 1. Resolve and confirm the corpus dir, then capture totals

**Resolution order — stop at the first match:**

1. Any directory path the user stated in the conversation *before* invoking
   the skill (absolute or relative). Use it directly without scanning.
2. A name inferable from context (e.g. "the resilience corpus" →
   `data/*resilience*_sectionized/` or `./*resilience*_sectionized/`).
   Resolve to an absolute path and confirm with the user before proceeding.
3. **Fallback only:** list `data/*_sectionized/` and repo-root
   `./*_sectionized/` directories, report them, and ask the user which one
   to use.

Once the path is settled, confirm it exists and capture totals:

```bash
find <dir> -name '*.json' -not -name 'failures.json' | wc -l
du -sh <dir>
```

### 2. Read `searches.py` and extract the query

Use `read` on `src/araiadoc/searches.py`. Distill the query into a small
Python dict of *hazard / utility groups*, one bucket per OR-block, so the
table in the review is readable. Example for `q`:

```python
RES_TERMS = {
  'heat':    ['extreme heat','heat wave','heatwave','heat stress','heat index','urban heat island','high temperature'],
  'cold':    ['cold wave','cold spell','winter storm','frost','snowstorm','ice storm','blizzard','freeze'],
  'flood':   ['flood','flash flood','inundation','storm surge','heavy precipitation','extreme rainfall'],
  'drought': ['drought','water scarcity'],
  'fire':    ['wildfire','forest fire','bushfire','wildland fire','wildfire smoke','fire weather'],
  'tc':      ['tropical cyclone','hurricane','typhoon'],
  'severe':  ['thunderstorm','hail','tornado','downburst','microburst','extreme wind'],
  'sea':     ['sea level rise','coastal erosion','saltwater intrusion','ocean warming','marine heatwave','ocean acidification'],
  'cryo':    ['sea ice loss','glacial melt','permafrost thaw','arctic sea ice'],
  'crop':    ['crop failure','crop yield','co2 fertilization','carbon dioxide fertilization'],
}
```

For `q`, drop or down-weight the second AND-block boilerplate terms
(`climate`, `weather`, `risk`, `infrastructure`, …) when counting hits —
they fire on almost every paper and are not useful signal.

For utility reviews, do **not** treat `Q2_AND_BLOCK` as boilerplate. The
production utility query is `(q2_chunks OR ...) AND Q2_AND_BLOCK AND NOT
Q2_NOT_BLOCK` for local s2orc (`src/araiadoc/collection/s2orc.py`) and the
TitanV path uses `Q2_AND_BLOCK` as a required Solr filter query. Its terms
(`electricity`, `power grid`, `substation`, `kWh`, `MWh`, `feeder`, `ISO`,
etc.) are required utility anchors and often the exact terms whose false
positives need to be diagnosed. For the utility corpus, score both the
20 `q2_chunks` groups and the `Q2_AND_BLOCK` anchors, while keeping
`Q2_NOT_BLOCK` in mind as the exclusion template.

### 3. Sample N files (file-level, truly random unless told otherwise)

```python
import random, glob, os
random.seed()  # or fixed seed if user asked for reproducibility
files = [f for f in glob.glob(f'{root}/*/*.json') if not f.endswith('failures.json')]
sample = random.sample(files, N)
```

### 4. Extract fields per sampled doc

For each file, load the JSON and pull:

- `title`
- list of section-header keys (everything that isn't `title`)
- the first non-title section's text (truncated ~1000 chars) as an
  abstract-substitute, since the s2orc_v2 sectionizer promotes pre-header
  paragraphs into an `abstract` or `introduction` key.

### 5. Term-hit scoring — **use word boundaries**

Substring matching produces too many false positives (`iso` inside
*isolate*, `feeder` inside *nematode feeder*, `frost` inside the surname
*Robert Frost*, `MWh`/`kWh` inside chemistry papers' units). Always:

```python
import re
def hit_groups_wb(text, groups):
    text = text.lower()
    found = {}
    for g, terms in groups.items():
        hits = [t for t in terms if re.search(r'\b' + re.escape(t.lower()) + r'\b', text)]
        if hits:
            found[g] = hits[:5]
    return found
```

For unit/acronym tokens (`SAIDI`, `kWh`, `NERC`) prefer **case-sensitive**
matching against the original (not lowercased) text. Keep those tokens in a
separate acronym/unit list so the lowercasing helper above does not erase
useful case distinctions (`ISO` vs `iso` inside *isolate*, `MWh`/`kWh` as
energy units vs unrelated text).

### 6. Optional: broadened coverage check

If the per-doc hits are surprisingly sparse, draw a larger (e.g. N=50)
random sample and report the rate of docs with ≥1 query-shortlist hit in
the dir. This separates "the query intent is wrong" from "this dir just
doesn't contain that intent at all".

### 7. Topical verdict (the actual answer)

For each doc, assign one of: `ON-TOPIC`, `BORDERLINE`, `OFF-TOPIC`, judged
on title + headers + snippet against the *intent* of the query (not just
which literal terms hit). Note in the table when a hit is clearly a false
positive (e.g. "chip flooding" in a petroleum-recovery paper).

### 8. Roll up findings

Per-dir summary line of the form `n ON-TOPIC, n BORDERLINE, n OFF-TOPIC`
out of N. State an estimated precision as **two numbers**:

- **strict precision** = `ON-TOPIC / N` (BORDERLINE counted as misses), and
- **generous precision** = `(ON-TOPIC + BORDERLINE) / N`.

Reporting both bounds is important: a large gap between them means the
corpus is heavy on *adjacent* (borderline) papers rather than cleanly on- or
off-topic, and a single number would hide that.

**Rank the false-positive drivers.** After assigning verdicts, count which
term/group fired in each OFF-TOPIC doc and sort descending. This single
table is the most actionable output of the round — it tells the next
iteration exactly which terms to tighten or drop. A `collections.Counter`
over the OFF-TOPIC docs' hit groups does the job.

Note recurring failure modes you saw (boilerplate `AND` terms, unit
substring hits, false-positive technical jargon clashes) — these become
inputs for the next iteration of the literal query.

**Tip — drive the verdicts from a single in-memory list.** With large N it
is far easier to hold the per-doc rows as a list of tuples
`(cid, title_stub, hits_str, context_hits_str, verdict, note)` in one script,
then derive the verdict tallies, the precision bounds, and the FP-driver
Counter from that same list. This keeps the markdown table, the summary line,
and the FP ranking consistent (they all come from one source of truth) and
avoids re-deriving verdicts by hand.

### 9. Open questions

End each round with concrete next-iteration questions, e.g.:

- "should `q` drop its AND-block entirely and rely on the hazard-OR plus
  a `NOT`-block?"
- "should `Q2` require ≥2 distinct chunks to fire?"

### 10. Append to `araia-review.md`

Use `edit` to append the new round below the last round. Do **not**
overwrite the file. Increment the round number. Date is today.

## Notes and lessons learned (carry these into every round)

These lessons are intentionally duplicated in `araia-compare`/SKILL.md
because both workflows need them.

- **Word boundaries always**, lowercased for case-insensitive terms,
  case-sensitive for acronyms. Substring matching falsely scored hits on
  `iso` (inside *isolate*, *isotope*), `feeder` (nematode feeder guilds),
  `frost` (the surname), and `MWh`/`kWh` units in chemistry papers.
- **The sectionized JSON schema is flat** (`title` + one key per section
  header). There is no nested `sections` dict, no separate `abstract`
  field guaranteed. Use the first non-title key in insertion order as an
  abstract-like snippet source (often `abstract` or `introduction`); do not
  alphabetically sort section keys.
- **The `q` AND-block is near-vacuous** as a filter — `risk`, `recovery`,
  `disaster`, `infrastructure`, `response` are in nearly every paper.
- **`Q2_NOT_BLOCK` and similar filter lists are iterative artifacts.** The
  current `Q2_NOT_BLOCK` in `src/araiadoc/searches.py` is an exclusion
  template built from recurring false-positive domains (genomics, clinical
  medicine, chemical engineering, spectroscopy, astronomy/particle physics,
  fusion/plasma physics, materials science, battery electrochemistry, etc.).
  Treat this kind of filter file / NOT-block as something to improve after
  each review round: promote repeated OFF-TOPIC drivers into the exclusion
  list, tighten ambiguous phrases, and preserve useful historical exclusions
  unless the sample shows they are suppressing true positives. When proposing
  a `NOT`-block for `q`, start from `Q2_NOT_BLOCK` plus any recurring
  false-positive clusters that the current round surfaced.
- **Utility query context matters.** `Q2_AND_BLOCK` is not analogous to the
  broad `q` AND-block. It is a required utility-anchor filter in both the
  local s2orc and TitanV paths, so score it during utility reviews rather
  than dropping it as boilerplate.
- **Report strict AND generous precision** (see step 8). The gap between them
  *is* the BORDERLINE rate and is itself a finding.
- **Always check whether the dir you are reviewing is the one you think
  it is.** Earlier rounds discovered that `utility_06-15_sectionized/`
  was actually a clone of `resilience_06-15_sectionized/`, not a `Q2`
  result set. Before drawing conclusions about a query's precision,
  spot-check that the directory's IDs are actually a subset of the
  query's expected ID list (see `araia-compare` for the procedure).
- **A persistently low strict precision can itself be a provenance signal.**
  If a corpus scores poorly across rounds and its name does not map to a
  known run for the query under review, suspect it was not produced by that
  query at all (e.g. a general s2orc slice). Resolve provenance (run logs,
  ID-list overlap via `araia-compare`) *before* concluding the query is at
  fault — you cannot evaluate a query against a corpus it did not generate.
