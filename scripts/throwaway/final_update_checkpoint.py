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
    data_dir = Path("/Users/jnavarro/callm/climpdfgetter/data")
    checkpoint_file = data_dir / "combined_titanv_checkpoint.json"
    search_results_dir = data_dir / "titanv_search_results_2025-12-08_15:27:00"

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

    # Process search results
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

    with open(checkpoint_file, "w") as f:
        json.dump(sorted(list(all_ids)), f, indent=2)
    print(f"Updated {checkpoint_file}")


if __name__ == "__main__":
    main()
