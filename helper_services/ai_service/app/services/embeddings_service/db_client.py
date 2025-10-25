# Работа с вектороной базой данных
import chromadb
from app.services.embeddings_service.models import sbert_model
from app.logger import logger
from .local_embedding import LocalEmbeddingFunction

logger.info("Подготовка базы данных")

# создаём persistent client
client = chromadb.PersistentClient(path="/app/services/embeddings_service/chroma_db")

embedding_fn = LocalEmbeddingFunction(sbert_model)

collection = client.get_or_create_collection(
    "chroma",
    embedding_function=embedding_fn
)

logger.info(f"База данных готова к работе. Количество документов: {collection.count()}")
