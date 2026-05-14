import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.services.tts import load_model, synthesize

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai_service:8005")
STATIC_DIR = Path(__file__).parent / "static"


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


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")
    history: list = []
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

                await websocket.send_text(json.dumps({
                    "user_msg": user_msg,
                    "response": answer,
                }))

                if answer:
                    wav = synthesize(answer)
                    await websocket.send_bytes(wav)

            except httpx.HTTPError as e:
                logger.error("ai_service error: %s", e)
                await websocket.send_text(json.dumps({"error": str(e)}))
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8010, reload=False)
