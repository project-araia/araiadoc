import glob
import json
from pathlib import Path


def main():
    data_dir = Path("/Users/jnavarro/callm/climpdfgetter/data")
    dir_600k = data_dir / "600k_titanv_results_2025-11-10_08:52:38"
    dir_titanv = data_dir / "titanv_2025-11-04_10:03:40"
    output_file = data_dir / "combined_titanv_checkpoint.json"

    all_ids = set()

    # Process 600k directory
    print(f"Processing {dir_600k}...")
    chunk_files = glob.glob(str(dir_600k / "chunk_*" / "*.json"))
    print(f"Found {len(chunk_files)} files in 600k directory.")
    for f in chunk_files:
        p = Path(f)
        all_ids.add(p.stem)

    # Process titanv directory
    print(f"Processing {dir_titanv}...")
    titanv_files = glob.glob(str(dir_titanv / "*.json"))
    print(f"Found {len(titanv_files)} files in titanv directory.")

    for f in titanv_files:
        try:
            with open(f, "r") as fp:
                content = json.load(fp)

                if "response" in content and "docs" in content["response"]:
                    for doc in content["response"]["docs"]:
                        if "corpus_id" in doc:
                            c_id = doc["corpus_id"]
                            if isinstance(c_id, list) and len(c_id) > 0:
                                all_ids.add(str(c_id[0]))
                            else:
                                all_ids.add(str(c_id))
                elif isinstance(content, list):
                    for item in content:
                        if "corpus_id" in item:
                            all_ids.add(str(item["corpus_id"]))

        except Exception as e:
            print(f"Error reading {f}: {e}")

    print(f"Total unique IDs: {len(all_ids)}")

    # Write to file
    with open(output_file, "w") as f:
        json.dump(list(sorted(all_ids)), f, indent=2)
    print(f"Written to {output_file}")


if __name__ == "__main__":
    main()
