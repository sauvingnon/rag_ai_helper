# Входная точка сервиса по перенаправлению запросов на API сторонних моделей.
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.api.endpoints import message_chat
from app.services.llm_service.llm_request import _get_whisper
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from app.logger import logger
from app.config import SENTRY_KEY

# Логи в Sentry
sentry_logging = LoggingIntegration(
    level=None,        # все уровни передаем
    event_level="INFO" # только ошибки будут как события
)

# Подготовка Sentry
sentry_sdk.init(
    dsn=SENTRY_KEY,
    environment="ai_service",
    send_default_pii=False,  # отключаем автоматическую отправку личных данных
    integrations=[sentry_logging]
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Загрузка моделей при старте...")
    _get_whisper()
    import app.services.embeddings_service.db_client  # noqa: F401 — загружает SBERT + CrossEncoder + ChromaDB
    logger.info("Все модели загружены")
    yield

logger.info("Запуск сервиса")

# Создаем приложение
app = FastAPI(debug=True, lifespan=lifespan)

# Подключаем роутеры
app.include_router(message_chat.router)

@app.get("/health")
async def health():
    return {"status": "ok"}

logger.info("Сервис запущен")