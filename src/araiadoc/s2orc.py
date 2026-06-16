"""Commands for downloading and querying the Semantic Scholar s2orc_v2 bulk dataset.

Two top-level commands are provided:

  download-s2orc   -- Download all shards of s2orc_v2 from the S2 Datasets API
                      with resume support (already-present shards are skipped).

  get-from-local-s2orc -- Query a local s2orc_v2 download using DuckDB,
                           producing per-document JSON files in the same layout
                           that section-dataset-s2orc expects as input.
                           Shards are processed one at a time so progress is
                           checkpointed (``duckdb_checkpoint.json``); re-running
                           with the same --output-dir resumes from the next
                           unscanned shard.  Supports:
                             * lookup by corpus ID (--source JSON/TXT of IDs)
                             * ad-hoc Solr-style query (--query)
                             * pre-defined weather/utility searches
                               (--all-weather / --all-utility) whose terms
                               mirror the Solr queries used by the old
                               get-from-titanv command.
"""

import json
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
        return f"regexp_matches(lower(COALESCE(body.text, '')), '\\b{safe}\\b')"
    if op == "and":
        return f"({_solr_ast_to_sql(node[1])}) AND ({_solr_ast_to_sql(node[2])})"
    if op == "or":
        return f"({_solr_ast_to_sql(node[1])}) OR ({_solr_ast_to_sql(node[2])})"
    if op == "not":
        return f"NOT ({_solr_ast_to_sql(node[1])})"
    return "FALSE"


# ---------------------------------------------------------------------------
# DuckDB query helpers (per-shard loop with checkpointing)
# ---------------------------------------------------------------------------


def _load_checkpoint(output_dir: Path) -> dict:
    """Load (or initialize) the per-shard DuckDB checkpoint for *output_dir*.

    The checkpoint records which shard filenames have been fully scanned, so a
    re-run with the same --output-dir resumes where the previous run left off.
    """
    cp_path = output_dir / "duckdb_checkpoint.json"
    if cp_path.exists():
        try:
            data = json.loads(cp_path.read_text())
            if isinstance(data, dict) and "completed_shards" in data:
                data["completed_shards"] = set(data["completed_shards"])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"completed_shards": set(), "written": 0}


def _save_checkpoint(output_dir: Path, data: dict) -> None:
    """Atomically write the DuckDB checkpoint to *output_dir*."""
    cp_path = output_dir / "duckdb_checkpoint.json"
    tmp = cp_path.with_suffix(".json.tmp")
    serialisable = {
        "completed_shards": sorted(data["completed_shards"]),
        "written": data.get("written", 0),
    }
    tmp.write_text(json.dumps(serialisable, indent=2))
    tmp.replace(cp_path)


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

    Processes one shard per query so a `rich` progress bar can advance and so
    that progress is checkpointed (``duckdb_checkpoint.json``) — re-running
    against the same *output_dir* resumes from the next unscanned shard.
    """
    import duckdb

    # Parse the Solr query and translate to a SQL WHERE clause
    ast = _SolrParser(_tokenize_solr(query_text)).parse()
    where_clause = _solr_ast_to_sql(ast)

    checkpoint = _load_checkpoint(output_dir)
    completed: set[str] = checkpoint["completed_shards"]
    written: int = checkpoint.get("written", 0)

    pending = [gz for gz in gz_files if gz.name not in completed]
    if completed:
        click.echo(
            f"* Resuming DuckDB query ({label}): {len(completed)}/{len(gz_files)} shard(s) "
            f"already complete, {written} doc(s) previously written."
        )
    click.echo(f"* DuckDB query ({label}) across {len(pending)} remaining shard(s) \u2026")

    if not pending:
        click.echo("* Nothing to do — all shards already scanned.")
        return written

    con = duckdb.connect()
    sql = f"""
        SELECT *
        FROM read_ndjson(?, compression='gzip', ignore_errors=true)
        WHERE {where_clause}
    """

    # Dedup within this run only; cross-run dedup is implicit because
    # _write_doc overwrites by corpusid.json filename.
    seen: set[str] = set()

    try:
        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            task = progress.add_task(f"[cyan]DuckDB scan ({label})", total=len(gz_files))
            progress.update(task, advance=len(completed))

            for gz in pending:
                try:
                    con.execute(sql, [[str(gz)]])
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
                    progress.log(f"* WARNING: shard {gz.name} failed ({type(exc).__name__}: {exc}); skipping.")
                    progress.update(task, advance=1)
                    continue

                completed.add(gz.name)
                checkpoint["completed_shards"] = completed
                checkpoint["written"] = written
                _save_checkpoint(output_dir, checkpoint)
                progress.update(task, advance=1)
    finally:
        con.close()

    click.echo(f"* DuckDB returned {written} unique document(s).")
    return written


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
    help=("Ad-hoc Solr-style query string.  Supports AND, OR, NOT, parens, " "and quoted phrases."),
)
def get_from_local_s2orc(
    data_dir: Path,
    output_dir: Path | None,
    source: str | None,
    all_weather: bool,
    all_utility: bool,
    query: str | None,
):
    """Extract documents from a local s2orc_v2 download using DuckDB.

    Use one of --source, --all-weather, --all-utility, or --query.

    Produces one JSON file per matching document, sharded by the last two
    digits of the corpus ID — the same layout consumed by section-dataset-s2orc.

    Shards are scanned one at a time so a progress bar can advance and so
    progress is checkpointed (``duckdb_checkpoint.json``) — re-running with
    the same --output-dir resumes from the next unscanned shard.

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
    # Corpus-ID lookup                                                   #
    # ------------------------------------------------------------------ #
    if source:
        source_path = Path(source)
        if source_path.suffix == ".json":
            ids = {str(i) for i in json.loads(source_path.read_text())}
        else:
            ids = {line.strip() for line in source_path.read_text().splitlines() if line.strip()}

        click.echo(f"* Looking up {len(ids)} corpus ID(s).")
        _lookup_ids_duckdb(ids, gz_files, output_dir)
        return

    # ------------------------------------------------------------------ #
    # Keyword search                                                     #
    # ------------------------------------------------------------------ #
    if all_weather:
        query_text = q
        label = "weather"
    elif all_utility:
        chunks_joined = " OR ".join(f"({c})" for c in q2_chunks)
        query_text = f"({chunks_joined}) AND ({Q2_AND_BLOCK}) AND NOT ({Q2_NOT_BLOCK})"
        label = "utility"
    else:
        query_text = query
        label = "query"

    written = _query_with_duckdb(gz_files, query_text, output_dir, label)

    click.echo(f"* Done. {written} document(s) written.")
    click.echo(f"* Output: {output_dir}")


def _lookup_ids_duckdb(ids: set, gz_files: list, output_dir: Path):
    """Use DuckDB to look up corpus IDs — much faster for large ID lists.

    Reads only the *exact* shard files supplied in ``gz_files`` (not the
    surrounding directory) so callers can safely pass a filtered subset.

    Processes one shard per query so a `rich` progress bar can advance and so
    that progress is checkpointed (``duckdb_checkpoint.json``) — re-running
    against the same *output_dir* resumes from the next unscanned shard.
    """
    try:
        import duckdb
    except ImportError:
        raise click.ClickException("duckdb is not installed.  Run: pixi install  or  pip install duckdb")

    checkpoint = _load_checkpoint(output_dir)
    completed: set[str] = checkpoint["completed_shards"]
    written: int = checkpoint.get("written", 0)

    pending = [gz for gz in gz_files if gz.name not in completed]
    if completed:
        click.echo(
            f"* Resuming DuckDB ID lookup: {len(completed)}/{len(gz_files)} shard(s) "
            f"already complete, {written} doc(s) previously written."
        )
    click.echo(f"* Using DuckDB to query {len(pending)} remaining shard(s) …")

    if not pending:
        click.echo("* Nothing to do — all shards already scanned.")
        click.echo(f"* Done. {written}/{len(ids)} document(s) written.")
        return

    ids_list = [str(i) for i in ids]
    con = duckdb.connect()

    query = """
        SELECT *
        FROM read_ndjson(?, compression='gzip', ignore_errors=true)
        WHERE CAST(corpusid AS VARCHAR) IN (SELECT UNNEST(?))
    """

    try:
        with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
            task = progress.add_task("[cyan]DuckDB ID lookup", total=len(gz_files))
            progress.update(task, advance=len(completed))

            for gz in pending:
                try:
                    con.execute(query, [[str(gz)], ids_list])
                    col_names = [desc[0] for desc in con.description]
                    while True:
                        row = con.fetchone()
                        if row is None:
                            break
                        doc = dict(zip(col_names, row))
                        _write_doc(doc, output_dir)
                        written += 1
                except Exception as exc:
                    progress.log(f"* WARNING: shard {gz.name} failed ({type(exc).__name__}: {exc}); skipping.")
                    progress.update(task, advance=1)
                    continue

                completed.add(gz.name)
                checkpoint["completed_shards"] = completed
                checkpoint["written"] = written
                _save_checkpoint(output_dir, checkpoint)
                progress.update(task, advance=1)
    finally:
        con.close()

    click.echo(f"* Done. {written}/{len(ids)} document(s) written.")
    if written < len(ids):
        click.echo(f"* {len(ids) - written} ID(s) missing from all shards.")
