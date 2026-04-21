# Входная точка сервиса по перенаправлению запросов на API сторонних моделей.
from fastapi import FastAPI
from app.api.endpoints import message_chat
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

logger.info("Запуск сервиса")

# Создаем приложение
app = FastAPI(debug=True)

# Подключаем роутеры
app.include_router(message_chat.router)

logger.info("Сервис запущен")