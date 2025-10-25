from aiogram import Router
from aiogram.types import Message, FSInputFile, BufferedInputFile
from logger import logger
from app.services.ai_service import ai_service
from app.utils.convert import convert_with_ffmpeg
import io, base64

router = Router()

@router.message(lambda msg: msg.voice)
async def handle_audio(msg: Message):

    logger.info(f"Пользователь {msg.from_user.username} отправил голосовое сообщение.")

    message_old = await msg.answer("⌛ Запрос принят, обработка…")
    file_obj = msg.voice
    file = await msg.bot.get_file(file_obj.file_id)
    # качаем как байты
    bio = await msg.bot.download_file(file.file_path)
    ogg_bytes = bio.read()

    mp3_bytes = await convert_with_ffmpeg(ogg_bytes)

    if(len(mp3_bytes) == 0):
        raise Exception("Файл пуст")

    # отправляем в микросервис
    result = await ai_service.send_audio(mp3_bytes)

    await message_old.edit_text(f"Вопрос: {result.user_msg}\nОтвет: {result.response}")

    if result.audio_base64:
        audio_bytes = base64.b64decode(result.audio_base64)
        voice = BufferedInputFile(audio_bytes, filename="response.wav")
        await msg.bot.send_voice(msg.chat.id, voice)

    logger.info(f"Пользователь {msg.from_user.username} успешно получил ответ.")