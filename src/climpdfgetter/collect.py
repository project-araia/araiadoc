import json
from pathlib import Path

from climpdfgetter.utils import _find_project_root

all_docs = []
all_stems = []
all_metadata = []

data_root = Path(_find_project_root()) / Path("data/")

# get all files based on unique stems
for directory in data_root.iterdir():
    if directory.is_dir() and directory.name.startswith("OSTI"):
        for doc in directory.iterdir():
            if doc.stem.isdigit() and doc.stem not in all_stems:
                all_docs.append(doc)
                all_stems.append(doc.stem)
        metadata = directory / "OSTI.GOV-metadata.json"
        with open(metadata, "r") as f:
            metadata = json.load(f)
        for doc in metadata:
            all_metadata.append(doc)

with open(data_root / "OSTI_doc_ids.json", "w") as f:
    json.dump(all_stems, f)

combined_dir = data_root / "combined"
combined_dir.mkdir(exist_ok=True)

for doc in all_docs:
    doc.rename(combined_dir / doc.name)

with open(combined_dir / "metadata.json", "w") as f:
    json.dump(all_metadata, f)

print(len(all_stems))
