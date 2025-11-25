import glob
import json
from pathlib import Path


def main():
    data_dir = Path("/Users/jnavarro/callm/climpdfgetter/data")
    checkpoint_file = data_dir / "combined_titanv_checkpoint.json"
    search_results_dir = data_dir / "titanv_search_results_2025-11-24_16:56:30"

    all_ids = set()

    # Load existing checkpoint
    if checkpoint_file.exists():
        print(f"Loading existing checkpoint from {checkpoint_file}...")
        with open(checkpoint_file, "r") as f:
            existing_ids = json.load(f)
            all_ids.update(existing_ids)
        print(f"Loaded {len(all_ids)} existing IDs.")
    else:
        print("Checkpoint file not found. Starting fresh.")

    # Process search results directory
    print(f"Processing {search_results_dir}...")
    # Recursive search for json files
    json_files = glob.glob(str(search_results_dir / "**" / "*.json"), recursive=True)
    print(f"Found {len(json_files)} JSON files.")

    for i, f in enumerate(json_files):
        if i % 100 == 0:
            print(f"Processing file {i}/{len(json_files)}...")
        try:
            with open(f, "r") as fp:
                try:
                    content = json.load(fp)
                except json.JSONDecodeError:
                    print(f"Skipping invalid JSON: {f}")
                    continue

                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "corpus_id" in item:
                            all_ids.add(str(item["corpus_id"]))
                elif isinstance(content, dict):
                    # Handle potential dict structure similar to previous task
                    if "response" in content and "docs" in content["response"]:
                        for doc in content["response"]["docs"]:
                            if "corpus_id" in doc:
                                c_id = doc["corpus_id"]
                                if isinstance(c_id, list) and len(c_id) > 0:
                                    all_ids.add(str(c_id[0]))
                                else:
                                    all_ids.add(str(c_id))
                    elif "corpus_id" in content:
                        all_ids.add(str(content["corpus_id"]))

        except Exception as e:
            print(f"Error reading {f}: {e}")

    print(f"Total unique IDs after update: {len(all_ids)}")

    # Write to file
    with open(checkpoint_file, "w") as f:
        json.dump(list(sorted(all_ids)), f, indent=2)
    print(f"Updated {checkpoint_file}")


if __name__ == "__main__":
    main()
