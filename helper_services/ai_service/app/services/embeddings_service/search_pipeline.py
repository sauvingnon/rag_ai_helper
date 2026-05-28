from app.config import TOP_K, RERANK_TOP, RERANK_THRESHOLD, USE_CROSS_ENCODER
from .db_client import get_collection
from .models import cross_encoder


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    results = get_collection().query(query_texts=[query], n_results=top_k)
    chunks = []
    for document, meta in zip(results["documents"][0], results["metadatas"][0]):
        chunks.append({
            "document": document,
            "type": meta.get("type"),
            "name": meta.get("name"),
            "text": meta.get("text"),
            "keywords": meta.get("keywords"),
            "notes": meta.get("notes"),
        })
    return chunks


def rerank(query: str, chunks: list[dict], top_rerank: int = RERANK_TOP) -> list[dict] | None:
    """Возвращает None если лучший score ниже порога — запрос нерелевантен базе.
    Если USE_CROSS_ENCODER=false — возвращает первые top_rerank результатов SBERT без реранкинга."""
    if not USE_CROSS_ENCODER:
        return chunks[:int(top_rerank)]

    pairs = [(query, ch["document"]) for ch in chunks]
    scores = cross_encoder.predict(pairs)
    scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)

    best_score = scored[0][0] if scored else -999
    if best_score < RERANK_THRESHOLD:
        return None  # ничего релевантного нет

    return [ch for _, ch in scored[:int(top_rerank)]]
