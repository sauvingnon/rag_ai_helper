import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

# Теперь можешь обращаться к переменным окружения
API_TOKEN = os.getenv("API_TOKEN")
CROSS_ENCODER_MODEL_NAME = os.getenv("CROSS_ENCODER_MODEL")
SBERT_MODEL_NAME = os.getenv("SBERT_MODEL")
RERANK_TOP = int(os.getenv("RERANK_TOP"))
SBERT_MODEL_PATH = os.getenv("SBERT_MODEL_PATH")
CROSS_ENCODER_MODEL_PATH = os.getenv("CROSS_ENCODER_MODEL_PATH")
TOP_K = int(os.getenv("TOP_K"))
SENTRY_KEY = os.getenv("SENTRY_KEY")