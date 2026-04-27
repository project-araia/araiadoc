import json
from pathlib import Path

import click
from joblib import Parallel, delayed
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

try:
    from .ref_extraction_utils import split_references
except ImportError:
    from ref_extraction_utils import split_references


def process_file(file_path):
    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        if not data:
            return False, file_path.name, "Empty file"

        # Get the last key
        keys = list(data.keys())
        if not keys:
            return False, file_path.name, "No keys"

        last_key = keys[-1]

        # If "References" key exists, we want to re-process (merge and re-split)
        # to take advantage of the improved heuristic.
        # But we must be careful: if "References" IS the last key, we need to handle that.
        # Usually checking "References" in data is enough.

        full_text = data[last_key]

        if "References" in data:
            # Reconstruct original text
            # Assuming References was stripped from the end of the last key.
            # However, if 'References' IS the last key (alphabetically or insertion order), we need to be careful.
            # But keys[-1] from data.keys() depends on insertion order in Python 3.7+
            # If References was added last, it is the last key.

            # Let's verify if References is indeed separate from last content key.
            if last_key == "References":
                # This could happen if References is the very last thing added.
                # We need to find the "Content" key preceding it.
                # But to be safe, let's look for known content key or just take the one before.
                if len(keys) >= 2:
                    content_key = keys[-2]
                    full_text = data[content_key] + "\n\n" + data["References"]
                    last_key = content_key  # We will update this content key
                else:
                    # Should not verify happen if we have headers
                    full_text = data["References"]
                    last_key = "References"  # Weird case
            else:
                # References exists but is not the last key?
                # Or maybe it is the last key but we just grabbed keys[-1].
                # Let's be explicit.
                full_text = data[last_key] + "\n\n" + data["References"]

        content, refs = split_references(full_text)

        if refs:
            # Update the last key with stripped content
            data[last_key] = content
            # Add/Update References key
            data["References"] = refs

            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)

            return True, file_path.name, "References extracted (updated)"
        else:
            # If we previously had references but now find none (unlikely with looser heuristic but possible)
            # We should probably remove the References key and restore content.
            if "References" in data:
                data[last_key] = full_text
                del data["References"]
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=4)
                return True, file_path.name, "References removed (re-merged)"

            return True, file_path.name, "No references found"

    except Exception as e:
        return False, file_path.name, str(e)


@click.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
def extract_refs(directory):
    """Extract references from JSON files in DIRECTORY."""

    data_dir = Path(directory)
    files = list(data_dir.glob("*_processed.json"))

    print(f"Found {len(files)} files in {directory}")

    success_count = 0
    extracted_count = 0
    fail_count = 0

    with Progress(SpinnerColumn(), *Progress.get_default_columns(), TimeElapsedColumn()) as progress:
        task = progress.add_task("[green]Processing", total=len(files))

        results = Parallel(n_jobs=-1, return_as="generator")(delayed(process_file)(p) for p in files)

        for success, name, msg in results:
            progress.update(task, advance=1)
            if success:
                success_count += 1
                if "References extracted" in msg:
                    extracted_count += 1
            else:
                fail_count += 1
                progress.console.print(f"[red]Error on {name}: {msg}[/red]")

    print(f"\nCompleted. Processed: {success_count}, With References: {extracted_count}, Failed: {fail_count}")


if __name__ == "__main__":
    extract_refs()
