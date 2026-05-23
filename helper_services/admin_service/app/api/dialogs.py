from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.dialog_store import (
    save_dialog, list_dialogs, get_dialog, delete_dialog, set_status
)

# Вызывается внутренними сервисами (telephony, voice) без аутентификации
internal_router = APIRouter()

# Вызывается из UI — защищён AuthMiddleware через prefix=/admin в main.py
admin_router = APIRouter()


class SaveDialogRequest(BaseModel):
    source: str        # "phone" | "web"
    started_at: str    # ISO-8601
    duration_sec: int
    messages: list     # [{role, content}, ...]


class SetStatusRequest(BaseModel):
    status: str        # "ok" | "disputed"


@internal_router.post("/internal/dialogs", status_code=201)
async def create_dialog(body: SaveDialogRequest):
    return save_dialog(body.source, body.started_at, body.duration_sec, body.messages)


@admin_router.get("/dialogs")
async def get_dialogs(
    source: str = Query(None),
    status: str = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return list_dialogs(source=source, status=status, offset=offset, limit=limit)


@admin_router.get("/dialogs/{dialog_id}")
async def get_one(dialog_id: str):
    d = get_dialog(dialog_id)
    if not d:
        raise HTTPException(404, "Диалог не найден")
    return d


@admin_router.delete("/dialogs/{dialog_id}", status_code=204)
async def delete_one(dialog_id: str):
    if not delete_dialog(dialog_id):
        raise HTTPException(404, "Диалог не найден")


@admin_router.patch("/dialogs/{dialog_id}/status")
async def update_status(dialog_id: str, body: SetStatusRequest):
    if body.status not in ("ok", "disputed"):
        raise HTTPException(400, "Статус должен быть 'ok' или 'disputed'")
    if not set_status(dialog_id, body.status):
        raise HTTPException(404, "Диалог не найден")
    return {"ok": True}
