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
