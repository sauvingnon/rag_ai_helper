import asyncio
import tempfile
import os
import re
import json
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI
from faster_whisper import WhisperModel
from app.config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, WHISPER_MODEL
from app.logger import logger

# ─── Агент ───────────────────────────────────────────────────────────────────

AGENT_SYSTEM = """ВАЖНО: Отвечай ТОЛЬКО на русском языке. Никогда не используй другие языки.

Ты голосовой ассистент справочной службы университета. Общаешься по телефону.

У тебя два инструмента:

1. search_knowledge_base — ищет информацию в базе знаний. Вызывай при любом конкретном вопросе об университете: факультеты, специальности, приёмная комиссия, расписание, контакты, стоимость обучения, общежитие, преподаватели, корпуса и т.д. Можно вызвать повторно с уточнённым запросом если первый результат недостаточен (максимум 2 раза за ход).

2. ask_clarification — задаёт уточняющий вопрос пользователю. Используй ТОЛЬКО если запрос совершенно неразборчив или настолько общий, что невозможно понять что искать (например: "расскажи про всё", "что у вас есть", несвязная речь). Если вопрос хоть как-то понятен — сразу ищи, не уточняй.

ЗАПРЕЩЕНО:
- упоминать названия инструментов или функций в ответе пользователю
- обещать перезвонить, отправить информацию позже, передать заявку
- придумывать факты об университете из головы
- говорить "уточню", "проверю", "найду" — либо ищи прямо сейчас, либо скажи что не знаешь

Отвечай кратко, 1-2 предложения. Это телефонный разговор. Язык: только русский."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": (
                "Задать уточняющий вопрос пользователю. "
                "Использовать ТОЛЬКО если запрос совершенно непонятен и поиск заведомо не поможет. "
                "Если запрос хоть как-то понятен — вместо этого вызывать search_knowledge_base."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Короткий уточняющий вопрос (одно предложение)"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Поиск информации в базе знаний университета. "
                "Вызывать при любом конкретном вопросе об университете. "
                "Можно вызвать повторно с уточнённым запросом если первый результат неполный (макс. 2 раза)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос — что именно нужно найти"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

_SENT_END = re.compile(r'(?<=[.!?…])\s')

_FORCE_SEARCH_MARKERS = [
    "search_knowledge_base",
    "ask_clarification",
    "минуточку, ищу",
    "почти нашла",
    "перезвон",
    "позвоню",
    "свяжусь",
    "найду информацию",
    "уточню информацию",
    "обращусь",
    "передам",
    "проверю",
    "посмотрю",
    "позвольте я",
    "дайте мне",
    "сейчас узнаю",
    "сейчас проверю",
    "сейчас посмотрю",
]

MAX_SEARCHES = 2

client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def _split_sentences(text: str) -> list[str]:
    parts = _SENT_END.split(text)
    return [p.strip() for p in parts if p.strip()]


async def _stream_sentences(stream) -> AsyncGenerator[str, None]:
    buffer = ""
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if not delta:
            continue
        buffer += delta
        while True:
            m = _SENT_END.search(buffer)
            if m:
                sentence = buffer[: m.start() + 1].strip()
                buffer = buffer[m.end():]
                if sentence:
                    yield sentence
            elif len(buffer) > 200:
                split = buffer.rfind(" ", 0, 200)
                if split > 0:
                    yield buffer[:split].strip()
                    buffer = buffer[split + 1:]
                else:
                    break
            else:
                break
    if buffer.strip():
        yield buffer.strip()


def _execute_search(query: str) -> str:
    from app.services.embeddings_service.search_pipeline import search, rerank  # noqa: PLC0415
    t0 = time.monotonic()
    chunks = search(query=query)
    t1 = time.monotonic()
    if not chunks:
        logger.info("[search] %.2f с — ничего не найдено", t1 - t0)
        return "Информация по запросу не найдена."
    top = rerank(query, chunks)
    t2 = time.monotonic()
    logger.info("[search] %.2f с  [rerank] %.2f с  chunks: %d → %d",
                t1 - t0, t2 - t1, len(chunks), len(top) if top else 0)
    if top is None:
        return "Релевантной информации не найдено."
    lines = []
    for i, ch in enumerate(top, 1):
        name = ch.get("name", "")
        text = ch.get("text") or ch.get("document", "")
        lines.append(f"[{i}] {name}\n{text.strip()}")
        if ch.get("notes"):
            lines.append(f"    Примечание: {ch['notes'].strip()}")
    return "\n".join(lines)


async def ai_agent_stream(
    user_message: str,
    history: list = None,
    user_name: str = "",
) -> AsyncGenerator[str, None]:
    """Agentic RAG loop.

    Итерации:
      - stream=False для всех decision-вызовов (tool или direct answer)
      - stream=True только для финального синтеза после поиска
      - ask_clarification: просто отдаёт вопрос пользователю и завершается
      - search_knowledge_base: до MAX_SEARCHES раз, затем форсируем финальный стрим
    """
    t_start = time.monotonic()
    loop = asyncio.get_event_loop()

    system = AGENT_SYSTEM
    if user_name:
        system += f"\n\nПользователя зовут {user_name}. Обращайся по имени."

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    search_count = 0

    try:
        while True:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                stream=False,
            )
            t_call = time.monotonic()
            msg = response.choices[0].message

            # ── Нет tool_call → финальный ответ ──────────────────────────────
            if not msg.tool_calls:
                content = msg.content or ""
                logger.info("[llm] %.2f с → прямой ответ: «%s»", t_call - t_start, content[:120])

                force_search = (
                    not content.strip()
                    or any(m in content.lower() for m in _FORCE_SEARCH_MARKERS)
                ) and search_count < MAX_SEARCHES

                if force_search:
                    reason = "пустой ответ" if not content.strip() else "маркер галлюцинации"
                    logger.warning("[llm] %s — форсируем поиск", reason)
                    yield "Минуточку, ищу информацию."
                    t_s = time.monotonic()
                    result = await loop.run_in_executor(None, _execute_search, user_message)
                    logger.info("[search] форс %.2f с", time.monotonic() - t_s)
                    search_count += 1
                    messages.append({"role": "assistant", "content": ""})
                    messages.append({
                        "role": "user",
                        "content": f"Используй эту информацию для ответа на вопрос:\n{result}\n\nВопрос: {user_message}"
                    })
                    continue

                if search_count > 0:
                    # После поиска: stream=True для минимальной задержки до первого аудио
                    t_llm = time.monotonic()
                    stream = await client.chat.completions.create(
                        model=LLM_MODEL, messages=messages, stream=True
                    )
                    first = True
                    async for sentence in _stream_sentences(stream):
                        if first:
                            logger.info("[llm] первый токен %.2f с от старта", time.monotonic() - t_start)
                            first = False
                        yield sentence
                else:
                    # Прямой ответ без поиска: контент уже есть, делим на предложения
                    if content:
                        for sentence in _split_sentences(content):
                            yield sentence
                    else:
                        yield "Извини, не смогла найти информацию по вашему вопросу."
                break

            # ── Tool call ─────────────────────────────────────────────────────
            tc = msg.tool_calls[0]
            logger.info("[llm] %.2f с → %s", t_call - t_start, tc.function.name)

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }]
            })

            # ── ask_clarification ─────────────────────────────────────────────
            if tc.function.name == "ask_clarification":
                try:
                    question = json.loads(tc.function.arguments).get("question", "")
                except Exception:
                    question = "Уточните, пожалуйста, ваш вопрос."
                logger.info("[llm] уточнение: «%s»", question[:80])
                yield question
                break  # ждём ответа пользователя в следующем туре

            # ── search_knowledge_base ─────────────────────────────────────────
            if tc.function.name == "search_knowledge_base":
                if search_count >= MAX_SEARCHES:
                    # Лимит исчерпан — форсируем финальный стрим без tool_choice
                    logger.warning("[llm] лимит поисков, форсируем финальный ответ")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": "Лимит поисков исчерпан. Ответь на основе уже найденной информации."
                    })
                    stream = await client.chat.completions.create(
                        model=LLM_MODEL, messages=messages, stream=True
                    )
                    async for sentence in _stream_sentences(stream):
                        yield sentence
                    break

                try:
                    query = json.loads(tc.function.arguments).get("query", user_message)
                except Exception:
                    query = user_message

                search_count += 1
                logger.info("[search] #%d запрос: «%s»", search_count, query[:60])

                yield "Минуточку, ищу информацию." if search_count == 1 else "Уточняю детали."

                t_s = time.monotonic()
                result = await loop.run_in_executor(None, _execute_search, query)
                logger.info("[search] #%d итого %.2f с", search_count, time.monotonic() - t_s)

                messages.append({
                    "role": "tool", "tool_call_id": tc.id, "content": result
                })
                # Продолжаем loop: LLM решает ответить или поискать ещё
                continue

        logger.info("[agent] цикл завершён %.2f с, поисков: %d", time.monotonic() - t_start, search_count)

    except Exception as e:
        logger.exception("Ошибка агента: %s", e)
        yield "Извини, произошла ошибка. Попробуй ещё раз."


# ─── STT ─────────────────────────────────────────────────────────────────────

_HALLUCINATION_MARKERS = [
    "субтитр",
    "продолжение следует",
    "переведено",
    "спасибо за просмотр",
    "подписывайтесь",
    "все права защищены",
    "на этом видео",
    "покажу вам",
    "не для информации",
    "смотрите также",
    "следующий выпуск",
    "ставьте лайк",
    "для информации",
]

_whisper: WhisperModel | None = None


def _get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        logger.info("Loading Whisper model (%s, cpu)...", WHISPER_MODEL)
        _whisper = WhisperModel(
            WHISPER_MODEL, device="cpu", compute_type="int8",
            download_root="/app/.whisper_cache",
        )
        logger.info("Whisper ready")
    return _whisper


def _is_hallucination(text: str) -> bool:
    t = text.strip().lower()
    if len(t) < 3:
        return True
    return any(m in t for m in _HALLUCINATION_MARKERS)


async def ai_voice_reqest(file) -> str | None:
    try:
        audio_bytes = file.read()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            t0 = time.monotonic()
            segments, _ = _get_whisper().transcribe(tmp_path, language="ru", beam_size=1)
            text = "".join(s.text for s in segments).strip()
            logger.info("[stt] %.2f с → «%s»", time.monotonic() - t0, text[:80])
        finally:
            os.unlink(tmp_path)

        if _is_hallucination(text):
            logger.info("[stt] галлюцинация: %s", text[:60])
            return None

        return text
    except Exception as e:
        logger.exception("Ошибка STT: %s", e)
        return None
