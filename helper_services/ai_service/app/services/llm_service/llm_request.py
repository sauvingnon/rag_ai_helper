import asyncio
import tempfile
import os
import re
import json
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI
from faster_whisper import WhisperModel
from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL, WHISPER_MODEL
from app.logger import logger

# ─── Агент ───────────────────────────────────────────────────────────────────

AGENT_SYSTEM = """ВАЖНО: Отвечай ТОЛЬКО на русском языке. Никогда не используй другие языки.

Ты голосовой ассистент справочной службы университета. Общаешься по телефону.

ПРАВИЛО: Ты не знаешь ничего об этом университете из своей памяти. Любые конкретные факты об университете — факультеты, специальности, расписание, контакты, документы, требования, преподаватели, корпуса, стоимость обучения — ты ОБЯЗАН искать через инструмент search_knowledge_base. Отвечать по памяти на такие вопросы ЗАПРЕЩЕНО.

Вызывай search_knowledge_base при любом вопросе о:
- факультетах, кафедрах, институтах, направлениях, специальностях
- приёмной комиссии, документах, вступительных испытаниях, дедлайнах
- расписании, сессии, экзаменах, зачётах
- стоимости обучения, общежитии, стипендии
- контактах, адресах, корпусах, режиме работы
- преподавателях, деканах, ректорате

Не вызывай инструмент только если: вопрос неясный (переспроси), тема не касается университета (откажись вежливо), или это приветствие/благодарность.

ЗАПРЕЩЕНО:
- упоминать названия инструментов или функций (search_knowledge_base и т.п.)
- обещать перезвонить, отправить информацию позже, передать заявку
- говорить что "найдёшь информацию" — либо ищи прямо сейчас через инструмент, либо скажи что не знаешь
- придумывать информацию об университете из головы

Ты отвечаешь ПРЯМО СЕЙЧАС в реальном времени. Никаких обещаний "позже".

Отвечай кратко, 1-2 предложения. Это телефонный разговор. Язык: русский."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Поиск информации в базе знаний университета",
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

client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


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
                buffer = buffer[m.end() :]
                if sentence:
                    yield sentence
            elif len(buffer) > 200:
                split = buffer.rfind(" ", 0, 200)
                if split > 0:
                    yield buffer[:split].strip()
                    buffer = buffer[split + 1 :]
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
    """Агентский RAG: LLM сама решает когда и что искать. Отдаёт предложениями."""
    t_start = time.monotonic()

    system = AGENT_SYSTEM
    if user_name:
        system += f"\n\nПользователя зовут {user_name}. Обращайся по имени."

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        # Первый вызов: решение (нестриминг — ждём tool_call или прямой ответ)
        response = await client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=False,
        )
        t_decision = time.monotonic()
        msg = response.choices[0].message

        if msg.tool_calls:
            logger.info("[llm-decision] %.2f с → tool_call", t_decision - t_start)
            yield "Минуточку, ищу информацию."

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            loop = asyncio.get_event_loop()
            for tc in msg.tool_calls:
                if tc.function.name == "search_knowledge_base":
                    try:
                        query = json.loads(tc.function.arguments).get("query", user_message)
                    except Exception:
                        query = user_message
                    logger.info("[search] запрос: %s", query[:60])
                    t_s = time.monotonic()
                    result = await loop.run_in_executor(None, _execute_search, query)
                    logger.info("[search] итого %.2f с", time.monotonic() - t_s)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            yield "Почти нашла информацию для вас."

            t_llm2 = time.monotonic()
            stream = await client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                stream=True,
            )
            first_token = True
            async for sentence in _stream_sentences(stream):
                if first_token:
                    logger.info("[llm-answer] первый токен за %.2f с от старта / %.2f с от search",
                                time.monotonic() - t_start, time.monotonic() - t_llm2)
                    first_token = False
                yield sentence

        else:
            content = msg.content or ""
            logger.info("[llm-decision] %.2f с → прямой ответ: «%s»", t_decision - t_start, content[:120])
            # Пустой ответ или маркеры что модель хотела искать но не смогла — форсируем поиск
            _FORCE_SEARCH_MARKERS = [
                "search_knowledge_base",
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
            force_search = (
                not content.strip()
                or any(m in content.lower() for m in _FORCE_SEARCH_MARKERS)
            )
            if force_search:
                reason = "пустой ответ" if not content.strip() else "маркер галлюцинации"
                logger.warning("[llm-decision] %s — форсируем поиск", reason)
                yield "Минуточку, ищу информацию."
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _execute_search, user_message)
                yield "Почти нашла информацию для вас."
                messages.append({"role": "assistant", "content": ""})
                messages.append({"role": "user", "content": f"Используя эту информацию, ответь на вопрос пользователя:\n{result}\n\nВопрос: {user_message}"})
                stream = await client.chat.completions.create(
                    model=OLLAMA_MODEL, messages=messages, stream=True,
                )
                async for sentence in _stream_sentences(stream):
                    yield sentence
            else:
                for sentence in _split_sentences(content):
                    yield sentence

        logger.info("[agent] полный цикл %.2f с", time.monotonic() - t_start)

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
