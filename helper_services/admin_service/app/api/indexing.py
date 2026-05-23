from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.services.indexer import index_file
from app.services.task_store import create_task, get_task, list_tasks

router = APIRouter(tags=["indexing"])

_s3 = None


def set_s3(s3) -> None:
    global _s3
    _s3 = s3


@router.post("/files/{file_id}/index", status_code=202)
async def trigger_index(file_id: str, background_tasks: BackgroundTasks):
    if _s3 is None:
        raise HTTPException(status_code=503, detail="S3 не инициализирован")
    meta = await _s3.get_file_meta(file_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    task_id = create_task(file_id, meta["filename"])
    background_tasks.add_task(index_file, task_id, file_id, _s3)
    return {"task_id": task_id}


@router.post("/files/reindex-all", status_code=202)
async def reindex_all(background_tasks: BackgroundTasks):
    if _s3 is None:
        raise HTTPException(status_code=503, detail="S3 не инициализирован")
    files = await _s3.list_files()
    if not files:
        return {"started": 0}
    for f in files:
        task_id = create_task(f["file_id"], f["filename"])
        background_tasks.add_task(index_file, task_id, f["file_id"], _s3)
    return {"started": len(files)}


@router.get("/tasks")
async def list_all_tasks():
    return list_tasks()


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task
