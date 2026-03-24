import argparse
import glob
import json
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
    parser = argparse.ArgumentParser(description="Update checkpoint from search results.")
    parser.add_argument("checkpoint_file", type=Path, help="Path to the checkpoint JSON file.")
    parser.add_argument("search_results_dir", type=Path, help="Directory containing search results JSON files.")
    args = parser.parse_args()

    checkpoint_file = args.checkpoint_file
    search_results_dir = args.search_results_dir

    all_ids = set()

    # Load existing checkpoint
    if checkpoint_file.exists():
        print(f"Loading existing checkpoint from {checkpoint_file}...")
        with open(checkpoint_file, "r") as f:
            existing_ids = json.load(f)
            for i in existing_ids:
                s_item = str(i)
                # Ensure we don't have brackets
                if s_item.startswith("[") and s_item.endswith("]"):
                    s_item = s_item[1:-1]
                all_ids.add(s_item)
        print(f"Loaded {len(all_ids)} existing IDs.")
    else:
        print(f"Checkpoint file {checkpoint_file} not found. Starting fresh.")

    # Process search results
    if not search_results_dir.exists():
        print(f"Search results directory {search_results_dir} not found.")
        return

    print(f"Processing {search_results_dir}...")
    files = glob.glob(str(search_results_dir / "**" / "*.json"), recursive=True)
    print(f"Found {len(files)} files to process.")

    for i, f_path in enumerate(files):
        if i % 1000 == 0:
            print(f"Processing file {i}/{len(files)}...")
        try:
            with open(f_path, "r") as f:
                data = json.load(f)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "response" in data and "docs" in data["response"]:
                    items = data["response"]["docs"]
                elif "corpus_id" in data:
                    items = [data]

            for item in items:
                cid = get_corpus_id(item)
                if cid:
                    all_ids.add(cid)

        except Exception as e:
            print(f"Error reading {f_path}: {e}")

    print(f"Total unique IDs: {len(all_ids)}")

    # Ensure parent directory of checkpoint file exists
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

    with open(checkpoint_file, "w") as f:
        json.dump(sorted(list(all_ids)), f, indent=2)
    print(f"Updated {checkpoint_file}")


if __name__ == "__main__":
    main()
