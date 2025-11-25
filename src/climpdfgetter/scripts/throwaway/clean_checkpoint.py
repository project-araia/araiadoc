import json
from pathlib import Path


def main():
    data_dir = Path("/Users/jnavarro/callm/climpdfgetter/data")
    checkpoint_file = data_dir / "combined_titanv_checkpoint.json"

    if not checkpoint_file.exists():
        print(f"File not found: {checkpoint_file}")
        return

    print(f"Reading {checkpoint_file}...")
    with open(checkpoint_file, "r") as f:
        ids = json.load(f)

    print(f"Total IDs before cleaning: {len(ids)}")

    cleaned_ids = set()
    for item in ids:
        # Ensure item is a string
        s_item = str(item)
        # Remove square brackets if present
        if s_item.startswith("[") and s_item.endswith("]"):
            s_item = s_item[1:-1]

        # Add to set to remove duplicates
        cleaned_ids.add(s_item)

    print(f"Total unique IDs after cleaning: {len(cleaned_ids)}")

    with open(checkpoint_file, "w") as f:
        json.dump(list(sorted(cleaned_ids)), f, indent=2)
    print(f"Updated {checkpoint_file}")


if __name__ == "__main__":
    main()
