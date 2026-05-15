import io
import logging
import re

import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

_model = None
_sample_rate = 24000
_speaker = "xenia"


def load_model() -> None:
    global _model
    logger.info("Loading Silero TTS model...")
    _model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker="v3_1_ru",
        trust_repo=True,
    )
    logger.info("Silero TTS ready")


def _digit_pairs(s: str) -> str:
    """'3412' → '34, 12'  |  '776055' → '77, 60, 55'"""
    s = re.sub(r"[\s\-]", "", s)
    return ", ".join(s[i:i+2] for i in range(0, len(s), 2))


def _clean(text: str) -> str:
    text = re.sub(r"[*_`#>]", "", text)
    # телефоны: 8(3412)77-62-62 → 8, 34, 12, 77, 60, 55
    text = re.sub(
        r'8\s*\((\d{3,4})\)\s*([\d][\d\-\s]+\d)(?:\s*доб\.?\s*(\d+))?',
        lambda m: (
            f"8, {_digit_pairs(m.group(1))}, {_digit_pairs(m.group(2))}"
            + (f", добавочный {_digit_pairs(m.group(3))}" if m.group(3) else "")
        ),
        text,
    )
    # email: pk@istu.ru → pk, собака, istu точка ru
    text = re.sub(
        r'([\w.\-]+)@([\w\-]+(?:\.[\w\-]+)+)',
        lambda m: f"{m.group(1)}, собака, {m.group(2).replace('.', ' точка ')}",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def synthesize(text: str) -> bytes:
    if _model is None:
        raise RuntimeError("TTS model not loaded")
    audio = _model.apply_tts(text=_clean(text), speaker=_speaker, sample_rate=_sample_rate)
    buf = io.BytesIO()
    sf.write(buf, audio.numpy(), _sample_rate, format="WAV")
    buf.seek(0)
    return buf.read()
