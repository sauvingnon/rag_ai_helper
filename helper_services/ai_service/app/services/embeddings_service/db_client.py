import chromadb
from app.services.embeddings_service.models import sbert_model
from app.logger import logger
from .local_embedding import LocalEmbeddingFunction

_CHROMA_PATH = "/app/services/embeddings_service/chroma_db"
_embedding_fn = LocalEmbeddingFunction(sbert_model)

logger.info("Подготовка базы данных")

_client = chromadb.PersistentClient(path=_CHROMA_PATH)
_collection = _client.get_or_create_collection("chroma", embedding_function=_embedding_fn)

logger.info("База данных готова. Документов: %d", _collection.count())


def get_collection():
    return _collection


def reload_collection() -> int:
    global _client, _collection
    _client = chromadb.PersistentClient(path=_CHROMA_PATH)
    _collection = _client.get_or_create_collection("chroma", embedding_function=_embedding_fn)
    count = _collection.count()
    logger.info("ChromaDB перезагружена. Документов: %d", count)
    return count
