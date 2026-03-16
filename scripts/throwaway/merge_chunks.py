import glob
import os
import shutil
from pathlib import Path


def merge_chunks(data_dir, target_dir_name):
    target_dir = Path(data_dir) / target_dir_name
    if not target_dir.exists():
        os.makedirs(target_dir)
        print(f"Created target directory: {target_dir}")
    else:
        print(f"Target directory exists: {target_dir}")

    # Find all source directories matching the pattern
    source_pattern = os.path.join(data_dir, "600k_titanv_results_v2_*")
    source_dirs = glob.glob(source_pattern)

    # Filter out directories that might be the target itself if created previously or named similarly
    source_dirs = [d for d in source_dirs if Path(d).name != target_dir_name and os.path.isdir(d)]

    print(f"Found source directories: {[Path(d).name for d in source_dirs]}")

    count = 0
    for source_dir in source_dirs:
        # Walk through chunks
        for root, dirs, files in os.walk(source_dir):
            # We are looking for files within chunk subdirectories
            # The structure is assumed to be source_dir/chunk_X/file.json

            # Check if current root is a 'chunk' directory
            rel_path = os.path.relpath(root, source_dir)
            if rel_path.startswith("chunk_"):
                print(f"Processing {rel_path} in {Path(source_dir).name}...")
                for file in files:
                    if file.endswith(".json"):
                        src_file = Path(root) / file
                        dst_file = target_dir / file

                        # Check for collision
                        if dst_file.exists():
                            print(f"Warning: {file} already exists in target. Overwriting.")

                        shutil.copy2(src_file, dst_file)
                        count += 1
                        if count % 1000 == 0:
                            print(f"Merged {count} files...")

    print(f"Total files merged: {count}")


if __name__ == "__main__":
    data_directory = "/Users/jnavarro/callm/climpdfgetter/data"
    merged_directory_name = "600k_titanv_results_merged"
    merge_chunks(data_directory, merged_directory_name)
