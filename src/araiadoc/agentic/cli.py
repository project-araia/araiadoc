from __future__ import annotations

import json
from pathlib import Path

import click
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from araiadoc.agentic.alcf_batch import (
    collect_alcf_batch_output,
    derive_chunk_input_path,
    submit_alcf_batch,
    write_batch_manifest,
    write_batch_request_chunks,
)
from araiadoc.agentic.artifacts import summarize_results_file, write_summary
from araiadoc.agentic.constants import DEFAULT_BASE_URL, DEFAULT_MODEL, VALID_DECISIONS
from araiadoc.agentic.docs import doc_input_sha256, iter_sectionized_docs
from araiadoc.agentic.jobs import prepare_doc_jobs
from araiadoc.agentic.runners import run_requests_mode
from araiadoc.agentic.util import load_json, sha256_text


def parse_keep_decisions(value: str) -> set[str]:
    decisions = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = decisions - VALID_DECISIONS
    if invalid:
        raise click.BadParameter(f"invalid decision(s): {', '.join(sorted(invalid))}")
    if not decisions:
        raise click.BadParameter("provide at least one decision")
    return decisions


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
    batch_input_file: str | None,
    batch_output_folder: str | None,
    max_batch_bytes: int,
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

    if not batch_input_file or not batch_output_folder:
        if len(chunks) == 1:
            copy_hint = f"  1. Copy {chunks[0]['path']} to ALCF storage (e.g. /eagle/...).\n"
            input_hint = "and --batch-output-folder set to the ALCF paths.\n"
        else:
            chunk_names = ", ".join(c["path"].name for c in chunks)
            copy_hint = f"  1. Copy all chunk files ({chunk_names}) to ALCF storage.\n"
            p = Path(batch_input_file) if batch_input_file else Path("/eagle/.../input.jsonl")
            example_paths = ", ".join(derive_chunk_input_path(str(p), c["index"]) for c in chunks)
            input_hint = (
                "and --batch-output-folder set to the ALCF paths.\n"
                f"     --batch-input-file is used as a template; chunks will be "
                f"submitted as {example_paths}.\n"
            )
        click.echo(
            "\nNo --batch-input-file / --batch-output-folder provided, so the "
            "batch was NOT submitted.\n"
            "Next steps:\n"
            + copy_hint
            + "  2. Re-run with --mode alcf-batch-submit plus --batch-input-file "
            + input_hint
            + "  3. After the job(s) finish, copy the output back and run "
            "--mode alcf-batch-collect --collect-batch-output <path>."
        )
        return

    if not api_key:
        raise click.UsageError("Provide --api-key or set API_KEY/OPENAI_API_KEY.")

    endpoint = base_url.rstrip("/") + "/batches"
    if len(chunks) == 1:
        click.echo(f"Submitting ALCF batch job to {endpoint} ...")
        chunk = chunks[0]
        # Single chunk: use --batch-input-file as-is (backward compatible).
        response = submit_alcf_batch(
            base_url=base_url,
            api_key=api_key,
            model=model,
            input_file=batch_input_file,
            output_folder_path=batch_output_folder,
            timeout=timeout,
        )
        click.echo(json.dumps(response, indent=2))
    else:
        click.echo(
            f"Submitting {len(chunks)} ALCF batch jobs to {endpoint} " f"(one per chunk, shared output folder) ..."
        )
        for chunk in chunks:
            chunk_input = derive_chunk_input_path(batch_input_file, chunk["index"])
            click.echo(
                f"\n  Chunk {chunk['index']:03d}: {chunk['num_requests']} requests "
                f"({chunk['num_bytes']} bytes) -> {chunk_input}"
            )
            response = submit_alcf_batch(
                base_url=base_url,
                api_key=api_key,
                model=model,
                input_file=chunk_input,
                output_folder_path=batch_output_folder,
                timeout=timeout,
            )
            click.echo(json.dumps(response, indent=2))
        click.echo(f"\nSubmitted {len(chunks)} batch jobs.")

    click.echo(
        "\nWhen the job(s) complete, copy the output back and run:\n"
        f"  araiadoc agentic-judge-dataset <SOURCE> --mode alcf-batch-collect "
        f"-o {output_dir} --collect-batch-output <ALCF_OUTPUT_PATH>"
    )


@click.command("agentic-judge-dataset")
@click.argument("source", type=click.Path(exists=True, file_okay=False, path_type=Path))
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
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Rubric prompt file. Must emphasize a 0-3 score and corresponding relevance criteria.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    help="Directory for judgment artifacts. Defaults to SOURCE_judged.",
)
@click.option(
    "--mode",
    type=click.Choice(["requests", "alcf-batch-submit", "alcf-batch-collect"]),
    default="requests",
    show_default=True,
    help=(
        "Mode: 'requests' judges each document via chat completions (works on "
        "any OpenAI-compatible endpoint). 'alcf-batch-submit' builds the batch "
        "request JSONL + manifest and POSTs an ALCF filesystem-based batch job. "
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
    "--batch-input-file",
    type=str,
    help=(
        "[alcf-batch-submit] ALCF filesystem path the inference service will "
        "read the request JSONL from (e.g. /eagle/argonne_tpc/you/input.jsonl). "
        "The tool also writes a local copy to OUTPUT_DIR/batch_requests.jsonl."
    ),
)
@click.option(
    "--batch-output-folder",
    type=str,
    help=(
        "[alcf-batch-submit] ALCF filesystem folder the inference service will "
        "write batch output to (e.g. /eagle/argonne_tpc/you/output/)."
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
def agentic_judge_dataset(
    source: Path,
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
    batch_input_file: str | None,
    batch_output_folder: str | None,
    collect_batch_output: Path | None,
    max_batch_mb: float,
) -> None:
    """Judge relevance of a sectionized corpus with an OpenAI-compatible model."""
    output_dir = output_dir or Path(str(source) + "_judged")
    source_resolved = source.resolve()
    output_resolved = output_dir.resolve(strict=False)
    if output_resolved == source_resolved or output_resolved.is_relative_to(source_resolved):
        raise click.UsageError("--output-dir must be outside SOURCE so judging never mutates or rereads its input.")

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
            batch_input_file=batch_input_file,
            batch_output_folder=batch_output_folder,
            max_batch_bytes=int(max_batch_mb * 1_000_000),
        )
        return

    if mode == "alcf-batch-collect":
        manifest_path = output_dir / "batch_manifest.json"
        manifest = load_json(manifest_path, {})
        if not manifest:
            raise click.UsageError(
                f"No batch manifest found at {manifest_path}. Run "
                "--mode alcf-batch-submit first (with the same --output-dir)."
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
