"""Кольцевой буфер записей производительности — хранится в памяти процесса."""
from collections import deque
from threading import Lock

_records: deque = deque(maxlen=500)
_lock = Lock()


def push(record: dict) -> None:
    with _lock:
        _records.appendleft(record)   # новые — первые


def get_records(limit: int = 100) -> list:
    with _lock:
        return list(_records)[:limit]
