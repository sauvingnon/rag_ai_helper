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


def _clear_chroma_cache() -> None:
    """Сбрасывает внутренний per-path синглтон chromadb (API зависит от версии)."""
    try:
        chromadb.PersistentClient.clear_system_cache()
        return
    except AttributeError:
        pass
    try:
        from chromadb.api.client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
        return
    except Exception:
        pass
    logger.warning("clear_system_cache недоступен — новый клиент может видеть кэш")


def reload_collection() -> int:
    global _client, _collection
    # Сначала строим новый клиент, потом свапаем атомарно —
    # чтобы не было окна, когда _collection == None и поисковый поток падает.
    _clear_chroma_cache()
    new_client = chromadb.PersistentClient(path=_CHROMA_PATH)
    new_collection = new_client.get_or_create_collection("chroma", embedding_function=_embedding_fn)
    count = new_collection.count()
    _client = new_client
    _collection = new_collection
    logger.info("ChromaDB перезагружена. Документов: %d", count)
    return count
