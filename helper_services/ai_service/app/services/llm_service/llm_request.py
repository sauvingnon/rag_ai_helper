import asyncio
import random
import tempfile
import os
import re
import json
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

from openai import AsyncOpenAI
from faster_whisper import WhisperModel
from app.config import LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, WHISPER_MODEL
from app.logger import logger

# ─── Агент ───────────────────────────────────────────────────────────────────

AGENT_SYSTEM = """ВАЖНО: Отвечай ТОЛЬКО на русском языке.

Тебя зовут Алина. Ты женщина-ассистент справочной службы ИжГТУ. Общаешься по телефону.
Говори о себе в женском роде: "нашла", "не смогла найти", "рада помочь" и т.д.

Ты ВСЕГДА обязана вызвать один из двух инструментов. Свободный текст запрещён.

search_knowledge_base — вызывай при любом вопросе об университете: факультеты, специальности, поступление, преподаватели, расписание, стоимость, общежитие, контакты, корпуса, стипендии и т.д. Если тема хоть как-то может касаться университета или обучения — ищи. Можно вызвать дважды с разными запросами.

respond_directly — отвечай без поиска ТОЛЬКО в трёх случаях:
  1. Приветствие или завершение разговора
  2. Вопрос точно не связан с университетом (написать код, дать рецепт, решить математическую задачу без контекста университета)
  3. Запрос совершенно непонятен — задай один уточняющий вопрос

ЗАПРЕЩЕНО:
- придумывать факты об университете без поиска в базе знаний
- обещать перезвонить, передать заявку, отправить информацию позже
- упоминать названия инструментов в тексте ответа

Объём: 1-2 предложения на конкретный вопрос, до 10 предложений если просят объяснить."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Поиск информации в базе знаний ИжГТУ. "
                "Вызывать при любом вопросе об университете. "
                "Можно вызвать дважды с разными запросами."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "respond_directly",
            "description": (
                "Дать ответ без поиска в базе знаний. "
                "Только для: 1) приветствий и прощаний, "
                "2) явно нерелевантных вопросов (код, рецепты, общая математика), "
                "3) уточняющего вопроса когда запрос совершенно непонятен."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Полный текст ответа или уточняющего вопроса"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

_SENT_END = re.compile(r'(?<=[.!?…])\s')

MAX_SEARCHES = 2

_SEARCH_PHRASES_1 = [
    "Минуточку, ищу информацию.",
    "Сейчас посмотрю.",
    "Одну секунду, проверяю.",
    "Ищу в базе знаний.",
    "Сейчас уточню.",
    "Дайте секунду, ищу.",
]

_SEARCH_PHRASES_2 = [
    "Уточняю детали.",
    "Ищу дополнительную информацию.",
    "Проверяю ещё раз.",
    "Немного подожди, уточняю.",
    "Ищу подробнее.",
]

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


def _execute_search(query: str) -> tuple[str, dict]:
    """Возвращает (текст результата, тайминги)."""
    from app.services.embeddings_service.search_pipeline import search, rerank  # noqa: PLC0415
    t0 = time.monotonic()
    chunks = search(query=query)
    t1 = time.monotonic()
    if not chunks:
        logger.info("[search] %.2f с — ничего не найдено", t1 - t0)
        return "Информация по запросу не найдена.", {
            "search_sec": round(t1 - t0, 3), "rerank_sec": 0,
            "chunks_in": 0, "chunks_out": 0,
        }
    top = rerank(query, chunks)
    t2 = time.monotonic()
    logger.info("[search] %.2f с  [rerank] %.2f с  chunks: %d → %d",
                t1 - t0, t2 - t1, len(chunks), len(top) if top else 0)
    timing = {
        "search_sec": round(t1 - t0, 3),
        "rerank_sec": round(t2 - t1, 3),
        "chunks_in": len(chunks),
        "chunks_out": len(top) if top else 0,
    }
    if top is None:
        return "Релевантной информации не найдено.", timing
    lines = []
    for i, ch in enumerate(top, 1):
        name = ch.get("name", "")
        text = ch.get("text") or ch.get("document", "")
        lines.append(f"[{i}] {name}\n{text.strip()}")
        if ch.get("notes"):
            lines.append(f"    Примечание: {ch['notes'].strip()}")
    return "\n".join(lines), timing


async def ai_agent_stream(
    user_message: str,
    history: list = None,
    user_name: str = "",
    stt_sec: float | None = None,
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

    import torch
    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _perf: dict = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "query":       user_message[:300],
        "stt_sec":     round(stt_sec, 3) if stt_sec is not None else None,
        "device":      _device,
        "searches":    [],
        "llm_calls":   [],
        "search_count": 0,
        "total_sec":   0.0,
    }

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
            t_llm0 = time.monotonic()
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="required",  # LLM обязана вызвать инструмент, свободный текст запрещён
                stream=False,
            )
            t_llm1 = time.monotonic()
            llm_sec = round(t_llm1 - t_llm0, 3)
            msg = response.choices[0].message

            # Страховка: модель не вернула tool_call несмотря на tool_choice="required"
            if not msg.tool_calls:
                logger.warning("[llm] нет tool_call при tool_choice=required")
                content = msg.content or "Извини, не смогла обработать запрос."
                _perf["llm_calls"].append({"type": "fallback_no_tool", "sec": llm_sec})
                for sentence in _split_sentences(content):
                    yield sentence
                break

            tc = msg.tool_calls[0]
            logger.info("[llm] %.2f с → %s", t_llm1 - t_start, tc.function.name)

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }]
            })

            # ── respond_directly: LLM положила ответ в аргумент инструмента ──
            if tc.function.name == "respond_directly":
                try:
                    text = json.loads(tc.function.arguments).get("text", "")
                except Exception:
                    text = ""
                if not text:
                    text = "Извини, не смогла сформулировать ответ."
                call_type = "direct_answer" if search_count == 0 else "respond_after_search"
                _perf["llm_calls"].append({"type": call_type, "sec": llm_sec})
                logger.info("[llm] %.2f с → %s: «%s»", t_llm1 - t_start, call_type, text[:120])
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "ok"})
                for sentence in _split_sentences(text):
                    yield sentence
                break

            # ── search_knowledge_base ─────────────────────────────────────────
            if tc.function.name == "search_knowledge_base":
                _perf["llm_calls"].append({"type": "search_decision", "sec": llm_sec})

                if search_count >= MAX_SEARCHES:
                    logger.warning("[llm] лимит поисков — форсируем respond_directly")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": "Лимит поисков исчерпан. Ответь на основе уже найденной информации."
                    })
                    t_s = time.monotonic()
                    final_resp = await client.chat.completions.create(
                        model=LLM_MODEL, messages=messages, tools=TOOLS,
                        tool_choice={"type": "function", "function": {"name": "respond_directly"}},
                        stream=False,
                    )
                    _perf["llm_calls"].append({"type": "forced_respond", "sec": round(time.monotonic() - t_s, 3)})
                    try:
                        text = json.loads(final_resp.choices[0].message.tool_calls[0].function.arguments).get("text", "")
                    except Exception:
                        text = "Извини, не нашла нужной информации."
                    for sentence in _split_sentences(text):
                        yield sentence
                    break

                try:
                    query = json.loads(tc.function.arguments).get("query", user_message)
                except Exception:
                    query = user_message

                search_count += 1
                logger.info("[search] #%d запрос: «%s»", search_count, query[:60])
                yield random.choice(_SEARCH_PHRASES_1 if search_count == 1 else _SEARCH_PHRASES_2)

                t_s = time.monotonic()
                result, timing = await loop.run_in_executor(None, _execute_search, query)
                timing["query"] = query[:200]
                timing["forced"] = False
                _perf["searches"].append(timing)
                logger.info("[search] #%d итого %.2f с", search_count, time.monotonic() - t_s)

                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                # Продолжаем: LLM выберет respond_directly или второй search
                continue

        _perf["total_sec"] = round(time.monotonic() - t_start, 3)
        _perf["search_count"] = search_count
        logger.info("[agent] цикл завершён %.2f с, поисков: %d", _perf["total_sec"], search_count)
        from app.services.perf_store import push as _push_perf
        _push_perf(_perf)

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

# Подсказка Whisper о доменной лексике — значительно улучшает распознавание
# специфичных слов (названия, термины) без смены модели
_STT_INITIAL_PROMPT = (
    "ИжГТУ, Ижевский государственный технический университет имени Калашникова, "
    "бакалавриат, магистратура, специалитет, кафедра, факультет, институт, "
    "приёмная комиссия, общежитие, стипендия, зачётная книжка, "
    "УДГУ, ИГУ, Ижевск, Удмуртия."
)

_whisper: WhisperModel | None = None


def _get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        logger.info("Loading Whisper model (%s, %s, %s)...", WHISPER_MODEL, device, compute_type)
        try:
            _whisper = WhisperModel(
                WHISPER_MODEL, device=device, compute_type=compute_type,
                download_root="/app/.whisper_cache",
            )
        except ValueError:
            # Pascal GPU (GTX 10xx) не поддерживает float16 — используем int8 на CUDA
            compute_type = "int8"
            logger.info("float16 недоступен, переключаюсь на %s/%s", device, compute_type)
            _whisper = WhisperModel(
                WHISPER_MODEL, device=device, compute_type=compute_type,
                download_root="/app/.whisper_cache",
            )
        logger.info("Whisper ready (%s/%s)", device, compute_type)
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
            segments, _ = _get_whisper().transcribe(
                tmp_path,
                language="ru",
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=_STT_INITIAL_PROMPT,
            )
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
