from __future__ import annotations

import chromadb
from chromadb import Collection

from app.config import CHROMA_PATH
from app.logger import logger

_client: chromadb.PersistentClient | None = None
_collection: Collection | None = None


def get_collection() -> Collection:
    global _client, _collection
    if _collection is None:
        from app.services.embedder import get_embedding_function
        logger.info("Инициализация ChromaDB: %s", CHROMA_PATH)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            "chroma",
            embedding_function=get_embedding_function(),
        )
        logger.info("ChromaDB готов, документов: %d", _collection.count())
    return _collection
