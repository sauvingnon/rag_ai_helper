import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

CROSS_ENCODER_MODEL_NAME = os.getenv("CROSS_ENCODER_MODEL")
SBERT_MODEL_NAME = os.getenv("SBERT_MODEL")
RERANK_TOP = int(os.getenv("RERANK_TOP"))
SBERT_MODEL_PATH = os.getenv("SBERT_MODEL_PATH")
CROSS_ENCODER_MODEL_PATH = os.getenv("CROSS_ENCODER_MODEL_PATH")
TOP_K = int(os.getenv("TOP_K"))

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-placeholder")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "-2.0"))
USE_CROSS_ENCODER = os.getenv("USE_CROSS_ENCODER", "true").lower() not in ("false", "0", "no")