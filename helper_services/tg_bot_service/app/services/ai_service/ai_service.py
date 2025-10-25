# services/ai_service/ai_service.py

from app.services.ai_service.client import client
from typing import Optional
from app.schemas.ai_service import AIRequest, AIAudioResponse
from app.schemas.pyndantic import to_pydantic_model
import aiohttp

entity_schema = "ai_service"

async def get_answer(request: AIRequest) -> Optional[str]:
    """
    Получить ответ на вопрос.
    """
    response = await client.post(
        f"{entity_schema}/chat",
        json=request.dict()   # <-- добавляем query-параметр
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()

async def send_audio(audio_bytes: bytes) -> Optional[AIAudioResponse]:
    """
    Расшифровать голосовое сообщение.
    """
    files = {
            "file": ("voice.wav", audio_bytes, "audio/wav")
        }
    response = await client.post(
        f"{entity_schema}/voice",
        files=files
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    response_data = response.json()
    return to_pydantic_model(AIAudioResponse, response_data)
