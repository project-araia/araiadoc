import glob
import json
import os
from collections import Counter


def extract_keys():
    base_dir = "/Users/jnavarro/callm/climpdfgetter/data/600k_titanv_results_12-1_sectionized"
    # Artifact path provided by the system
    output_file = "/Users/jnavarro/callm/climpdfgetter/data/post_conclusion_keys.md"

    pattern = os.path.join(base_dir, "**/*processed.json")
    files = glob.glob(pattern, recursive=True)

    post_conclusion_keys = Counter()

    print(f"Scanning {len(files)} files...")

    for filepath in files:
        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                continue

            keys = list(data.keys())
            found_conclusion = False

            for key in keys:
                if found_conclusion:
                    post_conclusion_keys[key] += 1
                    continue

                if "conclusion" in key.lower():
                    found_conclusion = True

        except Exception:
            # Silently skip errors to keep output clean, or log to stderr
            pass

    # Write to artifact
    with open(output_file, "w") as f:
        f.write("# Post-Conclusion Dictionary Keys\n\n")
        f.write(f"Scanned {len(files)} files.\n")
        f.write(f"Found {len(post_conclusion_keys)} unique keys appearing after 'conclusion' sections.\n\n")
        f.write("| Key | Frequency |\n")
        f.write("| --- | --- |\n")
        for key, count in post_conclusion_keys.most_common():
            # Escape pipes in keys just in case
            safe_key = key.replace("|", "\\|")
            f.write(f"| {safe_key} | {count} |\n")

    print(f"Report generated at {output_file}")


if __name__ == "__main__":
    extract_keys()
