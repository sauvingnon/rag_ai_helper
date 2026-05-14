import logging
import re

import numpy as np
import torch

logger = logging.getLogger(__name__)

_model = None
_TTS_SR = 24000
_TARGET_SR = 8000
_SPEAKER = "xenia"
_MAX_CHUNK = 300


def load_tts() -> None:
    global _model
    logger.info("Loading Silero TTS...")
    _model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v3_1_ru",
        trust_repo=True,
    )
    logger.info("Silero TTS ready")


def _clean(text: str) -> str:
    text = re.sub(r"[*_`#>\[\]]", "", text)
    # телефоны: 8(3412)77-62-62 или 8 (3412) 77-60-55 доб. 1345 → паузы через запятые
    text = re.sub(
        r'8\s*\((\d{3,4})\)\s*([\d][\d\-\s]+\d)(?:\s*доб\.?\s*(\d+))?',
        lambda m: (
            f"8, {m.group(1)}, {re.sub(r'[-]', ' ', m.group(2)).strip()}"
            + (f", добавочный {m.group(3)}" if m.group(3) else "")
        ),
        text,
    )
    # email: pk@istu.ru → пк, собака, исту точка ру
    text = re.sub(
        r'([\w.\-]+)@([\w\-]+(?:\.[\w\-]+)+)',
        lambda m: f"{m.group(1)}, собака, {m.group(2).replace('.', ' точка ')}",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _split(text: str) -> list[str]:
    """Разбить текст на куски ≤ _MAX_CHUNK символов по границам предложений."""
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(current) + len(sentence) > _MAX_CHUNK:
            if current:
                parts.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        parts.append(current)
    return parts or [text[:_MAX_CHUNK]]


def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    n = int(len(audio) * target_sr / orig_sr)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)


def synthesize_8k(text: str) -> bytes:
    """Возвращает сырой PCM: 8kHz, 16-bit, signed, little-endian, mono."""
    parts = []
    for chunk in _split(_clean(text)):
        audio = _model.apply_tts(text=chunk, speaker=_SPEAKER, sample_rate=_TTS_SR)
        audio_8k = _resample(audio.numpy(), _TTS_SR, _TARGET_SR)
        parts.append((audio_8k * 32767).clip(-32768, 32767).astype(np.int16))
    combined = np.concatenate(parts) if len(parts) > 1 else parts[0]
    return combined.tobytes()
