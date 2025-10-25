from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from logger import logger
from app.schemas.ai_service import AIRequest
from app.services.ai_service import ai_service
from aiogram.enums import ChatAction

# Телеграмм не даст отправить сообщение длиннее этого....
MAX_LEN = 4000

router = Router()

def split_text(text: str):
    for i in range(0, len(text), MAX_LEN):
        yield text[i:i+MAX_LEN]

# Обработка запроса к модели
@router.message(F.text)
async def input_email(message: Message, state: FSMContext):
    try:

        text_message = message.text.strip()

        ai_request = AIRequest(message=text_message)

        logger.info(f"Пользователь {message.from_user.username} с выбранной моделью сделал запрос: {text_message}")

        msg = await message.answer("⌛ Запрос принят, обработка…")

        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        response = await ai_service.get_answer(ai_request)

        await msg.delete()

        if response is None:
            raise Exception("Пустой ответ ai_service")
        
        if len(response) < MAX_LEN:
            await message.answer(response)
            return
        else:
            await message.answer("⌛ Ответ большой, делим на части…")
        
        for chunk in split_text(response):
            await message.answer(chunk)

        logger.info(f"Пользователь {message.from_user.username} успешно получил ответ.")

    except Exception as e:
        logger.exception(f"Ошибка обработки запроса от пользователя: {e}")
        await message.answer("❌ Произошла ошибка при обработке вашего запроса. Попробуйте снова.")
