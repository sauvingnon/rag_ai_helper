import json
import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path("/app/dialog_logs/dialogs.db")

_NO_ANSWER = [
    "только по вопросам университета",
    "помочь только по вопросам",
    "не смогла найти",
    "не нашла информацию",
    "нет информации",
    "информация не найдена",
    "не могу помочь с этим",
]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS dialogs (
                id           TEXT PRIMARY KEY,
                source       TEXT NOT NULL,
                started_at   TEXT NOT NULL,
                duration_sec INTEGER NOT NULL,
                messages     TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'ok'
            )
        """)


def _detect_status(messages: list) -> str:
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", "").lower()
            if any(m in content for m in _NO_ANSWER):
                return "disputed"
    return "ok"


def _row_to_dict(r) -> dict:
    return {
        "id": r["id"],
        "source": r["source"],
        "started_at": r["started_at"],
        "duration_sec": r["duration_sec"],
        "messages": json.loads(r["messages"]),
        "status": r["status"],
    }


def save_dialog(source: str, started_at: str, duration_sec: int, messages: list) -> dict:
    dialog_id = str(uuid.uuid4())
    status = _detect_status(messages)
    with _conn() as con:
        con.execute(
            "INSERT INTO dialogs (id, source, started_at, duration_sec, messages, status) VALUES (?,?,?,?,?,?)",
            (dialog_id, source, started_at, duration_sec, json.dumps(messages, ensure_ascii=False), status),
        )
    return {"id": dialog_id, "status": status}


def list_dialogs(source=None, status=None, offset=0, limit=50) -> dict:
    clauses, params = [], []
    if source:
        clauses.append("source = ?"); params.append(source)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as con:
        total = con.execute(f"SELECT COUNT(*) FROM dialogs {where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM dialogs {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return {"total": total, "items": [_row_to_dict(r) for r in rows]}


def get_dialog(dialog_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM dialogs WHERE id = ?", (dialog_id,)).fetchone()
    return _row_to_dict(r) if r else None


def delete_dialog(dialog_id: str) -> bool:
    with _conn() as con:
        return con.execute("DELETE FROM dialogs WHERE id = ?", (dialog_id,)).rowcount > 0


def set_status(dialog_id: str, status: str) -> bool:
    with _conn() as con:
        return con.execute("UPDATE dialogs SET status = ? WHERE id = ?", (status, dialog_id)).rowcount > 0
