import json
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from num2words import num2words
from pydantic import BaseModel

from app.services.tts import load_model, synthesize


def _normalize_for_tts(text: str) -> str:
    """Конвертирует цифры в русские слова чтобы Silero не пропускал их."""
    def _replace(m: re.Match) -> str:
        try:
            num_str = re.sub(r"[\s ]", "", m.group())
            return num2words(int(num_str), lang="ru")
        except Exception:
            return m.group()
    return re.sub(r"\b\d{1,3}(?:[\s ]\d{3})+\b|\b\d+\b", _replace, text)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AI_SERVICE_URL    = os.getenv("AI_SERVICE_URL",    "http://ai_service:8005")
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://admin_service:8020")
STATIC_DIR = Path(__file__).parent / "static"


async def _save_dialog(started_at: str, duration_sec: int, messages: list) -> None:
    if not messages:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{ADMIN_SERVICE_URL}/internal/dialogs",
                json={
                    "source": "web",
                    "started_at": started_at,
                    "duration_sec": duration_sec,
                    "messages": messages,
                },
            )
    except Exception as e:
        logger.warning("Не удалось сохранить лог диалога: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    message: str
    history: list = []


@app.get("/")
async def index():
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"{AI_SERVICE_URL}/ai_service/chat",
                json={"message": req.message, "history": req.history},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e))
    text = resp.json()
    return {"response": text if isinstance(text, str) else str(text)}


@app.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    async def proxy():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{AI_SERVICE_URL}/ai_service/chat/stream",
                json={"message": req.message, "history": req.history},
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(proxy(), media_type="application/x-ndjson")


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")
    history: list = []
    dialog_messages: list = []
    started_at = datetime.now(timezone.utc).isoformat()
    t_start = datetime.now(timezone.utc).timestamp()
    try:
        while True:
            # Клиент сначала шлёт JSON с историей, затем бинарные данные аудио
            msg = await websocket.receive()
            if "text" in msg:
                try:
                    history = json.loads(msg["text"]).get("history", history)
                except Exception:
                    pass
                msg = await websocket.receive()

            if "bytes" not in msg:
                continue
            audio_bytes = msg["bytes"]
            logger.info("Received audio: %d bytes", len(audio_bytes))

            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(tmp_path, "rb") as f:
                        resp = await client.post(
                            f"{AI_SERVICE_URL}/ai_service/voice",
                            files={"file": ("audio.webm", f, "audio/webm")},
                            data={"history": json.dumps(history)},
                        )
                    resp.raise_for_status()
                    data = resp.json()

                user_msg = data.get("user_msg", "")
                answer = data.get("response", "")
                logger.info("STT: %s | Answer: %s", user_msg, answer[:80])

                if user_msg:
                    dialog_messages.append({"role": "user",      "content": user_msg})
                if answer:
                    dialog_messages.append({"role": "assistant", "content": answer})

                await websocket.send_text(json.dumps({
                    "user_msg": user_msg,
                    "response": answer,
                }))

                if answer:
                    wav = synthesize(_normalize_for_tts(answer))
                    await websocket.send_bytes(wav)

            except httpx.HTTPError as e:
                logger.error("ai_service error: %s", e)
                await websocket.send_text(json.dumps({"error": str(e)}))
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        duration_sec = int(datetime.now(timezone.utc).timestamp() - t_start)
        await _save_dialog(started_at, duration_sec, dialog_messages)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8010, reload=False)
