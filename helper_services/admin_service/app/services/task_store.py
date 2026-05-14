import uuid
from datetime import datetime, timezone
from typing import Optional

_tasks: dict[str, dict] = {}


def create_task(file_id: str, filename: str) -> str:
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "task_id": task_id,
        "file_id": file_id,
        "filename": filename,
        "status": "pending",
        "chunks_added": 0,
        "chunks_deleted": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    return task_id


def update_task(task_id: str, **kwargs) -> None:
    if task_id in _tasks:
        _tasks[task_id].update(kwargs)


def get_task(task_id: str) -> Optional[dict]:
    return _tasks.get(task_id)


def list_tasks() -> list[dict]:
    return sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)
