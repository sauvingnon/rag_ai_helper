from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET
from app.services.s3_manager import S3Manager
from app.api.files import router as files_router, set_s3 as files_set_s3
from app.api.chunks import router as chunks_router
from app.api.indexing import router as indexing_router, set_s3 as indexing_set_s3
from app.api.auth import router as auth_router, verify_token, COOKIE_NAME
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
    files_set_s3(s3)
    indexing_set_s3(s3)
    await s3.connect()
    yield
    await s3.disconnect()


app = FastAPI(title="RAG Admin Service", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(files_router, prefix="/admin")
app.include_router(chunks_router, prefix="/admin")
app.include_router(indexing_router, prefix="/admin")


@app.get("/health")
async def health():
    return {"status": "ok"}


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="spa")
