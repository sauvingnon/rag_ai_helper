from sentence_transformers import SentenceTransformer, CrossEncoder
from app.config import SBERT_MODEL_PATH, CROSS_ENCODER_MODEL_PATH
from app.logger import logger

logger.info("Подготовка локальных моделей")

# Инициализация моделей

sbert_model = SentenceTransformer(SBERT_MODEL_PATH)
cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_PATH)

logger.info("Локальные модели готовы")
