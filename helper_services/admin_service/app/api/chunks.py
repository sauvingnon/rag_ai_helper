import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.chroma_client import get_collection

router = APIRouter(prefix="/chunks", tags=["chunks"])


class ChunkCreate(BaseModel):
    name: str
    text: str
    keywords: str = ""
    type: str = "general"
    notes: str = ""
    source_file_id: str = ""


class ChunkUpdate(BaseModel):
    name: str | None = None
    text: str | None = None
    keywords: str | None = None
    type: str | None = None
    notes: str | None = None


def _build_doc(meta: dict) -> str:
    parts = [
        meta.get("name", ""),
        f"Описание: {meta['text']}" if meta.get("text") else "",
        f"Ключевые слова: {meta['keywords']}" if meta.get("keywords") else "",
        f"Примечания: {meta['notes']}" if meta.get("notes") else "",
    ]
    return "\n".join(p for p in parts if p)


@router.get("/stats")
async def chunk_stats():
    """Количество чанков по каждому file_id. Используется для отображения статуса индексации."""
    collection = get_collection()
    try:
        result = collection.get(include=["metadatas"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    counts: dict[str, int] = {}
    for meta in (result["metadatas"] or []):
        fid = meta.get("source_file_id", "")
        if fid:
            counts[fid] = counts.get(fid, 0) + 1
    return counts


@router.post("", status_code=201)
async def create_chunk(body: ChunkCreate):
    collection = get_collection()
    chunk_id = str(_uuid.uuid4())
    meta = {
        "name": body.name,
        "text": body.text,
        "keywords": body.keywords,
        "type": body.type,
        "notes": body.notes,
        "source_file_id": body.source_file_id,
        "source_filename": "",
    }
    doc = _build_doc(meta)
    collection.add(ids=[chunk_id], documents=[doc], metadatas=[meta])
    return {"id": chunk_id, "document": doc, **meta}


@router.get("")
async def list_chunks(
    source_file_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    collection = get_collection()
    where = {"source_file_id": {"$eq": source_file_id}} if source_file_id else None
    try:
        result = collection.get(
            where=where,
            limit=limit,
            offset=offset,
            include=["metadatas", "documents"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    items = [
        {
            "id": cid,
            "document": (result["documents"] or [""] * len(result["ids"]))[i],
            **(result["metadatas"] or [{}] * len(result["ids"]))[i],
        }
        for i, cid in enumerate(result["ids"])
    ]

    try:
        if where:
            total_res = collection.get(where=where)
            total = len(total_res["ids"])
        else:
            total = collection.count()
    except Exception:
        total = len(items)

    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/{chunk_id}")
async def get_chunk(chunk_id: str):
    collection = get_collection()
    result = collection.get(ids=[chunk_id], include=["metadatas", "documents"])
    if not result["ids"]:
        raise HTTPException(status_code=404, detail="Чанк не найден")
    return {"id": chunk_id, "document": result["documents"][0], **result["metadatas"][0]}


@router.put("/{chunk_id}")
async def update_chunk(chunk_id: str, body: ChunkUpdate):
    collection = get_collection()
    existing = collection.get(ids=[chunk_id], include=["metadatas"])
    if not existing["ids"]:
        raise HTTPException(status_code=404, detail="Чанк не найден")

    meta = {**existing["metadatas"][0], **body.model_dump(exclude_none=True)}
    new_doc = _build_doc(meta)
    collection.update(ids=[chunk_id], documents=[new_doc], metadatas=[meta])
    return {"id": chunk_id, "document": new_doc, **meta}


@router.delete("/{chunk_id}", status_code=204)
async def delete_chunk(chunk_id: str):
    collection = get_collection()
    if not collection.get(ids=[chunk_id])["ids"]:
        raise HTTPException(status_code=404, detail="Чанк не найден")
    collection.delete(ids=[chunk_id])
