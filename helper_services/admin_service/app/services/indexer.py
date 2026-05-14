import os
from datetime import datetime, timezone

import httpx

from app.logger import logger
from app.services.chroma_client import get_collection
from app.services.llm_chunker import file_to_chunks
from app.services.task_store import update_task

_AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai_service:8005")


async def _notify_ai_reload() -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{_AI_SERVICE_URL}/reload-db")
        logger.info("ai_service: ChromaDB перезагружена")
    except Exception as e:
        logger.warning("Не удалось уведомить ai_service о перезагрузке: %s", e)


def _build_doc(ch: dict) -> str:
    notes = ch.get("notes") or (ch.get("meta") or {}).get("notes", "")
    parts = [
        ch.get("name", ""),
        f"Описание: {ch['text']}" if ch.get("text") else "",
        f"Ключевые слова: {ch['keywords']}" if ch.get("keywords") else "",
        f"Примечания: {notes}" if notes else "",
    ]
    return "\n".join(p for p in parts if p)


async def index_file(task_id: str, file_id: str, s3) -> None:
    update_task(task_id, status="running")
    try:
        result = await s3.download_file(file_id)
        if result is None:
            update_task(task_id, status="error", error="Файл не найден в S3")
            return
        content, meta = result

        chunks = await file_to_chunks(meta["filename"], content)
        if not chunks:
            update_task(task_id, status="error", error="Не удалось извлечь чанки из файла")
            return

        collection = get_collection()

        # Delete old chunks from this file
        old_count = 0
        try:
            old = collection.get(where={"source_file_id": {"$eq": file_id}})
            old_count = len(old["ids"])
            if old_count:
                collection.delete(where={"source_file_id": {"$eq": file_id}})
                logger.info("Удалено старых чанков: %d", old_count)
        except Exception as e:
            logger.warning("Не удалось удалить старые чанки: %s", e)

        # Prepare new chunks
        ids, texts, metadatas = [], [], []
        for i, ch in enumerate(chunks):
            notes = ch.get("notes") or (ch.get("meta") or {}).get("notes", "")
            ids.append(str(ch.get("id") or f"{file_id}_{i}"))
            texts.append(_build_doc(ch))
            metadatas.append({
                "type":            str(ch.get("type", "general")),
                "name":            str(ch.get("name", "")),
                "text":            str(ch.get("text", "")),
                "keywords":        str(ch.get("keywords", "")),
                "notes":           str(notes),
                "source_file_id":  file_id,
                "source_filename": meta["filename"],
            })

        BATCH = 50
        for start in range(0, len(ids), BATCH):
            collection.add(
                ids=ids[start:start + BATCH],
                documents=texts[start:start + BATCH],
                metadatas=metadatas[start:start + BATCH],
            )

        update_task(
            task_id,
            status="done",
            chunks_added=len(ids),
            chunks_deleted=old_count,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("Индексация завершена: +%d чанков, -%d старых", len(ids), old_count)
        await _notify_ai_reload()

    except Exception as e:
        logger.exception("Ошибка индексации: %s", e)
        update_task(task_id, status="error", error=str(e))
