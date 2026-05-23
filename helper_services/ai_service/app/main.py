from contextlib import asynccontextmanager
from typing import List
import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from app.api.endpoints import message_chat, eval_endpoint
from app.services.llm_service.llm_request import _get_whisper
from app.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Загрузка моделей при старте...")
    _get_whisper()
    import app.services.embeddings_service.db_client  # noqa: F401 — загружает SBERT + CrossEncoder + ChromaDB
    logger.info("Все модели загружены")
    yield
    # Явно освобождаем CUDA-память — иначе ctranslate2/PyTorch виснут при остановке
    logger.info("Завершение: освобождаем GPU-память...")
    import app.services.llm_service.llm_request as llm_mod
    import app.services.embeddings_service.models as emb_mod
    import torch
    llm_mod._whisper = None
    emb_mod.sbert_model = None
    emb_mod.cross_encoder = None
    torch.cuda.empty_cache()
    logger.info("GPU-память освобождена")

logger.info("Запуск сервиса")

# Создаем приложение
app = FastAPI(debug=True, lifespan=lifespan)

# Подключаем роутеры
app.include_router(message_chat.router)
app.include_router(eval_endpoint.router)

@app.get("/health")
async def health():
    return {"status": "ok"}


class EmbedRequest(BaseModel):
    texts: List[str]


@app.get("/ai_service/perf-logs")
async def perf_logs(limit: int = 100):
    from app.services.perf_store import get_records
    return get_records(limit=min(limit, 500))


@app.post("/ai_service/embed")
async def embed_texts(body: EmbedRequest):
    import app.services.embeddings_service.models as emb_mod
    loop = asyncio.get_event_loop()
    embeddings = await loop.run_in_executor(
        None, lambda: emb_mod.sbert_model.encode(body.texts).tolist()
    )
    return {"embeddings": embeddings}


@app.post("/reload-db")
async def reload_db():
    from app.services.embeddings_service.db_client import reload_collection
    count = reload_collection()
    return {"ok": True, "documents": count}

logger.info("Сервис запущен")