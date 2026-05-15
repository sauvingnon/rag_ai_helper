import time
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/ai_service", tags=["eval"])


class EvalQueryRequest(BaseModel):
    query: str


class EvalFullRequest(BaseModel):
    question: str


class EmbedRequest(BaseModel):
    texts: list[str]


@router.post("/eval_query")
def eval_query(body: EvalQueryRequest):
    """Детали retrieval-пайплайна для одного запроса.

    Возвращает:
    - raw_chunks: топ-K от SBERT (без фильтрации)
    - reranked_chunks: топ после Cross-Encoder с оценками
    - best_score: максимальный Cross-Encoder score
    - filtered_by_threshold: True если best_score < RERANK_THRESHOLD
    - search_time / rerank_time: латентность компонентов
    """
    from app.services.embeddings_service.db_client import get_collection
    from app.services.embeddings_service.models import cross_encoder
    from app.config import TOP_K, RERANK_TOP, RERANK_THRESHOLD

    query = body.query

    # ── SBERT поиск ──────────────────────────────────────────────────────────
    t0 = time.monotonic()
    results = get_collection().query(query_texts=[query], n_results=TOP_K)
    search_time = time.monotonic() - t0

    raw_chunks = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        raw_chunks.append({
            "name": meta.get("name", ""),
            "document": doc[:300],
        })

    if not raw_chunks:
        return {
            "search_time": round(search_time, 4),
            "rerank_time": 0.0,
            "raw_chunks": [],
            "reranked_chunks": [],
            "rerank_scores": [],
            "best_score": None,
            "filtered_by_threshold": True,
        }

    # ── Cross-Encoder rerank ──────────────────────────────────────────────────
    full_chunks = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        full_chunks.append({
            "name": meta.get("name", ""),
            "document": doc,
            "text": meta.get("text", ""),
        })

    t1 = time.monotonic()
    pairs = [(query, ch["document"]) for ch in full_chunks]
    scores = cross_encoder.predict(pairs).tolist()
    rerank_time = time.monotonic() - t1

    scored = sorted(zip(scores, full_chunks), key=lambda x: x[0], reverse=True)
    best_score = scored[0][0] if scored else -999.0
    filtered = best_score < RERANK_THRESHOLD

    reranked = []
    rerank_scores = []
    for s, ch in scored[:RERANK_TOP]:
        reranked.append({"name": ch.get("name", ""), "document": ch["document"][:300]})
        rerank_scores.append(round(float(s), 4))

    return {
        "search_time": round(search_time, 4),
        "rerank_time": round(rerank_time, 4),
        "raw_chunks": raw_chunks,
        "reranked_chunks": reranked,
        "rerank_scores": rerank_scores,
        "best_score": round(float(best_score), 4),
        "filtered_by_threshold": filtered,
    }


@router.post("/eval_full")
async def eval_full(body: EvalFullRequest):
    """Полный цикл агента + метрики retrieval за один вызов.

    Патчит _execute_search чтобы перехватить вызовы поиска изнутри агента
    и записать timing/scores без повторного запуска Cross-Encoder.
    """
    import app.services.llm_service.llm_request as llm_mod
    from app.services.embeddings_service.search_pipeline import search as _sbert_search
    from app.services.embeddings_service.models import cross_encoder
    from app.config import RERANK_TOP, RERANK_THRESHOLD

    search_log: list[dict] = []
    original = llm_mod._execute_search

    def _instrumented_search(query: str) -> str:
        # SBERT
        t0 = time.monotonic()
        chunks = _sbert_search(query=query)
        search_ms = (time.monotonic() - t0) * 1000

        if not chunks:
            search_log.append({
                "query": query, "search_ms": round(search_ms, 1),
                "rerank_ms": 0, "best_score": None,
                "filtered": True, "top_chunk": None, "top_scores": [],
            })
            return "Информация по запросу не найдена."

        # Cross-Encoder
        t1 = time.monotonic()
        pairs = [(query, ch["document"]) for ch in chunks]
        scores = cross_encoder.predict(pairs).tolist()
        rerank_ms = (time.monotonic() - t1) * 1000

        scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        best_score = scored[0][0] if scored else -999.0
        filtered = best_score < RERANK_THRESHOLD
        top = [ch for _, ch in scored[:RERANK_TOP]] if not filtered else None

        search_log.append({
            "query": query,
            "search_ms": round(search_ms, 1),
            "rerank_ms": round(rerank_ms, 1),
            "best_score": round(float(best_score), 4),
            "filtered": filtered,
            "top_chunk": scored[0][1].get("name", "") if scored else None,
            "top_chunks": [ch.get("name", "") for _, ch in scored[:RERANK_TOP]],
            "top_scores": [round(float(s), 4) for s, _ in scored[:RERANK_TOP]],
        })

        if top is None:
            return "Релевантной информации не найдено."

        lines = []
        for i, ch in enumerate(top, 1):
            name = ch.get("name", "")
            text = ch.get("text") or ch.get("document", "")
            lines.append(f"[{i}] {name}\n{text.strip()}")
            if ch.get("notes"):
                lines.append(f"    Примечание: {ch['notes'].strip()}")
        return "\n".join(lines)

    llm_mod._execute_search = _instrumented_search
    t_start = time.monotonic()
    try:
        from app.services.llm_service.llm_request import ai_agent_stream
        sentences = []
        async for sentence in ai_agent_stream(body.question, history=[], user_name=""):
            sentences.append(sentence)
        answer = " ".join(sentences)
    finally:
        llm_mod._execute_search = original

    total_ms = (time.monotonic() - t_start) * 1000

    search_ms_list = [s["search_ms"] for s in search_log]
    rerank_ms_list = [s["rerank_ms"] for s in search_log]
    best_scores = [s["best_score"] for s in search_log if s["best_score"] is not None]

    return {
        "answer": answer,
        "total_ms": round(total_ms, 1),
        "search_count": len(search_log),
        "search_log": search_log,
        "search_ms_total": round(sum(search_ms_list), 1),
        "rerank_ms_total": round(sum(rerank_ms_list), 1),
        "best_score": round(max(best_scores), 4) if best_scores else None,
        "filtered_by_threshold": all(s["filtered"] for s in search_log) if search_log else True,
        "top_chunk": search_log[0]["top_chunk"] if search_log else None,
    }


@router.post("/embed")
def embed_texts(body: EmbedRequest):
    """Эмбеддинги через SBERT — для вычисления Answer Relevance."""
    from app.services.embeddings_service.models import sbert_model
    vectors = sbert_model.encode(body.texts, normalize_embeddings=True).tolist()
    return {"embeddings": vectors}
