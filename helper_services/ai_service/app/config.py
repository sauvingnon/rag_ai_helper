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
SENTRY_KEY = os.getenv("SENTRY_KEY")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
RERANK_THRESHOLD = float(os.getenv("RERANK_THRESHOLD", "-2.0"))