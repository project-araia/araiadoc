import pickle

import pandas as pd
from sentence_transformers import SentenceTransformer

# Load data
df = pd.read_csv("../../data/climate_ID_600k_label.csv")
df["combined_text"] = df["abstract"] + " " + df["title"] + " " + df["field"]


# Load a sentence transformer model
model = SentenceTransformer("all-MiniLM-L6-v2", device="mps")

# Encode documents
document_embeddings = model.encode(df["combined_text"].tolist()[:1000], show_progress_bar=True)

pickle.dump(document_embeddings, open("../../data/document_embeddings.pkl", "wb"))
