import glob
import json
import logging
import os
from pathlib import Path

from joblib import Parallel, delayed

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def get_corpus_id(item):
    """Helper to extract ID safely and normalize to string."""
    if isinstance(item, dict):
        cid = item.get("corpus_id")
        if isinstance(cid, list) and len(cid) > 0:
            return str(cid[0])
        if cid is not None:
            return str(cid)
    return None


def read_file_items(file_path):
    """
    Reads a file and returns its content normalized to a list of items,
    along with structure information to allow valid rewriting.
    """
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], "invalid", None

    if isinstance(data, list):
        return data, "list", data

    if isinstance(data, dict):
        if "response" in data and "docs" in data["response"]:
            return data["response"]["docs"], "solr_dict", data
        elif "corpus_id" in data:
            # Single document
            return [data], "single_dict", data

    return [], "unknown", data


def scan_file_for_ids(file_path):
    """
    Pass 1 Worker: Reads file and returns a set of corpus_ids found.
    """
    items, _, _ = read_file_items(file_path)
    ids = set()
    for item in items:
        cid = get_corpus_id(item)
        if cid:
            ids.add(cid)
    return file_path, ids


def split_and_delete_file(file_path, ids_to_extract):
    """
    Pass 2 Worker: Reads file, extracts assigned IDs to individual files,
    and removes the original file if successful.
    """
    items, structure_type, _ = read_file_items(file_path)

    # Handle bad files (just delete them)
    if structure_type in (
        "invalid",
        "unknown",
        "empty",
    ):  # Added 'empty' in case logic changes, but for now scan handles it
        try:
            os.remove(file_path)
            return file_path, f"deleted_{structure_type}"
        except OSError:
            return file_path, "error_delete"

    # If we have no work for this file (ids_to_extract is empty),
    # AND it was a valid file, it means all its contents were duplicates found elsewhere.
    # So we should just delete it.
    # BUT wait: verify that 'ids_to_extract' being empty implies we drop the file.
    # Yes, per requirements: "Delete the original file".
    # And if we extracted nothing, we produce 0 output files.

    extracted_count = 0
    errors = 0

    parent_dir = Path(file_path).parent

    for item in items:
        cid = get_corpus_id(item)
        if cid and cid in ids_to_extract:
            target_path = parent_dir / f"{cid}.json"
            try:
                with open(target_path, "w") as f:
                    json.dump(item, f, indent=2)
                extracted_count += 1
            except OSError:
                errors += 1

    # After processing all items, delete the original
    if errors == 0:
        try:
            os.remove(file_path)
            # Return 'split' status or 'deleted' if nothing was extracted
            return file_path, "split" if extracted_count > 0 else "deleted_duplicates"
        except OSError:
            return file_path, "error_delete_original"
    else:
        # If we failed to write some sub-files, do we keep the original?
        # Safety first: Keep original if errors occurred.
        return file_path, "error_write_subfiles"


def main(root_dir=None):
    if root_dir is None:
        root_dir = Path("/Users/jnavarro/callm/climpdfgetter/data/all_titanv_search_results_2025-11-24_16:56:30")
        if not root_dir.exists():
            root_dir = Path("/Users/jnavarro/callm/climpdfgetter/data/titanv_search_results_2025-11-24_16:56:30")
    else:
        root_dir = Path(root_dir)

    logging.info(f"Target directory: {root_dir}")

    # 1. Listing files
    logging.info("Listing files...")
    files = sorted(glob.glob(str(root_dir / "**" / "*.json"), recursive=True))
    logging.info(f"Found {len(files)} files to process.")

    # 2. Parallel Scan for IDs
    logging.info("Starting PASS 1: Scanning for IDs...")
    results = Parallel(n_jobs=-1, verbose=5)(delayed(scan_file_for_ids)(f) for f in files)

    claimed_ids = set()
    files_with_work = []

    for file_path, found_ids in results:
        if not found_ids:
            files_with_work.append((file_path, set()))
            continue

        ids_to_keep = set()
        for cid in found_ids:
            if cid not in claimed_ids:
                claimed_ids.add(cid)
                ids_to_keep.add(cid)

        files_with_work.append((file_path, ids_to_keep))

    logging.info(f"ID Consolidation: {len(claimed_ids)} unique IDs found.")

    # 3. Parallel Split & Delete
    logging.info("Starting PASS 2: Splitting files and deleting originals...")
    rewrite_results = Parallel(n_jobs=-1, verbose=5)(
        delayed(split_and_delete_file)(fp, keep_set) for fp, keep_set in files_with_work
    )

    # 4. Summary
    status_counts = {}
    for _, status in rewrite_results:
        status_counts[status] = status_counts.get(status, 0) + 1

    logging.info("-" * 20)
    logging.info("Processing complete.")
    logging.info(f"Total unique IDs identified: {len(claimed_ids)}")
    logging.info("File Operation Status:")
    for status, count in sorted(status_counts.items()):
        logging.info(f"  {status}: {count}")


if __name__ == "__main__":
    main()
