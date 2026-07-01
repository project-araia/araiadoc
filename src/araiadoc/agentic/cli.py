from __future__ import annotations

import json
import time
from pathlib import Path

import click
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from araiadoc.agentic.alcf_batch import (
    BatchQuotaExceeded,
    collect_alcf_batch_output,
    count_active_batches,
    discover_batch_request_chunks,
    model_from_batch_request_chunks,
    poll_alcf_batch_results,
    submit_alcf_batch,
    write_batch_manifest,
    write_batch_request_chunks,
)
from araiadoc.agentic.artifacts import summarize_results_file, write_summary
from araiadoc.agentic.constants import DEFAULT_BASE_URL, DEFAULT_MODEL, VALID_DECISIONS
from araiadoc.agentic.docs import doc_input_sha256, iter_sectionized_docs
from araiadoc.agentic.jobs import prepare_doc_jobs
from araiadoc.agentic.runners import run_requests_mode
from araiadoc.agentic.util import atomic_write_json, load_json, sha256_text


def parse_keep_decisions(value: str) -> set[str]:
    decisions = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = decisions - VALID_DECISIONS
    if invalid:
        raise click.BadParameter(f"invalid decision(s): {', '.join(sorted(invalid))}")
    if not decisions:
        raise click.BadParameter("provide at least one decision")
    return decisions


def _run_alcf_batch_status(
    *,
    output_dir: Path,
    api_key: str | None,
    base_url: str,
    timeout: float,
    poll_interval: float,
    wait: bool,
) -> None:
    """Poll the ALCF gateway for the batches recorded in the submit checkpoint.

    Reads ``batch_submit_checkpoint.json`` for the batch IDs written at submit
    time, queries each ``/batches/<id>/result``, and prints a per-batch status
    table. With ``wait`` it blocks until every batch reaches a terminal state.
    """
    if not api_key:
        raise click.UsageError("Provide --api-key or set API_KEY/OPENAI_API_KEY.")

    submit_ckpt_path = output_dir / "batch_submit_checkpoint.json"
    submit_ckpt = load_json(submit_ckpt_path, {"submitted": {}})
    submitted: dict = dict(submit_ckpt.get("submitted", {}))
    if not submitted:
        raise click.UsageError(
            f"No submitted batches recorded at {submit_ckpt_path}. Run "
            "--mode alcf-batch-submit first (with the same --artifact-dir/--output-dir)."
        )

    # Map batch_id -> remote input path for readable reporting, skipping any
    # entries that never got an id (e.g. a submission that errored before record).
    id_to_input: dict[str, str] = {}
    for remote_input, meta in submitted.items():
        batch_id = meta.get("batch_id")
        if batch_id:
            id_to_input[str(batch_id)] = remote_input
    batch_ids = list(id_to_input)
    if not batch_ids:
        raise click.UsageError(
            f"{submit_ckpt_path} has submitted entries but none carry a batch_id; " "nothing to poll."
        )

    def _render(results: dict) -> None:
        counts: dict[str, int] = {}
        click.echo(f"\nBatch status ({len(results)}/{len(batch_ids)} polled):")
        for batch_id in batch_ids:
            res = results.get(batch_id)
            if res is None:
                continue
            state = res.get("state", "unknown")
            counts[state] = counts.get(state, 0) + 1
            line = f"  [{state:>9}] {batch_id}  <- {id_to_input.get(batch_id, '?')}"
            if state in ("failed", "unknown") and res.get("message"):
                line += f"\n              {res['message'].strip().splitlines()[-1][:200]}"
            click.echo(line)
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        click.echo(f"  => {summary}")

    click.echo(
        f"Polling {len(batch_ids)} batch(es) at {base_url_batches_result_hint(base_url)} "
        f"({'waiting until all terminal' if wait else 'single snapshot'}) ..."
    )
    results = poll_alcf_batch_results(
        base_url=base_url,
        api_key=api_key,
        batch_ids=batch_ids,
        timeout=timeout,
        poll_interval=poll_interval,
        wait=wait,
        on_update=_render,
    )

    failed = [bid for bid in batch_ids if results.get(bid, {}).get("state") == "failed"]
    completed = [bid for bid in batch_ids if results.get(bid, {}).get("state") == "completed"]
    if failed:
        click.echo(f"\n{len(failed)} batch(es) FAILED. Inspect their tracebacks above.")
    if completed and not failed:
        click.echo(
            "\nAll polled batches completed. Copy the output folder back and run:\n"
            f"  araiadoc agentic-judge-dataset <SOURCE> --mode alcf-batch-collect "
            f"-o {output_dir} --collect-batch-output <ALCF_OUTPUT_PATH>"
        )


def base_url_batches_result_hint(base_url: str) -> str:
    """Return the list/result base URL for display (mirrors alcf_batch derivation)."""
    from araiadoc.agentic.alcf_batch import _batches_list_base

    return _batches_list_base(base_url) + "/batches/<id>/result"


def _run_alcf_batch_submit(
    *,
    jobs: list,
    output_dir: Path,
    api_key: str | None,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    batch_input_dir: str | None,
    batch_input_file: str | None,
    batch_output_folder: str | None,
    max_batch_bytes: int,
    max_active_batches: int,
    poll_interval: float,
) -> None:
    """Build the request JSONL chunk(s) + manifest, then submit ALCF batch job(s).

    The ALCF inference gateway reads the input JSONL and writes output from/to
    ALCF shared storage paths (e.g. /eagle/...). This step writes a local copy
    of the request file(s) and a custom_id->doc manifest, then POSTs one batch
    per chunk referencing the ALCF paths so that --mode alcf-batch-collect can
    later fold results back into judge artifacts.

    When all requests fit within *max_batch_bytes* bytes a single
    ``batch_requests.jsonl`` is written (backward-compatible). Otherwise
    numbered chunk files (``batch_requests_000.jsonl``, …) are written and one
    batch is submitted per chunk, all sharing the same output folder.

    ALCF caps each user to a small number of *active* (pending/running) batches.
    Submissions are therefore throttled to *max_active_batches*: before each
    POST the gateway is polled (every *poll_interval* seconds) until a slot is
    free. Submitted chunks are recorded in ``batch_submit_checkpoint.json`` so a
    re-run resumes where it left off instead of double-submitting.

    Remote input paths are resolved by joining *batch_input_dir* with each
    chunk's LOCAL filename, so the files you copy to ALCF keep their names. The
    legacy single-path *batch_input_file* is still accepted for one-chunk runs.
    """
    if not jobs:
        click.echo("No documents to submit (all completed or none discovered).")
        return

    manifest_path = output_dir / "batch_manifest.json"
    chunks = write_batch_request_chunks(
        jobs,
        output_dir,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_bytes=max_batch_bytes,
    )
    write_batch_manifest(jobs, manifest_path)

    total_bytes = sum(c["num_bytes"] for c in chunks)
    if len(chunks) == 1:
        click.echo(f"Wrote {len(jobs)} requests ({total_bytes} bytes) to {chunks[0]['path']}")
    else:
        click.echo(
            f"Split {len(jobs)} requests ({total_bytes} bytes) across {len(chunks)} chunks "
            f"(--max-batch-mb={max_batch_bytes / 1_000_000:.3g}):"
        )
        for chunk in chunks:
            click.echo(f"  {chunk['path'].name}: {chunk['num_requests']} requests, " f"{chunk['num_bytes']} bytes")
    click.echo(f"Wrote manifest to {manifest_path}")

    _submit_chunks(
        chunks=chunks,
        output_dir=output_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        batch_input_dir=batch_input_dir,
        batch_input_file=batch_input_file,
        batch_output_folder=batch_output_folder,
        max_active_batches=max_active_batches,
        poll_interval=poll_interval,
    )


def _run_alcf_batch_resubmit(
    *,
    output_dir: Path,
    api_key: str | None,
    base_url: str,
    timeout: float,
    batch_input_dir: str | None,
    batch_input_file: str | None,
    batch_output_folder: str | None,
    max_active_batches: int,
    poll_interval: float,
) -> None:
    """Submit batch request chunks ALREADY written to *output_dir*, no regeneration.

    This is the resume-friendly path: it reads ``batch_requests*.jsonl`` (and the
    existing ``batch_manifest.json``) straight from *output_dir*, so SOURCE, the
    prompt, the model's chunking, and ``--max-batch-mb`` are irrelevant — the
    requests are already baked into the files. Combined with
    ``batch_submit_checkpoint.json`` and gateway reconciliation, only the
    not-yet-submitted chunks are POSTed.
    """
    chunks = discover_batch_request_chunks(output_dir)
    if not chunks:
        raise click.UsageError(
            f"--resubmit-existing found no batch_requests*.jsonl in {output_dir}. "
            "Run --mode alcf-batch-submit first (without --resubmit-existing) to build them."
        )
    if not (output_dir / "batch_manifest.json").exists():
        raise click.UsageError(
            f"No batch_manifest.json in {output_dir}; cannot collect later. "
            "Rebuild with --mode alcf-batch-submit (without --resubmit-existing)."
        )

    submit_model = model_from_batch_request_chunks(chunks)
    total_bytes = sum(c["num_bytes"] for c in chunks)
    total_requests = sum(c["num_requests"] for c in chunks)
    click.echo(
        f"Resubmitting {len(chunks)} existing chunk(s) from {output_dir} "
        f"({total_requests} requests, {total_bytes} bytes); no regeneration."
    )
    click.echo(f"Using model from existing request JSONL: {submit_model}")

    _submit_chunks(
        chunks=chunks,
        output_dir=output_dir,
        api_key=api_key,
        base_url=base_url,
        model=submit_model,
        timeout=timeout,
        batch_input_dir=batch_input_dir,
        batch_input_file=batch_input_file,
        batch_output_folder=batch_output_folder,
        max_active_batches=max_active_batches,
        poll_interval=poll_interval,
    )


def _submit_chunks(
    *,
    chunks: list,
    output_dir: Path,
    api_key: str | None,
    base_url: str,
    model: str,
    timeout: float,
    batch_input_dir: str | None,
    batch_input_file: str | None,
    batch_output_folder: str | None,
    max_active_batches: int,
    poll_interval: float,
) -> None:
    """Submit pre-built chunk descriptors to ALCF, throttled and resumable."""
    multi_chunk = len(chunks) > 1
    have_remote = (batch_input_dir or batch_input_file) and batch_output_folder

    if not have_remote:
        chunk_names = ", ".join(c["path"].name for c in chunks)
        if multi_chunk:
            copy_hint = (
                f"  1. Copy all {len(chunks)} chunk files ({chunk_names}) into one "
                "ALCF storage folder (no renaming).\n"
            )
            rerun_hint = (
                "  2. Re-run with --mode alcf-batch-submit plus --batch-request-dir "
                "<that ALCF folder> and --batch-result-dir <ALCF result folder>.\n"
                "     One batch is submitted per chunk, reusing each chunk's filename.\n"
            )
        else:
            copy_hint = f"  1. Copy {chunks[0]['path']} to ALCF storage (e.g. /eagle/...).\n"
            rerun_hint = (
                "  2. Re-run with --mode alcf-batch-submit plus --batch-request-dir "
                "<ALCF folder> (or legacy --batch-input-file <ALCF path>) and "
                "--batch-result-dir <ALCF result folder>.\n"
            )
        click.echo(
            "\nNo ALCF input/output paths provided, so the batch was NOT submitted.\n"
            "Next steps:\n" + copy_hint + rerun_hint + "  3. After the job(s) finish, copy the output back and run "
            "--mode alcf-batch-collect --collect-batch-output <path>."
        )
        return

    if not api_key:
        raise click.UsageError("Provide --api-key or set API_KEY/OPENAI_API_KEY.")

    # The ALCF inference service reads input_file / writes output on Sophia's
    # filesystem, NOT the machine running this command. Relative paths resolve to
    # nothing there and the batch fails almost immediately. Require absolute paths
    # (ALCF further requires them to live under /eagle/argonne_tpc or another
    # world-readable location).
    _require_absolute_alcf_path("--batch-request-dir", batch_input_dir)
    _require_absolute_alcf_path("--batch-input-file", batch_input_file)
    _require_absolute_alcf_path("--batch-result-dir", batch_output_folder)

    # Resolve each chunk's remote input path.
    if batch_input_dir:
        remote_dir = batch_input_dir.rstrip("/")
        remote_inputs = [f"{remote_dir}/{c['path'].name}" for c in chunks]
    else:
        # Legacy single --batch-input-file path. Only valid for a single chunk:
        # there is no unambiguous way to map one path onto many chunks.
        if multi_chunk:
            raise click.UsageError(
                f"This run split into {len(chunks)} chunks, but --batch-input-file "
                "is a single path. Use --batch-request-dir <ALCF folder> instead so "
                "each chunk is submitted under its own filename "
                f"({', '.join(c['path'].name for c in chunks)})."
            )
        remote_inputs = [batch_input_file]

    endpoint = base_url.rstrip("/") + "/batches"

    # Resume: skip chunks already submitted in a prior run.
    submit_ckpt_path = output_dir / "batch_submit_checkpoint.json"
    submit_ckpt = load_json(submit_ckpt_path, {"submitted": {}})
    submitted: dict = dict(submit_ckpt.get("submitted", {}))

    def _record(remote_input: str, response: dict) -> None:
        submitted[remote_input] = {
            "batch_id": response.get("batch_id") or response.get("id"),
            "status": response.get("status"),
            "submitted_at": time_now(),
        }
        atomic_write_json(submit_ckpt_path, {"submitted": submitted})

    # Also reconcile against the gateway: any chunk whose remote input_file
    # already appears in the user's batch list was submitted by an earlier run
    # (possibly before checkpointing existed) — adopt it so we don't double-submit.
    try:
        from araiadoc.agentic.alcf_batch import list_alcf_batches

        existing = list_alcf_batches(base_url=base_url, api_key=api_key, timeout=timeout)
        by_input = {str(b.get("input_file")): b for b in existing if b.get("input_file")}
        for ri in remote_inputs:
            if ri not in submitted and ri in by_input:
                b = by_input[ri]
                submitted[ri] = {
                    "batch_id": b.get("batch_id") or b.get("id"),
                    "status": b.get("status"),
                    "submitted_at": b.get("created_at"),
                    "adopted_from_gateway": True,
                }
        if submitted:
            atomic_write_json(submit_ckpt_path, {"submitted": submitted})
    except click.UsageError as e:
        click.echo(f"(warning: could not reconcile with gateway batch list: {e})")

    pending = [(c, ri) for c, ri in zip(chunks, remote_inputs) if ri not in submitted]
    already = len(remote_inputs) - len(pending)
    if already:
        click.echo(
            f"Resuming: {already}/{len(remote_inputs)} chunk(s) already submitted (per {submit_ckpt_path.name})."
        )
    if not pending:
        click.echo("All chunks already submitted. Nothing to do.")
    else:
        click.echo(
            f"Submitting {len(pending)} ALCF batch job(s) to {endpoint} "
            f"(max {max_active_batches} active at a time, shared output folder) ..."
        )

    for chunk, remote_input in pending:
        _wait_for_active_slot(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_active_batches=max_active_batches,
            poll_interval=poll_interval,
        )
        label = f"Chunk {chunk['index']:03d}" if chunk["index"] is not None else "Batch"
        click.echo(f"\n  {label}: {chunk['num_requests']} requests ({chunk['num_bytes']} bytes) -> {remote_input}")
        response = _submit_with_quota_backoff(
            base_url=base_url,
            api_key=api_key,
            model=model,
            input_file=remote_input,
            output_folder_path=batch_output_folder,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        click.echo(json.dumps(response, indent=2))
        _record(remote_input, response)

    submitted_count = len([1 for ri in remote_inputs if ri in submitted])
    click.echo(f"\nSubmitted {submitted_count}/{len(remote_inputs)} batch job(s) total.")
    click.echo(
        "\nWhen the job(s) complete, copy the output back and run:\n"
        f"  araiadoc agentic-judge-dataset <SOURCE> --mode alcf-batch-collect "
        f"-o {output_dir} --collect-batch-output <ALCF_OUTPUT_PATH>"
    )


def _require_absolute_alcf_path(flag: str, value: str | None) -> None:
    """Reject relative ALCF paths, which the inference service can't resolve.

    The batch service reads/writes these paths on Sophia's filesystem, so a
    relative path (e.g. ``63_judged_input/``) silently produces batches that
    fail almost immediately. ALCF additionally requires the location to be
    world-readable, typically under ``/eagle/argonne_tpc``.
    """
    if value is None:
        return
    if not value.startswith("/"):
        raise click.UsageError(
            f"{flag} must be an ABSOLUTE path on ALCF storage (got {value!r}). "
            "The inference service reads/writes this path on Sophia, not your "
            "local machine, so relative paths fail. Use something under "
            "/eagle/argonne_tpc/<you>/ (or another world-readable absolute path)."
        )
    if not value.startswith("/eagle/") and not value.startswith("/lus/"):
        click.echo(
            f"  (warning: {flag}={value} is absolute but not under /eagle or /lus; "
            "ALCF batches usually require /eagle/argonne_tpc or a world-readable location.)"
        )


def time_now() -> str:
    """Wrapper so tests can monkeypatch the timestamp without importing util."""
    from araiadoc.agentic.util import now_iso

    return now_iso()


def _wait_for_active_slot(
    *,
    base_url: str,
    api_key: str,
    timeout: float,
    max_active_batches: int,
    poll_interval: float,
) -> None:
    """Block until the user's active-batch count is below *max_active_batches*."""
    while True:
        try:
            active = count_active_batches(base_url=base_url, api_key=api_key, timeout=timeout)
        except click.UsageError as e:
            # Listing failed; warn and proceed (the submit itself still guards via quota backoff).
            click.echo(f"  (warning: could not query active batches: {e}); proceeding.")
            return
        if active < max_active_batches:
            return
        click.echo(
            f"  {active} active batch(es) >= limit {max_active_batches}; "
            f"waiting {poll_interval:.0f}s for a slot to free ..."
        )
        time.sleep(poll_interval)


def _submit_with_quota_backoff(
    *,
    base_url: str,
    api_key: str,
    model: str,
    input_file: str,
    output_folder_path: str,
    timeout: float,
    poll_interval: float,
) -> dict:
    """Submit one batch, retrying on quota_exceeded after waiting for a slot."""
    while True:
        try:
            return submit_alcf_batch(
                base_url=base_url,
                api_key=api_key,
                model=model,
                input_file=input_file,
                output_folder_path=output_folder_path,
                timeout=timeout,
            )
        except BatchQuotaExceeded:
            click.echo(f"  quota full on submit; waiting {poll_interval:.0f}s and retrying ...")
            time.sleep(poll_interval)


@click.command("agentic-judge-dataset")
@click.argument(
    "source",
    required=False,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--model",
    default=DEFAULT_MODEL,
    show_default=True,
    help="OpenAI-compatible chat model name.",
)
@click.option(
    "--base-url",
    default=DEFAULT_BASE_URL,
    show_default=True,
    help="OpenAI-compatible API base URL.",
)
@click.option(
    "--api-key",
    envvar=["API_KEY", "OPENAI_API_KEY"],
    help="API key/token. Also read from API_KEY or OPENAI_API_KEY.",
)
@click.option(
    "--prompt",
    "prompt_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Rubric prompt file. Must emphasize a 0-3 score and corresponding relevance "
        "criteria. Required except with --resubmit-existing."
    ),
)
@click.option(
    "--artifact-dir",
    "--output-dir",
    "-o",
    "output_dir",
    type=click.Path(path_type=Path),
    help=(
        "Directory for araiadoc artifacts/work files (request chunks, manifest, "
        "checkpoints, results, summary). Defaults to SOURCE_judged. "
        "--output-dir is a legacy alias."
    ),
)
@click.option(
    "--mode",
    type=click.Choice(["requests", "alcf-batch-submit", "alcf-batch-status", "alcf-batch-collect"]),
    default="requests",
    show_default=True,
    help=(
        "Mode: 'requests' judges each document via chat completions (works on "
        "any OpenAI-compatible endpoint). 'alcf-batch-submit' builds the batch "
        "request JSONL + manifest and POSTs an ALCF filesystem-based batch job. "
        "'alcf-batch-status' polls the ALCF gateway for the batches recorded in "
        "batch_submit_checkpoint.json (add --wait to block until all finish). "
        "'alcf-batch-collect' folds an ALCF batch output file/folder back into "
        "judge artifacts."
    ),
)
@click.option(
    "--concurrency",
    default=4,
    show_default=True,
    type=click.IntRange(1),
    help="Concurrent requests for --mode requests.",
)
@click.option("--max-tokens", default=512, show_default=True, type=click.IntRange(1))
@click.option("--temperature", default=0.0, show_default=True, type=float)
@click.option(
    "--timeout",
    default=120.0,
    show_default=True,
    type=click.FloatRange(1.0),
    help="Per-request timeout in seconds.",
)
@click.option(
    "--limit",
    type=click.IntRange(1),
    help="Judge at most N documents. No limit by default.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Build and print prompt samples without calling the model.",
)
@click.option(
    "--max-input-chars",
    default=20000,
    show_default=True,
    type=click.IntRange(100),
    help="Maximum document payload characters included in each prompt.",
)
@click.option(
    "--copy-kept",
    is_flag=True,
    help="Copy documents with kept decisions into OUTPUT_DIR/kept.",
)
@click.option(
    "--keep-decisions",
    default="relevant",
    show_default=True,
    help="Comma-separated decisions copied by --copy-kept.",
)
@click.option(
    "--resume/--no-resume",
    default=True,
    show_default=True,
    help="Skip completed stable job keys from judge_checkpoint.json.",
)
@click.option(
    "--batch-request-dir",
    "--batch-input-dir",
    "batch_input_dir",
    type=str,
    help=(
        "[alcf-batch-submit] ALCF filesystem folder containing request JSONL "
        "chunk file(s) for the endpoint to read (e.g. /eagle/.../requests/). "
        "The tool submits one batch per chunk using the SAME filenames it wrote "
        "locally (batch_requests.jsonl, or batch_requests_000.jsonl, …). "
        "--batch-input-dir is a legacy alias."
    ),
)
@click.option(
    "--batch-input-file",
    type=str,
    help=(
        "[alcf-batch-submit] DEPRECATED for multi-chunk runs; use --batch-request-dir. "
        "ALCF filesystem path the inference service reads a SINGLE-chunk request "
        "JSONL from (e.g. /eagle/argonne_tpc/you/input.jsonl). Errors if the run "
        "produced more than one chunk."
    ),
)
@click.option(
    "--batch-result-dir",
    "--batch-output-folder",
    "batch_output_folder",
    type=str,
    help=(
        "[alcf-batch-submit] ALCF filesystem folder where the inference service "
        "writes batch result/progress files (e.g. /eagle/.../batch_results/). "
        "--batch-output-folder is a legacy alias."
    ),
)
@click.option(
    "--collect-batch-output",
    type=click.Path(exists=True, path_type=Path),
    help=(
        "[alcf-batch-collect] Path to the ALCF batch output .jsonl file, or a "
        "folder containing output .jsonl files, to fold into judge artifacts."
    ),
)
@click.option(
    "--max-batch-mb",
    default=9,
    show_default=True,
    type=click.FloatRange(min=0.001),
    help=(
        "[alcf-batch-submit] Maximum size in MB per request JSONL chunk. "
        "When all requests fit within this limit a single batch_requests.jsonl "
        "is written; otherwise numbered chunk files are written and one batch "
        "job is submitted per chunk. Default (9 MB) stays comfortably "
        "under the ALCF 10 MB payload limit."
    ),
)
@click.option(
    "--max-active-batches",
    default=2,
    show_default=True,
    type=click.IntRange(1),
    help=(
        "[alcf-batch-submit] Maximum number of active (pending/running) ALCF "
        "batches at once. Submission is throttled to stay within this; ALCF "
        "currently caps users at 2 active batches."
    ),
)
@click.option(
    "--poll-interval",
    default=30.0,
    show_default=True,
    type=click.FloatRange(1.0),
    help=(
        "[alcf-batch-submit] Seconds to wait between polling the ALCF gateway "
        "for a free active-batch slot when throttling submissions."
    ),
)
@click.option(
    "--resubmit-existing",
    is_flag=True,
    help=(
        "[alcf-batch-submit] Submit the batch_requests*.jsonl already written to "
        "--artifact-dir/--output-dir instead of regenerating them. Skips reading SOURCE / the "
        "prompt / re-chunking; the submit model is derived from body.model inside "
        "the existing JSONL, and --max-batch-mb is ignored. Use to resume after a "
        "partial or failed submission without rebuilding."
    ),
)
@click.option(
    "--wait",
    is_flag=True,
    help=(
        "[alcf-batch-status] Block and keep polling every --poll-interval seconds "
        "until all recorded batches reach a terminal state (completed/failed) "
        "instead of printing a single status snapshot and exiting."
    ),
)
def agentic_judge_dataset(
    source: Path | None,
    model: str,
    base_url: str,
    api_key: str | None,
    prompt_path: Path,
    output_dir: Path | None,
    mode: str,
    concurrency: int,
    max_tokens: int,
    temperature: float,
    timeout: float,
    limit: int | None,
    dry_run: bool,
    max_input_chars: int,
    copy_kept: bool,
    keep_decisions: str,
    resume: bool,
    batch_input_dir: str | None,
    batch_input_file: str | None,
    batch_output_folder: str | None,
    collect_batch_output: Path | None,
    max_batch_mb: float,
    max_active_batches: int,
    poll_interval: float,
    resubmit_existing: bool,
    wait: bool,
) -> None:
    """Judge relevance of a sectionized corpus with an OpenAI-compatible model."""
    if mode == "alcf-batch-status":
        if output_dir is None:
            raise click.UsageError(
                "--mode alcf-batch-status requires --artifact-dir pointing at the dir "
                "with batch_submit_checkpoint.json."
            )
        _run_alcf_batch_status(
            output_dir=output_dir,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            poll_interval=poll_interval,
            wait=wait,
        )
        return

    # Resubmit-existing short-circuit: the requests are already baked into
    # batch_requests*.jsonl in --artifact-dir/--output-dir, so we don't read SOURCE / the prompt
    # / re-chunk. This must run before any prompt/source-dependent work below.
    if resubmit_existing:
        if mode != "alcf-batch-submit":
            raise click.UsageError("--resubmit-existing is only valid with --mode alcf-batch-submit.")
        if output_dir is None:
            raise click.UsageError(
                "--resubmit-existing requires --artifact-dir/--output-dir pointing at the dir "
                "with batch_requests*.jsonl."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        _run_alcf_batch_resubmit(
            output_dir=output_dir,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            batch_input_dir=batch_input_dir,
            batch_input_file=batch_input_file,
            batch_output_folder=batch_output_folder,
            max_active_batches=max_active_batches,
            poll_interval=poll_interval,
        )
        return

    if source is None:
        raise click.UsageError("SOURCE is required (except with --resubmit-existing).")
    output_dir = output_dir or Path(str(source) + "_judged")

    source_resolved = source.resolve()
    output_resolved = output_dir.resolve(strict=False)
    if output_resolved == source_resolved or output_resolved.is_relative_to(source_resolved):
        raise click.UsageError(
            "--artifact-dir/--output-dir must be outside SOURCE so judging never mutates or rereads its input."
        )

    if prompt_path is None:
        raise click.UsageError("--prompt is required (except with --resubmit-existing).")

    parsed_keep_decisions = parse_keep_decisions(keep_decisions)
    rubric = prompt_path.read_text(encoding="utf-8")
    prompt_sha256 = sha256_text(rubric)
    docs = iter_sectionized_docs(source)
    if limit is not None:
        docs = docs[:limit]

    checkpoint_path = output_dir / "judge_checkpoint.json"
    result_path = output_dir / "judge_results.jsonl.gz"
    summary_path = output_dir / "judge_summary.json"
    failures_path = output_dir / "failures.json"
    checkpoint = load_json(checkpoint_path, {"completed_keys": []}) if resume else {"completed_keys": []}
    completed_keys = set(checkpoint.get("completed_keys", []))
    jobs = prepare_doc_jobs(
        docs=docs,
        rubric=rubric,
        prompt_sha256=prompt_sha256,
        model=model,
        base_url=base_url,
        max_input_chars=max_input_chars,
        completed_keys=completed_keys,
        resume=resume,
    )

    if dry_run:
        click.echo(f"Discovered documents: {len(docs)}")
        click.echo(f"Would judge documents: {len(jobs)}")
        for idx, job in enumerate(jobs, start=1):
            click.echo(f"\n--- Prompt sample {idx}: {job['doc']['source_path']} ---")
            click.echo(job["prompt"])
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    if mode == "alcf-batch-submit":
        _run_alcf_batch_submit(
            jobs=jobs,
            output_dir=output_dir,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            batch_input_dir=batch_input_dir,
            batch_input_file=batch_input_file,
            batch_output_folder=batch_output_folder,
            max_batch_bytes=int(max_batch_mb * 1_000_000),
            max_active_batches=max_active_batches,
            poll_interval=poll_interval,
        )
        return

    if mode == "alcf-batch-collect":
        manifest_path = output_dir / "batch_manifest.json"
        manifest = load_json(manifest_path, {})
        if not manifest:
            raise click.UsageError(
                f"No batch manifest found at {manifest_path}. Run "
                "--mode alcf-batch-submit first (with the same --artifact-dir/--output-dir)."
            )
        if collect_batch_output is None:
            raise click.UsageError(
                "alcf-batch-collect requires --collect-batch-output pointing to "
                "the ALCF batch output .jsonl file or folder."
            )

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        if mode == "requests":
            if not api_key:
                raise click.UsageError("Provide --api-key or set API_KEY/OPENAI_API_KEY.")
            stats = run_requests_mode(
                jobs=jobs,
                source=source,
                output_dir=output_dir,
                api_key=api_key,
                base_url=base_url,
                model=model,
                prompt_sha256=prompt_sha256,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                concurrency=concurrency,
                copy_kept=copy_kept,
                keep_decisions=parsed_keep_decisions,
                completed_keys=completed_keys,
                checkpoint_path=checkpoint_path,
                result_path=result_path,
                progress=progress,
            )
        else:  # alcf-batch-collect
            progress.log(f"Collecting ALCF batch output from {collect_batch_output}")
            stats = collect_alcf_batch_output(
                output_path=collect_batch_output,
                manifest=manifest,
                source=source,
                output_dir=output_dir,
                model=model,
                base_url=base_url,
                prompt_sha256=prompt_sha256,
                copy_kept=copy_kept,
                keep_decisions=parsed_keep_decisions,
                completed_keys=completed_keys,
                checkpoint_path=checkpoint_path,
                result_path=result_path,
            )

        if stats["failures"]:
            failures_path.write_text(json.dumps(stats["failures"], indent=2), encoding="utf-8")
        expected_input_hashes = {doc["source_path"]: doc_input_sha256(doc) for doc in docs}
        cumulative = summarize_results_file(
            result_path,
            model=model,
            base_url=base_url,
            prompt_sha256=prompt_sha256,
            expected_input_hashes=expected_input_hashes,
        )
        write_summary(
            summary_path,
            source=source,
            output_dir=output_dir,
            model=model,
            base_url=base_url,
            prompt_path=prompt_path,
            prompt_sha256=prompt_sha256,
            mode=mode,
            keep_decisions=parsed_keep_decisions,
            copy_kept=copy_kept,
            total_discovered=len(docs),
            total_attempted=cumulative["succeeded"] + stats["failed"],
            total_succeeded=cumulative["succeeded"],
            total_failed=stats["failed"],
            decision_counts=cumulative["decision_counts"],
            parse_failures=cumulative["parse_failures"],
            current_run_attempted=len(jobs),
            current_run_succeeded=stats["succeeded"],
            current_run_failed=stats["failed"],
            current_run_decision_counts=stats["decision_counts"],
            current_run_parse_failures=stats["parse_failures"],
            retries=4,
            api_key_provided=bool(api_key),
        )
        progress.log("\n* Agentic judging complete.")
        progress.log(f"* Output directory: {output_dir}")
        progress.log(f"* Documents attempted: {len(jobs)}")
        progress.log(f"* Documents succeeded: {stats['succeeded']}")
        progress.log(f"* Documents failed: {stats['failed']}")
        progress.log(f"* Parse failures: {stats['parse_failures']}")
