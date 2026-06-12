"""Commands for downloading and querying the Semantic Scholar s2orc_v2 bulk dataset.

Two top-level commands are provided:

  download-s2orc   -- Download all shards of s2orc_v2 from the S2 Datasets API
                      with resume support (already-present shards are skipped).

  get-from-local-s2orc -- Query a local s2orc_v2 download using DuckDB, producing
                           per-document JSON files in the same layout that
                           section-dataset-s2orc expects as input.  Supports:
                             * lookup by corpus ID (--source CSV/JSON of IDs)
                             * full-text keyword search (--query SQL ILIKE pattern)
                             * pre-defined weather/utility searches (--all-weather /
                               --all-utility) whose terms mirror the Solr queries
                               used by the old get-from-titanv command.
"""

import gzip
import json
import re
import time
from pathlib import Path

import click
import requests
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from araiadoc.searches import Q2_AND_BLOCK, Q2_NOT_BLOCK, q, q2_chunks
from araiadoc.utils import _build_session, _prep_output_dir

# ---------------------------------------------------------------------------
# S2 Datasets API endpoints
# ---------------------------------------------------------------------------
_RELEASE_URL = "https://api.semanticscholar.org/datasets/v1/release/latest"
_DATASET_URL = "https://api.semanticscholar.org/datasets/v1/release/{release_id}/dataset/s2orc_v2/"

# ---------------------------------------------------------------------------
# download-s2orc
# ---------------------------------------------------------------------------


def _download_shard(url: str, dest: Path, session: requests.Session, progress, task):
    """Stream-download *url* to *dest*, updating *task* every 10 MB."""
    MB = 1024 * 1024
    # timeout=(connect_s, read_s): 30 s to establish, 300 s between chunks.
    with session.get(url, stream=True, timeout=(30, 300)) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        if task is not None and total:
            progress.update(task, total=total)
        with open(dest, "wb") as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=10 * MB):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if task is not None:
                        progress.update(task, advance=len(chunk))
    if total and downloaded != total:
        raise RuntimeError(f"Incomplete download: got {downloaded:,} bytes, expected {total:,}")


@click.command("download-s2orc")
@click.option(
    "--api-key",
    "-k",
    required=True,
    envvar="S2_API_KEY",
    help="Semantic Scholar API key (or set S2_API_KEY env var).",
)
@click.option(
    "--output-dir",
    "-o",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory in which to save the downloaded .gz shards.",
)
@click.option(
    "--shards",
    "-n",
    default=None,
    type=int,
    help="Download only the first N shards (omit to download all ~30).",
)
def download_s2orc(api_key: str, output_dir: Path, shards: int | None):
    """Download the Semantic Scholar s2orc_v2 bulk dataset.

    Each shard is a gzip-compressed JSONL file (~6 GB each, ~180 GB total).
    Already-present shards are skipped so the command is safely re-runnable.

    The API key can be supplied via --api-key or the S2_API_KEY environment
    variable.  Obtain a key at https://www.semanticscholar.org/product/api
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    session = _build_session()

    click.echo("* Fetching latest release ID …")
    r = session.get(_RELEASE_URL, timeout=30)
    r.raise_for_status()
    release_id = r.json()["release_id"]
    click.echo(f"* Release: {release_id}")

    def fetch_manifest() -> list[str]:
        """Re-fetch the manifest to get fresh presigned URLs."""
        url = _DATASET_URL.format(release_id=release_id)
        resp = session.get(url, headers={"x-api-key": api_key}, timeout=60)
        resp.raise_for_status()
        return resp.json()["files"]

    files = fetch_manifest()

    if shards is not None:
        files = files[:shards]

    click.echo(f"* {len(files)} shard(s) to download → {output_dir}")

    # Persist the manifest so the sectionizer can find the files later.
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"release_id": release_id, "files": files}, indent=2))

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        dl_task = progress.add_task("[cyan]Overall", total=len(files))

        for shard_idx, file_url in enumerate(files):
            # Derive a stable local filename from the URL.
            # S2 URLs look like:
            #   https://ai2-s2ag.s3.amazonaws.com/staging/<release>/s2orc_v2/<shard>.gz?<token>
            # Strip the query string first, then take the last path component.
            clean_url = file_url.split("?")[0]
            shard_name = clean_url.rsplit("/", 1)[-1]
            dest = output_dir / shard_name

            if dest.exists():
                # Validate size against Content-Length before skipping.
                # S3 presigned URLs are method-bound (signed for GET only) and
                # return no Content-Length on HEAD, so fall back to a streaming
                # GET that we close immediately after reading the headers.
                expected = 0
                head = session.head(file_url, timeout=30)
                if head.headers.get("Content-Length"):
                    expected = int(head.headers["Content-Length"])
                else:
                    probe = session.get(file_url, stream=True, timeout=30)
                    expected = int(probe.headers.get("Content-Length", 0))
                    probe.close()
                if expected and dest.stat().st_size == expected:
                    progress.log(f"* Skipping {shard_name} (already complete)")
                    progress.update(dl_task, advance=1)
                    continue
                if not expected:
                    progress.log(
                        f"* Skipping {shard_name} "
                        f"(server did not report size: local file is {dest.stat().st_size:,} bytes)"
                    )
                    progress.update(dl_task, advance=1)
                    continue
                progress.log(
                    f"* Re-downloading {shard_name} " f"(size mismatch: {dest.stat().st_size:,} vs {expected:,})"
                )
                dest.unlink()

            progress.log(f"* Downloading {shard_name} …")
            shard_task = progress.add_task(f"[white]{shard_name}", total=None)

            # Download to a .part file and atomically rename on success.  This
            # prevents the next invocation from skipping a half-written shard:
            # only fully-downloaded files end up at the final path.
            part_dest = dest.with_suffix(dest.suffix + ".part")
            success = False
            current_url = file_url
            for attempt in range(5):
                try:
                    _download_shard(current_url, part_dest, session, progress, shard_task)
                    part_dest.rename(dest)
                    success = True
                    break
                except Exception as exc:
                    progress.log(f" ! Attempt {attempt + 1}/5 failed: {exc}")
                    # Clean up any partial bytes before retrying.
                    if part_dest.exists():
                        try:
                            part_dest.unlink()
                        except OSError:
                            pass
                    if attempt < 4:
                        time.sleep(5 * (attempt + 1))
                        # Refresh the presigned URL — the previous one may have
                        # expired mid-download, which is the most common cause
                        # of repeated failures on a single shard.
                        try:
                            current_url = fetch_manifest()[shard_idx]
                            progress.log(" * Refreshed presigned URL for retry.")
                        except Exception as refresh_exc:
                            progress.log(f" ! Could not refresh URL: {refresh_exc}")

            if not success:
                progress.log(f" ! Giving up on {shard_name}.")

            progress.update(dl_task, advance=1)

    click.echo(f"* Done.  Shards saved to: {output_dir}")


# ---------------------------------------------------------------------------
# Helpers for get-from-local-s2orc
# ---------------------------------------------------------------------------


def _write_doc(doc: dict, output_dir: Path):
    """Write one s2orc_v2 document as a JSON file under a sharded directory."""
    corpus_id = str(doc.get("corpusid", "unknown"))
    shard = corpus_id[-2:] if len(corpus_id) >= 2 else corpus_id
    shard_dir = output_dir / shard
    shard_dir.mkdir(exist_ok=True)
    dest = shard_dir / f"{corpus_id}.json"
    if not dest.exists():
        dest.write_text(json.dumps(doc, ensure_ascii=False))
    return dest


# ---------------------------------------------------------------------------
# Solr-query boolean evaluator
# ---------------------------------------------------------------------------
# The Solr queries in searches.py use a small subset of the Solr/Lucene query
# language: parenthesised groups, the binary operators OR / AND, the unary
# prefix NOT (or '-' in front of a term), bare words (which Solr treats as
# whole-token matches), and double-quoted phrases (whole-phrase substring
# matches).
#
# For local execution against doc["body"]["text"] we approximate each leaf
# token as a case-insensitive word-boundary match via regex (``\\b``).
# This closely mirrors Solr's tokenised matching while still being
# efficient for one-pass scanning.
#
# Why not a single regex?  Because the Solr queries contain hundreds of terms
# and arbitrary nesting depth — a proper recursive-descent parser is the only
# way to get the boolean semantics right.
# ---------------------------------------------------------------------------


def _tokenize_solr(query_text: str):
    """Tokenise a Solr query string.

    Yields tuples: ("LPAREN",), ("RPAREN",), ("OP", "OR"|"AND"|"NOT"),
    ("TERM", text).  Whitespace is dropped.
    """
    pos = 0
    n = len(query_text)
    while pos < n:
        c = query_text[pos]
        if c.isspace():
            pos += 1
            continue
        if c == "(":
            yield ("LPAREN",)
            pos += 1
            continue
        if c == ")":
            yield ("RPAREN",)
            pos += 1
            continue
        if c == '"':
            end = query_text.find('"', pos + 1)
            if end == -1:
                # Unterminated quote — consume the rest as one term.
                yield ("TERM", query_text[pos + 1 :])  # noqa
                return
            yield ("TERM", query_text[pos + 1 : end])  # noqa
            pos = end + 1
            continue
        if c == "-":
            # Prefix NOT, only when applied directly to a term/group.
            yield ("OP", "NOT")
            pos += 1
            continue
        # Bare word — consume until whitespace, paren, or quote.
        start = pos
        while pos < n and not query_text[pos].isspace() and query_text[pos] not in '()"':
            pos += 1
        word = query_text[start:pos]
        if not word:
            pos += 1
            continue
        if word.upper() in {"OR", "AND", "NOT"}:
            yield ("OP", word.upper())
        else:
            yield ("TERM", word)


class _SolrParser:
    """Recursive-descent parser for a Solr-style boolean expression.

    Grammar:
      expr   := and_expr ("OR" and_expr)*
      and_expr := not_expr ("AND"? not_expr)*    # AND is implicit when absent
      not_expr := "NOT" not_expr | atom
      atom   := "(" expr ")" | TERM
    """

    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        node = self._parse_or()
        if self.pos != len(self.tokens):
            # Trailing tokens — fall back gracefully.
            pass
        return node

    def _parse_or(self):
        left = self._parse_and()
        while self._peek() == ("OP", "OR"):
            self._consume()
            right = self._parse_and()
            left = ("or", left, right)
        return left

    def _parse_and(self):
        left = self._parse_not()
        while True:
            tok = self._peek()
            if tok == ("OP", "AND"):
                self._consume()
                right = self._parse_not()
                left = ("and", left, right)
            elif tok and tok[0] in ("TERM", "LPAREN"):
                # Implicit AND between adjacent atoms (Solr default operator).
                right = self._parse_not()
                left = ("and", left, right)
            else:
                break
        return left

    def _parse_not(self):
        if self._peek() == ("OP", "NOT"):
            self._consume()
            return ("not", self._parse_not())
        return self._parse_atom()

    def _parse_atom(self):
        tok = self._peek()
        if tok is None:
            return ("term", "")
        if tok[0] == "LPAREN":
            self._consume()
            node = self._parse_or()
            if self._peek() and self._peek()[0] == "RPAREN":
                self._consume()
            return node
        if tok[0] == "TERM":
            self._consume()
            return ("term", tok[1])
        # Unexpected token — skip it and recurse.
        self._consume()
        return self._parse_atom()


def _eval_solr_ast(node, text_lower: str) -> bool:
    op = node[0]
    if op == "term":
        term = node[1].lower().strip()
        if not term:
            return True
        return bool(re.search(r"\b" + re.escape(term) + r"\b", text_lower))
    if op == "and":
        return _eval_solr_ast(node[1], text_lower) and _eval_solr_ast(node[2], text_lower)
    if op == "or":
        return _eval_solr_ast(node[1], text_lower) or _eval_solr_ast(node[2], text_lower)
    if op == "not":
        return not _eval_solr_ast(node[1], text_lower)
    return False


def _compile_solr_query(query_text: str):
    """Parse a Solr query once and return a predicate over s2orc_v2 docs."""
    ast = _SolrParser(_tokenize_solr(query_text)).parse()

    def predicate(doc):
        body = doc.get("body") or {}
        text_lower = (body.get("text") or "").lower()
        if not text_lower:
            return False
        return _eval_solr_ast(ast, text_lower)

    return predicate


def _build_solr_keyword_predicate(query_text: str):
    """Backward-compatible wrapper: compile a Solr query into a doc predicate."""
    return _compile_solr_query(query_text)


def _build_weather_predicate():
    """Predicate that mirrors the --all-weather Solr query (uses `q` from searches.py)."""
    return _compile_solr_query(q)


def _build_utility_predicate():
    """Predicate that mirrors the --all-utility Solr query.

    The Solr-side composition is:
      ANY(q2_chunks)  AND  Q2_AND_BLOCK  AND  NOT (Q2_NOT_BLOCK)
    """
    main_pred = _compile_solr_query(" OR ".join(f"({chunk})" for chunk in q2_chunks))
    and_pred = _compile_solr_query(Q2_AND_BLOCK)
    not_pred = _compile_solr_query(Q2_NOT_BLOCK)

    def predicate(doc):
        return main_pred(doc) and and_pred(doc) and not not_pred(doc)

    return predicate


def _solr_ast_to_sql(node) -> str:
    """Translate a Solr AST node to a DuckDB SQL WHERE clause.

    Operates on the ``body`` column (DuckDB STRUCT inferred from ndjson).
    Terms are matched case-insensitively via ``regexp_matches`` with
    word boundaries (``\\b``) to approximate Solr's token-level matching.
    """
    op = node[0]
    if op == "term":
        term = node[1].strip()
        if not term:
            return "TRUE"
        safe = term.lower().replace("'", "''")
        return f"regexp_matches(lower(COALESCE(body.text, '')), " f"'\\b{safe}\\b')"
    if op == "and":
        return f"({_solr_ast_to_sql(node[1])}) AND ({_solr_ast_to_sql(node[2])})"
    if op == "or":
        return f"({_solr_ast_to_sql(node[1])}) OR ({_solr_ast_to_sql(node[2])})"
    if op == "not":
        return f"NOT ({_solr_ast_to_sql(node[1])})"
    return "FALSE"


# ---------------------------------------------------------------------------
# Parallel scanning & DuckDB query helpers
# ---------------------------------------------------------------------------


def _scan_predicate_parallel(
    gz_files: list[Path],
    predicate,
    output_dir: Path,
    n_jobs: int = -1,
) -> tuple[int, int]:
    """Scan gzip shards in parallel with joblib.

    Each worker writes matching documents directly to *output_dir*.

    Returns ``(unique_written, skipped_duplicates)``.
    """
    from joblib import Parallel, delayed

    def _scan_one(gz: Path) -> list[str]:
        """Process one shard, write matches, return list of corpus IDs found."""
        found_ids: list[str] = []
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if predicate(doc):
                    _write_doc(doc, output_dir)
                    found_ids.append(str(doc.get("corpusid", "")))
        return found_ids

    click.echo(
        f"* Scanning {len(gz_files)} shard(s) with joblib " f"({n_jobs if n_jobs != -1 else 'all'} worker(s)) \u2026"
    )

    results = Parallel(n_jobs=n_jobs, verbose=10)(delayed(_scan_one)(gz) for gz in gz_files)

    seen: set[str] = set()
    written = 0
    skipped = 0
    for ids in results:
        for cid in ids:
            if cid in seen:
                skipped += 1
            else:
                seen.add(cid)
                written += 1

    return written, skipped


def _query_with_duckdb(
    gz_files: list[Path],
    query_text: str,
    output_dir: Path,
    label: str,
) -> int:
    """Use DuckDB to filter shards by *query_text* (Solr syntax).

    Translates the Solr AST to a DuckDB SQL WHERE clause, so the
    filtering happens inside the database engine rather than in
    Python.  Writes matching documents to *output_dir* and returns
    the count of unique documents written.
    """
    import duckdb

    click.echo(f"* DuckDB query ({label}) across {len(gz_files)} shard(s) \u2026")

    # Parse the Solr query and translate to a SQL WHERE clause
    ast = _SolrParser(_tokenize_solr(query_text)).parse()
    where_clause = _solr_ast_to_sql(ast)

    file_paths = [str(p) for p in gz_files]
    con = duckdb.connect()

    sql = f"""
        SELECT *
        FROM read_ndjson(?, compression='gzip', ignore_errors=true)
        WHERE {where_clause}
    """

    written = 0
    seen: set[str] = set()
    try:
        con.execute(sql, [file_paths])
        col_names = [desc[0] for desc in con.description]
        while True:
            row = con.fetchone()
            if row is None:
                break
            doc = dict(zip(col_names, row))
            cid = str(doc.get("corpusid", ""))
            if cid in seen:
                continue
            seen.add(cid)
            _write_doc(doc, output_dir)
            written += 1
    except Exception as exc:
        raise click.ClickException(f"DuckDB query failed: {exc}")
    finally:
        con.close()

    click.echo(f"* DuckDB returned {written} unique document(s).")
    return written


def _lookup_ids_parallel(ids: set, gz_files: list, output_dir: Path, n_jobs: int = -1):
    """Look up corpus IDs in parallel using joblib.

    Each worker reads a subset of shards and returns matching
    ``(corpus_id, doc)`` tuples.  The main thread deduplicates
    and writes.
    """
    from joblib import Parallel, delayed

    def _search_shard(gz: Path) -> list[tuple[str, dict]]:
        """Search one shard, return [(cid, doc), ...] for matching IDs."""
        found: list[tuple[str, dict]] = []
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cid = str(doc.get("corpusid", ""))
                if cid in ids:
                    found.append((cid, doc))
        return found

    click.echo(f"* Scanning {len(gz_files)} shard(s) with joblib (ID lookup) \u2026")

    results = Parallel(n_jobs=n_jobs, verbose=10)(delayed(_search_shard)(gz) for gz in gz_files)

    seen: set[str] = set()
    written = 0
    for found_list in results:
        for cid, doc in found_list:
            if cid not in seen:
                seen.add(cid)
                _write_doc(doc, output_dir)
                written += 1

    click.echo(f"* Done. {written}/{len(ids)} document(s) written.")
    if written < len(ids):
        click.echo(f"* {len(ids) - written} ID(s) missing from all shards.")


# ---------------------------------------------------------------------------
# get-from-local-s2orc
# ---------------------------------------------------------------------------


@click.command("get-from-local-s2orc")
@click.option(
    "--data-dir",
    "-d",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing the downloaded s2orc_v2 .gz shard files.",
)
@click.option(
    "--output-dir",
    "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for extracted JSON documents (created if absent).",
)
@click.option(
    "--source",
    "-s",
    default=None,
    type=click.Path(exists=True),
    help=("File of corpus IDs to look up: a JSON array of integers, or a .txt " "file with one integer ID per line."),
)
@click.option(
    "--all-weather",
    "-a",
    is_flag=True,
    help="Extract all documents matching the weather/climate keyword search.",
)
@click.option(
    "--all-utility",
    "-u",
    is_flag=True,
    help="Extract all documents matching the utility/electricity keyword search.",
)
@click.option(
    "--query",
    "-q",
    default=None,
    help=(
        "Ad-hoc Solr-style query string.  Quoted phrases and bare words are all "
        "required to appear in the document body (AND semantics)."
    ),
)
@click.option(
    "--use-duckdb",
    is_flag=True,
    default=False,
    help=(
        "Use DuckDB to scan the shards instead of pure-Python streaming.  "
        "Faster for corpus-ID lookups AND keyword/weather/utility queries; "
        "requires duckdb to be installed."
    ),
)
@click.option(
    "--jobs",
    "-j",
    default=-1,
    type=int,
    help="Number of parallel workers for shard scanning (-1 = all cores).",
)
def get_from_local_s2orc(
    data_dir: Path,
    output_dir: Path | None,
    source: str | None,
    all_weather: bool,
    all_utility: bool,
    query: str | None,
    use_duckdb: bool,
    jobs: int,
):
    """Extract documents from a local s2orc_v2 download.

    Use one of --source, --all-weather, --all-utility, or --query.

    Produces one JSON file per matching document, sharded by the last two
    digits of the corpus ID — the same layout consumed by section-dataset-s2orc.

    \b
    Examples:
      # Look up specific corpus IDs
      araiadoc get-from-local-s2orc -d /data/s2orc -s my_ids.json

      # Weather keyword search
      araiadoc get-from-local-s2orc -d /data/s2orc -o ./weather_docs --all-weather

      # Ad-hoc query
      araiadoc get-from-local-s2orc -d /data/s2orc -q '"adsorption refrigeration"'
    """
    if sum([bool(source), all_weather, all_utility, bool(query)]) != 1:
        raise click.UsageError("Provide exactly one of --source, --all-weather, --all-utility, or --query.")

    if output_dir is None:
        if all_weather:
            output_dir = _prep_output_dir("s2orc_weather_results")
        elif all_utility:
            output_dir = _prep_output_dir("s2orc_utility_results")
        else:
            output_dir = _prep_output_dir("s2orc_id_results")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"Output directory: {output_dir}")

    gz_files = sorted(data_dir.glob("*.gz"))
    if not gz_files:
        raise click.UsageError(f"No .gz shard files found in {data_dir}")
    click.echo(f"* Found {len(gz_files)} shard file(s).")

    # ------------------------------------------------------------------ #
    # Corpus-ID lookup                                                     #
    # ------------------------------------------------------------------ #
    if source:
        source_path = Path(source)
        if source_path.suffix == ".json":
            ids = {str(i) for i in json.loads(source_path.read_text())}
        else:
            ids = {line.strip() for line in source_path.read_text().splitlines() if line.strip()}

        click.echo(f"* Looking up {len(ids)} corpus ID(s).")

        if use_duckdb:
            _lookup_ids_duckdb(ids, gz_files, output_dir)
        else:
            _lookup_ids_parallel(ids, gz_files, output_dir, n_jobs=jobs)
        return

    # ------------------------------------------------------------------ #
    # Keyword / predicate search                                          #
    # ------------------------------------------------------------------ #
    if all_weather:
        predicate = _build_weather_predicate()
        label = "weather"
    elif all_utility:
        predicate = _build_utility_predicate()
        label = "utility"
    else:
        predicate = _build_solr_keyword_predicate(query)
        label = "query"

    if use_duckdb:
        # Build the Solr query text that the DuckDB path needs.
        if all_weather:
            query_text = q
        elif all_utility:
            chunks_joined = " OR ".join(f"({c})" for c in q2_chunks)
            query_text = f"({chunks_joined}) AND ({Q2_AND_BLOCK}) AND NOT ({Q2_NOT_BLOCK})"
        else:
            query_text = query

        written = _query_with_duckdb(gz_files, query_text, output_dir, label)
    else:
        written, skipped = _scan_predicate_parallel(gz_files, predicate, output_dir, n_jobs=jobs)

    click.echo(
        f"* Done. {written} document(s) written" + (f", {skipped} duplicate(s) skipped." if not use_duckdb else ".")
    )
    click.echo(f"* Output: {output_dir}")


def _lookup_ids_streaming(ids: set, gz_files: list, output_dir: Path):
    """Stream all shards and write any doc whose corpusid is in *ids*."""
    remaining = set(ids)
    written = 0

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        task = progress.add_task("[cyan]Scanning shards", total=len(gz_files))

        for gz in gz_files:
            if not remaining:
                break
            with gzip.open(gz, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = str(doc.get("corpusid", ""))
                    if cid in remaining:
                        _write_doc(doc, output_dir)
                        remaining.discard(cid)
                        written += 1
            progress.update(task, advance=1)

    click.echo(f"* Done. {written}/{len(ids)} document(s) written.")
    if remaining:
        click.echo(f"* {len(remaining)} ID(s) missing from all shards.")


def _lookup_ids_duckdb(ids: set, gz_files: list, output_dir: Path):
    """Use DuckDB to look up corpus IDs — much faster for large ID lists.

    Reads only the *exact* shard files supplied in ``gz_files`` (not the
    surrounding directory) so callers can safely pass a filtered subset.
    """
    try:
        import duckdb
    except ImportError:
        raise click.ClickException("duckdb is not installed.  Run: pixi install  or  pip install duckdb")

    click.echo(f"* Using DuckDB to query {len(gz_files)} shard(s) …")

    ids_list = [str(i) for i in ids]
    file_paths = [str(p) for p in gz_files]

    con = duckdb.connect()

    # Pass the explicit file list and ID list as bound parameters.  DuckDB's
    # read_ndjson accepts either a single path or a LIST of paths; binding the
    # list as a parameter avoids any glob-vs-explicit-files ambiguity.
    query = """
        SELECT *
        FROM read_ndjson(?, compression='gzip', ignore_errors=true)
        WHERE CAST(corpusid AS VARCHAR) IN (SELECT UNNEST(?))
    """

    written = 0
    try:
        con.execute(query, [file_paths, ids_list])
        col_names = [desc[0] for desc in con.description]
        while True:
            row = con.fetchone()
            if row is None:
                break
            doc = dict(zip(col_names, row))
            _write_doc(doc, output_dir)
            written += 1
    except Exception as exc:
        raise click.ClickException(f"DuckDB query failed: {exc}")
    finally:
        con.close()

    click.echo(f"* Done. {written}/{len(ids)} document(s) written.")
    if written < len(ids):
        click.echo(f"* {len(ids) - written} ID(s) missing from all shards.")
