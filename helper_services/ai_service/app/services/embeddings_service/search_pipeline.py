from app.config import TOP_K, RERANK_TOP
from .db_client import collection
from .models import cross_encoder

# Поиск top-K через Chroma
def search(query, top_k=TOP_K):
    results = collection.query(
        query_texts=[query],
        n_results=top_k
    )
    # Chroma возвращает dict: {"ids": ..., "documents": ..., "metadatas": ...}
    chunks = []
    for document, meta in zip(results["documents"][0], results["metadatas"][0]):
        chunks.append({
            "document": document,
            "type": meta.get("type"),
            "name": meta.get("name"),
            "text": meta.get("text"),
            "keywords": meta.get("keywords"),
            "notes": meta.get("notes")
        })
    return chunks


# Реранк через Cross-Encoder
def rerank(query, chunks, top_rerank=RERANK_TOP):
    pairs = []
    for ch in chunks:
        text = ch.get("document")
        pairs.append((query, text))
    
    scores = cross_encoder.predict(pairs)
    scored_chunks = list(zip(scores, chunks))
    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    return [ch for _, ch in scored_chunks[:int(top_rerank)]]

