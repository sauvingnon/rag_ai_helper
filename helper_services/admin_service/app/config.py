import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

S3_ENDPOINT   = os.getenv("S3_ENDPOINT",  "http://garage:3900")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_BUCKET     = os.getenv("S3_BUCKET",    "rag-files")

CHROMA_PATH      = os.getenv("CHROMA_PATH",      "/app/chroma_db")
SBERT_MODEL_PATH = os.getenv("SBERT_MODEL_PATH", "/app/models/sbert_model")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL    = os.getenv("LLM_MODEL",    "deepseek-chat")
LLM_API_KEY  = os.getenv("LLM_API_KEY",  "")

ADMIN_LOGIN      = os.getenv("ADMIN_LOGIN",    "admin")
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "changeme")
JWT_SECRET       = os.getenv("JWT_SECRET",     "change-this-secret")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

ALLOWED_EXTENSIONS = {".yaml", ".yml", ".txt", ".pdf", ".docx"}
