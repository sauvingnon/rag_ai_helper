from groq import Groq
from app.config import API_TOKEN
from app.logger import logger
import base64

system_promt = """Ты ассистент университета. Тебе будут высланы куски текста.
У каждого chunk есть краткое описание (description), которое поясняет его суть.
Отвечай только на основе полученных chunks. Отвечай напрямую, как будто знаешь информацию сам. Не используй фразы “в тексте говорится”, “из данных следует”, “Chunk 1 сообщает” и т.п. Если chunks нет, тогда просто скажи - 
"Извини, я не могу ответить на этот запрос." и не выводи никакой иной информации. 
На посторонние темы тебе говорить нельзя. Всегда отвечай на русском."""

# Подключение к стороннему AI-API
client = Groq(
    api_key=API_TOKEN
)

GROQ_PLTF = "groq/compound"

WHISPER = "whisper-large-v3"

TTS_MODEL = "playai-tts"

async def get_audio_response(text: str) -> str:

    model = TTS_MODEL
    response_format = "wav"
    voice = "Fritz-PlayAI"

    response = client.audio.speech.create(
        model=model,
        voice = voice,
        input=text,
        response_format=response_format
    )

    audio_bytes = response.read()

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    return audio_b64

async def ai_voice_reqest(file):

    model = WHISPER

    try:
        logger.info(f"Выполняется запрос к модели {model}")

        transcription = client.audio.transcriptions.create(
            file=file,
            model=model,
            response_format="verbose_json",
            language="ru"
        )

        logger.info(f"Запрос выполнен успешно")

        return transcription.text
    
    except Exception as e:
       logger.exception(f"Ошибка при выполнении запроса: {e}")
       return None
    

# Отправка запроса
async def ai_request(request: str) -> str:

    model = GROQ_PLTF

    try:
        logger.info(f"Выполняется запрос к модели {model}")

        # В начале задаем системный промт, для того, чтобы модель имела контекст.
        chat_completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        system_promt
                    ),
                },
                {
                    "role": "user",
                    "content": request  # это уже реальный вопрос пользователя
                }
            ],
        )

        result = chat_completion.choices[0].message.content

        logger.info(f"Запрос выполнен успешно")

        return result
    
    except Exception as e:
       logger.exception(f"Ошибка при выполнении запроса: {e}")
       return None
    
# Не придумывай информацию и не отвечай на вопросы по другим темам. Старайся инетрпретировать любой вопрос в контексте вопроса об университете.
# Но используй при этом только предоставленные chunks текста. Используй поле description в chunk, чтобы понять о чем фрагмент и нужен ли он нам..
# Если информации нет — отвечай: "Извини, я не могу ответить на этот вопрос." и не выводи никакой иной информации."""