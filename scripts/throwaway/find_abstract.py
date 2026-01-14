import os
import re

search_root = "/Users/jnavarro/callm/climpdfgetter/data/old/600k"
# Pattern 1: Literal newlines (0x0A 0x0A) followed by abstract
pattern_literal = re.compile(rb"\n\nabstract", re.IGNORECASE)
# Pattern 2: Escaped newlines (\n\n) followed by abstract (common in JSON)
pattern_escaped = re.compile(rb"\\n\\nabstract", re.IGNORECASE)

matches = []

print(f"Searching in {search_root}...")
count = 0
for root, dirs, files in os.walk(search_root):
    for filename in files:
        filepath = os.path.join(root, filename)
        # Skip generic large files if not relevant, but user said all files.
        # Typically these are .json.
        if not filename.endswith(".json"):
            continue

        count += 1
        try:
            with open(filepath, "rb") as f:
                content = f.read()
                if pattern_literal.search(content) or pattern_escaped.search(content):
                    matches.append(filepath)
        except Exception:
            pass

print(f"Scanned {count} files.")
print(f"Found {len(matches)} matches.")
with open("abstract_matches.txt", "w") as f:
    for m in matches:
        f.write(m + "\n")
print("Matches saved to abstract_matches.txt")
