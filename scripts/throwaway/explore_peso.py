import pandas as pd
import torch
from datasets import load_dataset
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from climpdfgetter.searches import RESILIENCE_SEARCHES

# 1. Loading the dataset
dataset = load_dataset("allenai/peS2o")
val_split = dataset["validation"]
print(f"Original validation size: {len(val_split)}")

# 2. Filter for s2orc/valid first (approx 100k rows)
s2orc_val = val_split.filter(lambda x: x["source"] == "s2orc/train")
print(f"Total s2orc/valid rows: {len(s2orc_val)}")

# 3. Search for each keyword
print("\nSearching for keywords in s2orc/valid...")
keyword_counts = {}

for keyword in RESILIENCE_SEARCHES:
    kw_lower = keyword.lower()
    # Using filter to count occurrences
    matches = s2orc_val.filter(lambda x: kw_lower in x["text"].lower(), num_proc=4)
    count = len(matches)
    keyword_counts[keyword] = count
    print(f"- {keyword}: {count}")

# 4. Summary Table
print("\n--- Summary Table ---")
df = pd.DataFrame(list(keyword_counts.items()), columns=["Keyword", "Count"])
print(df.sort_values(by="Count", ascending=False).to_string(index=False))

# Keep the rest of the demo code but update it to use a relevant result
if keyword_counts:
    best_keyword = max(keyword_counts, key=keyword_counts.get)
    print(f"\nTop keyword: {best_keyword}")
    filtered_train = s2orc_val.filter(lambda x: best_keyword.lower() in x["text"].lower())
else:
    filtered_train = s2orc_val

# 3. Using SentenceTransformers for Semantic Search
# This helps find entries that are semantically related even if they don't share keywords.
print("\nInitializing SentenceTransformer...")
device = "mps" if torch.backends.mps.is_available() else "cpu"
model = SentenceTransformer("all-MiniLM-L6-v2", device=device)

# Let's take a small subset for demonstration
subset = filtered_train.select(range(min(10, len(filtered_train))))
texts = subset["text"]

print(f"Encoding {len(texts)} documents...")
embeddings = model.encode(texts, show_progress_bar=True)

print(f"Embeddings shape: {embeddings.shape}")

# Example query
query = "global warming impacts on agriculture"
query_embedding = model.encode([query])

# Simple cosine similarity (manual)

similarities = cosine_similarity(query_embedding, embeddings)
best_idx = similarities.argmax()

print(f"\nQuery: {query}")
print(f"Most similar document (Index {best_idx}):")  # noqa
print(texts[best_idx][:200] + "...")
