import torch
from sentence_transformers import SentenceTransformer, CrossEncoder
from app.config import SBERT_MODEL_PATH, CROSS_ENCODER_MODEL_PATH, USE_CROSS_ENCODER
from app.logger import logger

device = "cuda" if torch.cuda.is_available() else "cpu"
logger.info("Подготовка локальных моделей (device=%s)", device)

sbert_model = SentenceTransformer(SBERT_MODEL_PATH, device=device)

if USE_CROSS_ENCODER:
    cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_PATH, device=device)
    logger.info("Локальные модели готовы (device=%s)", device)
else:
    cross_encoder = None
    logger.info("Локальные модели готовы (device=%s, cross-encoder отключён)", device)
