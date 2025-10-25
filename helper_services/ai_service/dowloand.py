# Скачивание моделей 
from sentence_transformers import SentenceTransformer, CrossEncoder
import os
from app.config import SBERT_MODEL_NAME, CROSS_ENCODER_MODEL_NAME

# папка для локального хранения
script_dir = os.path.dirname(os.path.abspath(__file__))

# SBERT-модель
sbert_model = SentenceTransformer(SBERT_MODEL_NAME)
sbert_model.save(f"{script_dir}/models/sbert_model")

# CrossEncoder-модель
cross_model = CrossEncoder(CROSS_ENCODER_MODEL_NAME)
cross_model.save(f"{script_dir}/models/cross_encoder_model")

print("✅ Модели сохранены локально!")
