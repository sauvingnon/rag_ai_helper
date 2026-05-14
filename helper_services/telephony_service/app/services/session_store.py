"""Persistent per-caller conversation sessions stored as JSON files."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/app/sessions"))
MAX_USER_TURNS = 20  # сколько реплик пользователя хранить (каждая = 2 сообщения)


def _path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c == "-")[:64]
    return SESSIONS_DIR / f"{safe}.json"


def load_session(session_id: str) -> dict:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(session_id)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            history = data.get("history", [])
            # Оставляем последние MAX_USER_TURNS пар
            max_msgs = MAX_USER_TURNS * 2
            if len(history) > max_msgs:
                history = history[-max_msgs:]
            return {
                "history": history,
                "name": data.get("name", ""),
                "name_received": data.get("name_received", False),
            }
        except Exception as e:
            logger.warning("Не удалось загрузить сессию %s: %s", session_id, e)
    return {"history": [], "name": "", "name_received": False}


def save_session(session_id: str, name: str, name_received: bool, history: list) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    max_msgs = MAX_USER_TURNS * 2
    trimmed = history[-max_msgs:] if len(history) > max_msgs else history
    try:
        with open(_path(session_id), "w", encoding="utf-8") as f:
            json.dump(
                {"name": name, "name_received": name_received, "history": trimmed},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.warning("Не удалось сохранить сессию %s: %s", session_id, e)
