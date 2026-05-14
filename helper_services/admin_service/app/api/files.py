from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response

from app.config import ALLOWED_EXTENSIONS
from app.services.s3_manager import S3Manager

router = APIRouter(prefix="/files", tags=["files"])

_s3: S3Manager | None = None


def set_s3(s3: S3Manager) -> None:
    global _s3
    _s3 = s3


def _get_s3() -> S3Manager:
    if _s3 is None:
        raise RuntimeError("S3Manager не инициализирован")
    return _s3


# ── endpoints ──────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    """Загрузить файл в S3. Поддерживаемые форматы: yaml, yml, txt, pdf, docx."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Неподдерживаемый тип: {ext}. Разрешены: {sorted(ALLOWED_EXTENSIONS)}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")

    result = await _get_s3().upload_file(filename=file.filename, data=data)
    if result is None:
        raise HTTPException(status_code=500, detail="Ошибка загрузки в S3")
    return result


@router.get("")
async def list_files():
    """Список всех файлов."""
    return await _get_s3().list_files()


@router.get("/{file_id}")
async def get_file_meta(file_id: str):
    """Метаданные файла."""
    meta = await _get_s3().get_file_meta(file_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return meta


@router.get("/{file_id}/download")
async def download_file(file_id: str):
    """Скачать файл."""
    result = await _get_s3().download_file(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    data, meta = result
    return Response(
        content=data,
        media_type=meta["content_type"],
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'},
    )


@router.get("/{file_id}/view")
async def view_file(file_id: str):
    """Отдать файл inline для просмотра в браузере."""
    result = await _get_s3().download_file(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    data, meta = result
    return Response(
        content=data,
        media_type=meta["content_type"],
        headers={"Content-Disposition": f'inline; filename="{meta["filename"]}"'},
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file(file_id: str):
    """Удалить файл из S3."""
    ok = await _get_s3().delete_file(file_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Файл не найден")
