from .llm_service.llm_request import ai_request, ai_voice_reqest, get_audio_response
from app.logger import logger
from app.api.schemas.model_name import AIRequest, AIAudioResponse
from .embeddings_service.search_pipeline import search, rerank
from app.utils.preprocess import prepare_query_for_search
from fastapi import APIRouter, UploadFile, File, HTTPException
import io

async def voice_handler(file: UploadFile):
    """
    Принимаем аудио в формате mp3/wav/ogg
    """
    try:

        logger.info("Запущено выполнение запроса на распознавание аудио.")

        # читаем содержимое в память
        audio_bytes = await file.read()

        file = io.BytesIO(audio_bytes)
        file.name = "voice.wav"
        
        user_msg = await ai_voice_reqest(file=file)

        logger.info("Голосовое сообщение успешно обработано.")

        clear_msg = prepare_query_for_search(user_msg)

        chunks = search(query=clear_msg)

        if not chunks:
            response = "Извини, я не могу ответить на этот запрос."
            logger.info(f"Ответ не был сформирован, так как chunks нет.")
            return response

        logger.info(f"Количество полученных чанков: {len(chunks)}")

        top_chunks = rerank(clear_msg, chunks)

        logger.info(f"Реранк отсорировал самые релевантные: {len(top_chunks)}")

        promt = await build_llm_prompt(user_msg, top_chunks)

        logger.info(f"Итоговый промт: {promt}")

        response = await ai_request(promt)

        logger.info(f"Ответ: {response}\nПодготовка голосового ответа")

        # audio_response = await get_audio_response(response)

        result = AIAudioResponse(user_msg=user_msg, response=response)

        logger.info(f"Запрос на распознавание выполнен")

        return result    

    except Exception as e:
        logger.exception(f"Ошибка: {e}")

# Главный обработчик - связывает эмб модель и ллм модель
async def general_handler(request: AIRequest) -> str:

    try:

        logger.info(f"Запущено выполнение запроса: {request.message}")

        clear_message = prepare_query_for_search(request.message)

        chunks = search(query=clear_message)

        if not chunks:
            response = "Извини, я не могу ответить на этот запрос."
            logger.info(f"Ответ не был сформирован, так как chunks нет.")
            return response
        
        logger.info(f"Количество полученных чанков: {len(chunks)}")

        top_chunks = rerank(clear_message, chunks)

        logger.info(f"Реранк отсорировал самые релевантные: {len(top_chunks)}")

        promt = await build_llm_prompt(request.message, top_chunks)

        logger.info(f"Итоговый промт: {promt}")

        response = await ai_request(promt)

        logger.info(f"Ответ: {response}")

        return response
    
    except Exception as e:
        logger.exception(f"Ошибка в /start: {e}")

async def build_llm_prompt(user_question, chunks):
    prompt = ""
    for i, chunk in enumerate(chunks, 1):
        document = chunk.get("document")
        notes = chunk.get("notes")
        type = chunk.get("type")
        
        prompt += f"Chunk {i}:\n"
        prompt += f"Text: {document}\n\n"
        if notes:
            prompt += f"Дополнительные данные: {notes}\n\n"
        
    prompt += f"Вопрос пользователя: {user_question}\n"
    prompt += (
        "Используя только приведённые выше chunks, сформулируй полный и точный ответ без указаний твоего хода размышления, выводов. Ты справочная система."
    )
    return prompt


