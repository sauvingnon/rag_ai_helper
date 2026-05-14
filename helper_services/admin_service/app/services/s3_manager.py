import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import aiobotocore.session
from botocore.config import Config
from botocore.exceptions import ClientError

from app.logger import logger

_CONTENT_TYPES: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt":  "text/plain",
    ".yaml": "text/yaml",
    ".yml":  "text/yaml",
}


class S3Manager:
    """Async CRUD layer for document storage in Garage/S3.

    Key layout:  files/{uuid4}/{url-encoded-filename}
    """

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket_name: str):
        self.endpoint_url = endpoint_url
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self._client = None
        self._context = None
        self._is_connected = False
        self._lock = asyncio.Lock()

    # ── connection ─────────────────────────────────────────────────────────────

    async def connect(self, max_retries: int = 5, retry_delay: int = 5) -> bool:
        delay = retry_delay
        for attempt in range(max_retries):
            try:
                logger.info("Подключение к S3 (попытка %d/%d)…", attempt + 1, max_retries)
                session = aiobotocore.session.get_session()
                self._context = session.create_client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name="us-east-1",
                    use_ssl=False,
                    verify=False,
                    config=Config(
                        s3={"addressing_style": "path"},
                        retries={"max_attempts": 3, "mode": "standard"},
                        signature_version="s3v4",
                    ),
                )
                self._client = await self._context.__aenter__()
                await self._client.head_bucket(Bucket=self.bucket_name)
                self._is_connected = True
                logger.info("S3 подключён (bucket: %s)", self.bucket_name)
                return True
            except Exception as e:
                logger.error("Ошибка подключения к S3: %s", e)
                await self._close_context()
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
        logger.error("Не удалось подключиться к S3 после %d попыток", max_retries)
        return False

    async def disconnect(self) -> None:
        await self._close_context()
        logger.info("S3 соединение закрыто")

    async def _close_context(self) -> None:
        if self._context:
            try:
                await self._context.__aexit__(None, None, None)
            except Exception:
                pass
        self._client = None
        self._context = None
        self._is_connected = False

    async def _ensure(self) -> bool:
        async with self._lock:
            if self._client and self._is_connected:
                return True
            logger.warning("S3 соединение потеряно, переподключаемся…")
            await self._close_context()
            return await self.connect(max_retries=3, retry_delay=2)

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _content_type(filename: str) -> str:
        return _CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")

    @staticmethod
    def _make_key(file_id: str, filename: str) -> str:
        return f"files/{file_id}/{quote(filename, safe='')}"

    @staticmethod
    def _parse_key(key: str) -> tuple[str, str]:
        """(file_id, filename) из ключа вида files/{id}/{name}."""
        parts = key.split("/", 2)
        if len(parts) != 3:
            return "", ""
        return parts[1], unquote(parts[2])

    def _obj_to_meta(self, obj: dict) -> Optional[dict]:
        key = obj.get("Key", "")
        if key.endswith("/"):
            return None
        file_id, filename = self._parse_key(key)
        if not file_id or not filename:
            return None
        return {
            "file_id":      file_id,
            "filename":     filename,
            "key":          key,
            "size_bytes":   obj["Size"],
            "uploaded_at":  obj["LastModified"].isoformat(),
            "content_type": self._content_type(filename),
        }

    # ── public CRUD ────────────────────────────────────────────────────────────

    async def upload_file(self, filename: str, data: bytes) -> Optional[dict]:
        """Загрузить файл. Возвращает метаданные или None при ошибке."""
        if not data:
            logger.warning("upload_file: пустые данные для %s", filename)
            return None
        if not await self._ensure():
            return None

        file_id = str(uuid.uuid4())
        key = self._make_key(file_id, filename)
        content_type = self._content_type(filename)
        uploaded_at = datetime.now(timezone.utc).isoformat()

        try:
            await self._client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            logger.info("Загружен файл: %s (%d байт)", key, len(data))
            return {
                "file_id":      file_id,
                "filename":     filename,
                "key":          key,
                "size_bytes":   len(data),
                "uploaded_at":  uploaded_at,
                "content_type": content_type,
            }
        except Exception as e:
            logger.exception("Ошибка загрузки %s: %s", filename, e)
            return None

    async def list_files(self) -> list[dict]:
        """Список файлов. O(страниц) запросов — без head_object."""
        if not await self._ensure():
            return []
        items: list[dict] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket_name, Prefix="files/"):
                for obj in page.get("Contents", []):
                    row = self._obj_to_meta(obj)
                    if row:
                        items.append(row)
        except Exception as e:
            logger.exception("Ошибка list_files: %s", e)
        return items

    async def get_file_meta(self, file_id: str) -> Optional[dict]:
        """Метаданные файла. O(1) запрос через prefix listing."""
        if not await self._ensure():
            return None
        try:
            resp = await self._client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=f"files/{file_id}/",
                MaxKeys=1,
            )
            objs = [o for o in resp.get("Contents", []) if not o["Key"].endswith("/")]
            if not objs:
                return None
            return self._obj_to_meta(objs[0])
        except Exception as e:
            logger.exception("Ошибка get_file_meta(%s): %s", file_id, e)
            return None

    async def download_file(self, file_id: str) -> Optional[tuple[bytes, dict]]:
        """Скачать файл по ID. Возвращает (данные, метаданные) или None."""
        meta = await self.get_file_meta(file_id)
        if meta is None:
            return None
        if not await self._ensure():
            return None
        try:
            resp = await self._client.get_object(Bucket=self.bucket_name, Key=meta["key"])
            data = await resp["Body"].read()
            return data, meta
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            logger.exception("Ошибка download_file(%s): %s", file_id, e)
            return None
        except Exception as e:
            logger.exception("Ошибка download_file(%s): %s", file_id, e)
            return None

    async def delete_file(self, file_id: str) -> bool:
        """Удалить файл по ID. Возвращает False если не найден или ошибка."""
        meta = await self.get_file_meta(file_id)
        if meta is None:
            return False
        if not await self._ensure():
            return False
        try:
            await self._client.delete_object(Bucket=self.bucket_name, Key=meta["key"])
            logger.info("Удалён файл: %s", meta["key"])
            return True
        except Exception as e:
            logger.exception("Ошибка delete_file(%s): %s", file_id, e)
            return False
