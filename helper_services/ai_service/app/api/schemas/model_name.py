from enum import Enum
from typing import Optional
from pydantic import BaseModel

# Схема запроса
class AIRequest(BaseModel):
    message: str
    history: list = []

class AIAudioResponse(BaseModel):
    user_msg: str
    response: str
    audio_base64: Optional[str] = None
