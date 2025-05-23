from pathlib import Path

from climpdfgetter.utils import _find_project_root

# all_docs = []
# all_stems = []
# all_metadata = []

data_root = Path(_find_project_root()) / Path("data/")

# # get all files based on unique stems
# for directory in data_root.iterdir():
#     if directory.is_dir() and directory.name.startswith("OSTI"):
#         for doc in directory.iterdir():
#             if doc.stem.isdigit() and doc.stem not in all_stems:
#                 all_docs.append(doc)
#                 all_stems.append(doc.stem)
#         metadata = directory / "OSTI.GOV-metadata.json"
#         with open(metadata, "r") as f:
#             metadata = json.load(f)
#         for doc in metadata:
#             all_metadata.append(doc)

# with open(data_root / "OSTI_doc_ids.json", "w") as f:
#     json.dump(all_stems, f)

combined_dir = data_root / "combined"
# # combined_dir.mkdir(exist_ok=True)

# combined_new = data_root / "combined_new"

# # for doc in all_docs:
# #     doc.rename(combined_dir / doc.name)

# all_good_metadata = []
# all_good_docs = []

# with open(combined_dir / "metadata.json", "r") as f:
#     all_metadata = json.load(f)

# for i in combined_dir.iterdir():
#     for j in all_metadata:
#         if i.stem == j["osti_id"] and j["product_type"] == "Journal Article":
#             all_good_docs.append(i)
#             all_good_metadata.append(j)

# with open(combined_new / "metadata.json", "w") as f:
#     json.dump(all_good_metadata, f)

# all_good_docs = list(set(all_good_docs))

# for doc in all_good_docs:
#     doc.rename(combined_new / doc.name)

# print(len(all_good_metadata))

combined_already_json = Path("OSTI_combined_json")
pdf_dir = Path("OSTI_combined")

# if a token.json file is already in OSTI_combined_json, remove the corresponding pdf file from the data dir

for i in combined_already_json.iterdir():
    for j in pdf_dir.iterdir():
        if i.stem == j.stem:
            j.unlink()
