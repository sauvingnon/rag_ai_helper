from __future__ import annotations

from chromadb import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer

from app.config import SBERT_MODEL_PATH
from app.logger import logger

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Загрузка SBERT: %s", SBERT_MODEL_PATH)
        _model = SentenceTransformer(SBERT_MODEL_PATH)
        logger.info("SBERT готов")
    return _model


class LocalEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: Documents) -> Embeddings:
        return get_model().encode(list(input)).tolist()


_fn: LocalEmbeddingFunction | None = None


def get_embedding_function() -> LocalEmbeddingFunction:
    global _fn
    if _fn is None:
        _fn = LocalEmbeddingFunction()
    return _fn
