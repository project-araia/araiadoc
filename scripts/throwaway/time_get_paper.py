import time
from pathlib import Path

from semanticscholar import SemanticScholar

data_dir = "../../data/old/600k_titanv_results_2025-12-23_sectionized_with_metadata"

all_file_prefixes = [i.stem for i in Path(data_dir).glob("*.json")][:100]

ss = SemanticScholar()

intervals = []
num_accessed = 0

try:
    for i in all_file_prefixes:
        start = time.time()
        paper = ss.get_paper("CorpusID:" + i)
        end = time.time()
        print(end - start)
        intervals.append(end - start)
        num_accessed += 1
except Exception as e:
    print(e)

average = sum(intervals) / len(intervals)
print("Average time: " + str(average))
print("Total time: " + str(sum(intervals)))
print("Number of accessed papers: " + str(num_accessed))
