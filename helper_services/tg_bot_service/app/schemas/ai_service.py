from typing import Optional
from pydantic import BaseModel

class AIRequest(BaseModel):
    message: str

class AIAudioResponse(BaseModel):
    user_msg: str
    response: str
    audio_base64: Optional[str] = None