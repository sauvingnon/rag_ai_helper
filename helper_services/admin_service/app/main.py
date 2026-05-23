from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

_TELEPHONY_SESSIONS_DIR = Path("/app/telephony_sessions")

import httpx
from app.config import S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, AI_SERVICE_URL
from app.logger import logger
from app.services.s3_manager import S3Manager
from app.api.files import router as files_router, set_s3 as files_set_s3
from app.api.chunks import router as chunks_router
from app.api.indexing import router as indexing_router, set_s3 as indexing_set_s3
from app.api.auth import router as auth_router, verify_token, COOKIE_NAME
from app.api.dialogs import internal_router as dialogs_internal_router, admin_router as dialogs_admin_router
from app.services.dialog_store import init_db
from app.logger import logger

s3 = S3Manager(
    endpoint_url=S3_ENDPOINT,
    access_key=S3_ACCESS_KEY,
    secret_key=S3_SECRET_KEY,
    bucket_name=S3_BUCKET,
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/admin"):
            token = request.cookies.get(COOKIE_NAME)
            if not token or not verify_token(token):
                return JSONResponse({"detail": "Не авторизован"}, status_code=401)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    files_set_s3(s3)
    indexing_set_s3(s3)
    await s3.connect()
    yield
    await s3.disconnect()


app = FastAPI(title="RAG Admin Service", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(dialogs_internal_router)              # /internal/dialogs — без авторизации
app.include_router(dialogs_admin_router, prefix="/admin")  # /admin/dialogs — защищён middleware
app.include_router(files_router, prefix="/admin")
app.include_router(chunks_router, prefix="/admin")
app.include_router(indexing_router, prefix="/admin")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/perf-logs")
async def perf_logs(limit: int = 100):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{AI_SERVICE_URL}/ai_service/perf-logs", params={"limit": limit})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.post("/admin/ai/reload-db")
async def reload_ai_db():
    """Перезагружает коллекцию ChromaDB в ai_service."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{AI_SERVICE_URL}/reload-db")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/admin/sessions/stats")
async def sessions_stats():
    """Количество файлов сессий телефонии."""
    if not _TELEPHONY_SESSIONS_DIR.exists():
        return {"count": 0}
    files = list(_TELEPHONY_SESSIONS_DIR.glob("*.json"))
    return {"count": len(files)}


@app.delete("/admin/sessions/all", status_code=200)
async def clear_all_sessions():
    """Удалить все файлы сессий телефонии (история диалогов)."""
    if not _TELEPHONY_SESSIONS_DIR.exists():
        return {"deleted": 0}
    files = list(_TELEPHONY_SESSIONS_DIR.glob("*.json"))
    for f in files:
        f.unlink(missing_ok=True)
    logger.info("Удалено сессий телефонии: %d", len(files))
    return {"deleted": len(files)}


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="spa")
