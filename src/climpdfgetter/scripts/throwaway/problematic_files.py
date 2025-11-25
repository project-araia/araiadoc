import json
import os

problem_files = []

SEARCH_RESULTS = "/Users/jnavarro/callm/climpdfgetter/data/titanv_search_results_2025-11-24_16:56:30"

for directory in os.listdir(SEARCH_RESULTS):
    if not os.path.isdir(os.path.join(SEARCH_RESULTS, directory)):
        continue
    for file in os.listdir(os.path.join(SEARCH_RESULTS, directory)):
        if file.endswith(".json"):
            with open(os.path.join(SEARCH_RESULTS, directory, file), "r") as f:
                try:
                    content = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    print(f"Skipping invalid JSON: {os.path.join(directory, file)}")
                    problem_files.append(os.path.join(directory, file))
                    continue

# delete all files in problem_files
for file in problem_files:
    os.remove(os.path.join(SEARCH_RESULTS, file))
