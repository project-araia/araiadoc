import json


def sort_checkpoint(checkpoint_file):
    print(f"Reading checkpoint from {checkpoint_file}...")
    try:
        with open(checkpoint_file, "r") as f:
            ids = json.load(f)
    except FileNotFoundError:
        print("Checkpoint file not found.")
        return

    print(f"Loaded {len(ids)} IDs.")

    unique_ids = sorted(list(set(ids)))

    print(f"Unique IDs: {len(unique_ids)}")
    print(f"Writing sorted unique IDs to {checkpoint_file}...")

    with open(checkpoint_file, "w") as f:
        json.dump(unique_ids, f, indent=2)
    print("Done.")


if __name__ == "__main__":
    checkpoint_filename = "/Users/jnavarro/callm/climpdfgetter/data/600k_titanv_checkpoint.json"
    sort_checkpoint(checkpoint_filename)
