import io
import json
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from app.api.schemas.model_name import AIRequest
from app.services.core import general_handler, voice_handler, voice_handler_stream
from app.services.llm_service.llm_request import ai_voice_reqest

router = APIRouter(
    prefix="/ai_service",
    tags=["ai_service"],
)

@router.post("/chat")
async def message_req(request: AIRequest):
    return await general_handler(request=request)

@router.post("/voice")
async def voice_req(
    file: UploadFile = File(...),
    history: str = Form(default="[]"),
    user_name: str = Form(default=""),
):
    history_parsed = json.loads(history)
    return await voice_handler(file, history=history_parsed, user_name=user_name)

@router.post("/voice/stream")
async def voice_stream_req(
    file: UploadFile = File(...),
    history: str = Form(default="[]"),
    user_name: str = Form(default=""),
):
    history_parsed = json.loads(history)

    async def generate():
        async for user_msg, sentence in voice_handler_stream(file, history_parsed, user_name):
            yield json.dumps({"user_msg": user_msg, "sentence": sentence}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/transcribe")
async def transcribe_req(file: UploadFile = File(...)):
    """Только STT — без RAG и LLM."""
    audio_bytes = await file.read()
    bio = io.BytesIO(audio_bytes)
    bio.name = "voice.wav"
    text = await ai_voice_reqest(file=bio)
    return {"text": text or ""}
