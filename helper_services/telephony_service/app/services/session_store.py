"""Persistent per-caller conversation sessions stored in SQLite (shared with admin_service)."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("SESSIONS_DB", "/app/dialog_logs/dialogs.db"))
MAX_USER_TURNS = 20


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_sessions_table() -> None:
    with _conn() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id    TEXT PRIMARY KEY,
                name          TEXT NOT NULL DEFAULT '',
                name_received INTEGER NOT NULL DEFAULT 0,
                history       TEXT NOT NULL DEFAULT '[]',
                updated_at    TEXT NOT NULL
            )
        """)


def load_session(session_id: str) -> dict:
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT name, name_received, history FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row:
            history = json.loads(row["history"])
            max_msgs = MAX_USER_TURNS * 2
            if len(history) > max_msgs:
                history = history[-max_msgs:]
            return {
                "history": history,
                "name": row["name"],
                "name_received": bool(row["name_received"]),
            }
    except Exception as e:
        logger.warning("Не удалось загрузить сессию %s: %s", session_id, e)
    return {"history": [], "name": "", "name_received": False}


def save_session(session_id: str, name: str, name_received: bool, history: list) -> None:
    max_msgs = MAX_USER_TURNS * 2
    trimmed = history[-max_msgs:] if len(history) > max_msgs else history
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as con:
            con.execute(
                """
                INSERT INTO sessions (session_id, name, name_received, history, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    name          = excluded.name,
                    name_received = excluded.name_received,
                    history       = excluded.history,
                    updated_at    = excluded.updated_at
                """,
                (session_id, name, int(name_received), json.dumps(trimmed, ensure_ascii=False), now),
            )
    except Exception as e:
        logger.warning("Не удалось сохранить сессию %s: %s", session_id, e)
