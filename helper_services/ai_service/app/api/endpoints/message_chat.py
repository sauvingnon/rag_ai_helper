from fastapi import APIRouter, UploadFile, File
from app.api.schemas.model_name import AIRequest
from app.services.core import general_handler, voice_handler

router = APIRouter(
    prefix="/ai_service",
    tags=["ai_service"],
)

# Прием запросов
@router.post("/chat")
async def message_req(request: AIRequest):
    return await general_handler(request=request)

# Прием запросов
@router.post("/voice")
async def voice_req(file: UploadFile = File(...)):
    return await voice_handler(file)
