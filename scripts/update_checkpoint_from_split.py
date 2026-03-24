import argparse
import json
import os


def update_checkpoint(source_dir, checkpoint_file):
    print(f"Reading checkpoint from {checkpoint_file}...")
    try:
        with open(checkpoint_file, "r") as f:
            existing_ids = set(json.load(f))
    except FileNotFoundError:
        print("Checkpoint file not found. Starting with empty set.")
        existing_ids = set()

    print(f"Loaded {len(existing_ids)} existing IDs.")

    new_ids = set()
    print(f"Scanning {source_dir}...")
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".json"):
                # Extract ID from filename
                file_id = os.path.splitext(file)[0]
                new_ids.add(file_id)

    print(f"Found {len(new_ids)} IDs in new directory.")

    combined_ids = existing_ids.union(new_ids)
    added_count = len(combined_ids) - len(existing_ids)
    print(f"Adding {added_count} new unique IDs.")

    # Sort for consistency
    sorted_ids = sorted(list(combined_ids))

    print(f"Writing {len(sorted_ids)} IDs to {checkpoint_file}...")
    with open(checkpoint_file, "w") as f:
        json.dump(sorted_ids, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update checkpoint from directory.")
    parser.add_argument("source_directory", type=str, help="Source directory with JSON files.")
    parser.add_argument("checkpoint_filename", type=str, help="Checkpoint filename.")
    args = parser.parse_args()

    update_checkpoint(args.source_directory, args.checkpoint_filename)
