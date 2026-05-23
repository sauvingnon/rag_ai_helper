from .llm_service.llm_request import ai_agent_stream, ai_voice_reqest
from app.logger import logger
from app.api.schemas.model_name import AIRequest, AIAudioResponse
from fastapi import UploadFile
import io


async def voice_handler(file: UploadFile, history: list = None, user_name: str = ""):
    try:
        logger.info("Запущено выполнение запроса на распознавание аудио.")

        audio_bytes = await file.read()
        bio = io.BytesIO(audio_bytes)
        bio.name = "voice.wav"

        t_stt0 = __import__("time").monotonic()
        user_msg = await ai_voice_reqest(file=bio)
        stt_sec = __import__("time").monotonic() - t_stt0

        if not user_msg or not user_msg.strip():
            logger.info("STT вернул пустой текст — пропускаем")
            return AIAudioResponse(user_msg="", response="")

        logger.info("Голосовое сообщение: %s", user_msg[:80])

        sentences = []
        async for sentence in ai_agent_stream(user_msg, history=history or [], user_name=user_name, stt_sec=stt_sec):
            sentences.append(sentence)

        response = " ".join(sentences)
        logger.info("Ответ: %s", response[:120])
        return AIAudioResponse(user_msg=user_msg, response=response)

    except Exception as e:
        logger.exception("Ошибка voice_handler: %s", e)


async def general_handler(request: AIRequest) -> str:
    try:
        logger.info("Запрос: %s", request.message[:80])

        sentences = []
        async for sentence in ai_agent_stream(request.message, history=request.history):
            sentences.append(sentence)

        response = " ".join(sentences)
        logger.info("Ответ: %s", response[:120])
        return response

    except Exception as e:
        logger.exception("Ошибка general_handler: %s", e)
        return "Извини, произошла ошибка."


async def voice_handler_stream(file: UploadFile, history: list = None, user_name: str = ""):
    """Async-генератор: (user_msg, sentence). Предложения отдаются по мере генерации LLM."""
    audio_bytes = await file.read()
    bio = io.BytesIO(audio_bytes)
    bio.name = "voice.wav"

    t_stt0 = __import__("time").monotonic()
    user_msg = await ai_voice_reqest(file=bio)
    stt_sec = __import__("time").monotonic() - t_stt0
    if not user_msg or not user_msg.strip():
        return

    logger.info("STT: %s", user_msg[:80])

    first = True
    async for sentence in ai_agent_stream(user_msg, history=history or [], user_name=user_name, stt_sec=stt_sec):
        yield (user_msg if first else ""), sentence
        first = False
