from __future__ import annotations

import json
import re
import yaml
from pathlib import Path

from openai import AsyncOpenAI

from app.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from app.logger import logger

_client: AsyncOpenAI | None = None
_MAX_CHARS = 9000  # символов на один LLM-вызов (~6-7 страниц)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return _client


_SYSTEM = """Ты помощник для создания базы знаний университета.
Разбей текст на смысловые чанки. Каждый чанк — отдельная тема, факт или раздел.
Верни ТОЛЬКО JSON-массив без пояснений:
[
  {
    "name": "краткое название чанка",
    "text": "основной текст чанка",
    "keywords": "ключевые слова через запятую",
    "type": "general",
    "notes": ""
  }
]"""


def _split_text(text: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Разбивает текст на части по границам абзацев, не превышая max_chars."""
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    while text:
        if len(text) <= max_chars:
            parts.append(text)
            break
        # Ищем границу абзаца до max_chars
        cut = text.rfind("\n\n", 0, max_chars)
        if cut == -1:
            cut = text.rfind("\n", 0, max_chars)
        if cut == -1:
            cut = max_chars
        parts.append(text[:cut].strip())
        text = text[cut:].strip()

    return [p for p in parts if p]


def _parse_yaml(content: bytes) -> list[dict]:
    data = yaml.safe_load(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _extract_txt(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    import pypdf
    from io import BytesIO
    reader = pypdf.PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(content: bytes) -> str:
    from docx import Document
    from io import BytesIO
    doc = Document(BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


async def _llm_parse(text: str) -> list[dict]:
    resp = await _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": text},
        ],
        stream=False,
    )
    raw = resp.choices[0].message.content or "[]"
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    logger.error("LLM вернул не-JSON: %s", raw[:300])
    return []


async def file_to_chunks(filename: str, content: bytes) -> list[dict]:
    ext = Path(filename).suffix.lower().lstrip(".")

    if ext in ("yaml", "yml"):
        chunks = _parse_yaml(content)
        logger.info("YAML: %d чанков без LLM", len(chunks))
        return chunks

    if ext == "txt":
        text = _extract_txt(content)
    elif ext == "pdf":
        text = _extract_pdf(content)
    elif ext == "docx":
        text = _extract_docx(content)
    else:
        raise ValueError(f"Неподдерживаемый формат: {ext}")

    parts = _split_text(text)
    total_chars = len(text)
    logger.info("Текст: %d символов → %d частей", total_chars, len(parts))

    all_chunks: list[dict] = []
    for i, part in enumerate(parts, 1):
        logger.info("LLM часть %d/%d (%d символов)…", i, len(parts), len(part))
        chunks = await _llm_parse(part)
        logger.info("  → %d чанков", len(chunks))
        all_chunks.extend(chunks)

    logger.info("Итого: %d чанков из %d частей", len(all_chunks), len(parts))
    return all_chunks
