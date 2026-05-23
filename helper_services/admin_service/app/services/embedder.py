from __future__ import annotations

import os

import httpx
from chromadb import EmbeddingFunction, Documents, Embeddings

from app.logger import logger

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai_service:8005")


class LocalEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        texts = list(input)
        logger.info("Запрос эмбеддингов у ai_service: %d текстов", len(texts))
        resp = httpx.post(
            f"{AI_SERVICE_URL}/ai_service/embed",
            json={"texts": texts},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


_fn: LocalEmbeddingFunction | None = None


def get_embedding_function() -> LocalEmbeddingFunction:
    global _fn
    if _fn is None:
        _fn = LocalEmbeddingFunction()
    return _fn
