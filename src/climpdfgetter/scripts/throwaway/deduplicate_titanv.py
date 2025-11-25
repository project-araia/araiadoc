import glob
import json
import os
from pathlib import Path


def get_corpus_id(item):
    """Helper to extract ID safely and normalize to string."""
    if isinstance(item, dict):
        cid = item.get("corpus_id")
        if isinstance(cid, list) and len(cid) > 0:
            return str(cid[0])
        if cid is not None:
            return str(cid)
    return None


def main():
    root_dir = Path("/Users/jnavarro/callm/climpdfgetter/data/titanv_search_results_2025-11-24_16:56:30")
    seen_ids = set()

    # Sort files to ensure deterministic processing order
    print("Listing files...")
    files = sorted(glob.glob(str(root_dir / "**" / "*.json"), recursive=True))
    print(f"Found {len(files)} files to process.")

    deleted_files_count = 0
    modified_files_count = 0

    for i, file_path in enumerate(files):
        if i % 100 == 0:
            print(f"Processing {i}/{len(files)}...")

        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"Deleting invalid JSON: {file_path}")
            os.remove(file_path)
            deleted_files_count += 1
            continue

        # Determine list to filter
        items = []
        is_dict_structure = False

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "response" in data and "docs" in data["response"]:
            items = data["response"]["docs"]
            is_dict_structure = True
        else:
            # If it's a dict but not the expected structure, check if it has corpus_id directly (single doc?)
            # The previous scripts handled: if "corpus_id" in content
            if isinstance(data, dict) and "corpus_id" in data:
                # It's a single document
                items = [data]
                # We can treat it as a list of 1 for processing,
                # but writing back might need care if we want to preserve it being a dict.
                # However, if it's a duplicate, we delete the file.
                # If it's not, we keep it.
                # Let's handle this case.
                cid = get_corpus_id(data)
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    # Keep file as is
                    continue
                else:
                    # Duplicate
                    print(f"Deleting duplicate single-doc file: {file_path}")
                    os.remove(file_path)
                    deleted_files_count += 1
                    continue
            else:
                # Unknown structure or empty dict
                print(f"Deleting file with unknown structure: {file_path}")
                os.remove(file_path)
                deleted_files_count += 1
                continue

        new_items = []
        has_changes = False

        for item in items:
            cid = get_corpus_id(item)
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                new_items.append(item)
            else:
                # Duplicate or no ID
                has_changes = True

        if not new_items:
            # All items were duplicates
            # print(f"Deleting empty file (all duplicates): {file_path}")
            os.remove(file_path)
            deleted_files_count += 1
            continue

        if has_changes:
            # Write back
            if is_dict_structure:
                data["response"]["docs"] = new_items
            else:
                data = new_items

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            modified_files_count += 1

    print("-" * 20)
    print("Processing complete.")
    print(f"Total unique IDs found: {len(seen_ids)}")
    print(f"Files deleted (invalid/empty/duplicates): {deleted_files_count}")
    print(f"Files modified (partial duplicates removed): {modified_files_count}")


if __name__ == "__main__":
    main()
