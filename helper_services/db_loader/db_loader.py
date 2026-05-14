# Скрипт для загрузки документов в формате yaml в векторную базу данных
# с использованием локальной или интернет-модели
import logging
from pathlib import Path
import yaml
import chromadb
from sentence_transformers import SentenceTransformer
from local_embedding import LocalEmbeddingFunction

# Настройка логов
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Константы
BASE_DIR = Path.cwd()
MODEL_PATH = BASE_DIR / "helper_services" / "ai_service" / "models" / "sbert_model"

script_dir = Path(__file__).resolve().parent
data_base_dir = script_dir / "chroma_db"
data_files_dir = script_dir / "data"


def load_yaml_files(data_dir: Path) -> list[dict]:
    """Чтение всех yaml/yml файлов в директории"""
    yaml_files = list(data_dir.rglob("*.y*ml"))
    logging.info(f"Найдено YAML файлов: {len(yaml_files)}")

    chunks = []
    for file_path in yaml_files:
        logging.info(f"Загружаем файл: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, list):
                chunks.extend(data)
            elif isinstance(data, dict):
                chunks.append(data)
    return chunks


def build_enriched_text(ch: dict) -> str:
    """Формируем текст для эмбеддинга"""
    parts = [ch.get("name", "")]
    if ch.get("text"):
        parts.append(f"Описание: {ch['text']}")
    if ch.get("keywords"):
        parts.append(f"Ключевые слова: {ch['keywords']}")
    notes = ch.get("meta", {}).get("notes", "")
    if notes:
        parts.append(f"Контакты и примечания: {notes}")
    return "\n".join(parts)


def main():
    # Загружаем модель
    if MODEL_PATH.exists():
        logging.info(f"Loading SBERT model from local path: {MODEL_PATH}")
        sbert_model = SentenceTransformer(str(MODEL_PATH))
    else:
        raise ValueError(f"Модель локально не найдена, загрузите модель в локальную папку {MODEL_PATH}")

    # Инициализация ChromaDB
    client = chromadb.PersistentClient(path=str(data_base_dir))
    embedding_fn = LocalEmbeddingFunction(sbert_model)
    collection = client.get_or_create_collection(
        "chroma", embedding_function=embedding_fn
    )

    # Загружаем YAML
    chunks = load_yaml_files(data_files_dir)
    logging.info(f"Итоговое кол-во чанков: {len(chunks)}")

    if not chunks:
        raise ValueError(f"Нет данных для загрузки.")

    # Подготавливаем данные для батчевой вставки
    texts = [build_enriched_text(ch) for ch in chunks]
    embeddings = sbert_model.encode(texts, batch_size=32, show_progress_bar=True).tolist()

    ids = []
    metadatas = []
    for ch in chunks:
        doc_id = ch.get("id") or f"{ch.get('name', 'doc')}_{len(ids)}"
        ids.append(doc_id)

        meta = ch.get("meta", {})
        metadatas.append(
            {
                "type": ch.get("type", ""),
                "name": ch.get("name", ""),
                "text": ch.get("text", ""),
                "keywords": ch.get("keywords", ""),
                "notes": meta.get("notes", ""),
            }
        )

    # Добавляем в Chroma одним батчем
    collection.add(documents=texts, metadatas=metadatas, ids=ids, embeddings=embeddings)

    logging.info("Загрузка базы данных завершена!")


if __name__ == "__main__":
    main()
