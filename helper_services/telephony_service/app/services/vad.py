import collections
import logging

import numpy as np
import torch

logger = logging.getLogger(__name__)

_model = None

SAMPLE_RATE = 8000
CHUNK_SAMPLES = 256       # 32ms — обязательный размер чанка для Silero VAD при 8kHz
CHUNK_BYTES = CHUNK_SAMPLES * 2  # 16-bit

SPEECH_THRESHOLD = 0.65   # выше → говорит (поднято чтобы шум не триггерил)
SILENCE_THRESHOLD = 0.40  # ниже → тишина
SILENCE_CHUNKS_TO_END = 24  # ~768ms тишины после речи → конец фразы (24 × 32ms)
PRE_BUFFER_CHUNKS = 16      # ~512ms буфер до начала речи (16 × 32ms)


def load_vad() -> None:
    global _model
    logger.info("Loading Silero VAD...")
    _model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
    )
    logger.info("Silero VAD ready")


def _vad_prob(pcm: bytes) -> float:
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    return _model(torch.from_numpy(audio), SAMPLE_RATE).item()


class SpeechCollector:
    """
    Накапливает 20ms PCM-фреймы от Asterisk AudioSocket.
    feed() возвращает полный PCM буфер когда обнаружен конец фразы.
    """

    def __init__(self):
        self._pre_buf: collections.deque = collections.deque(maxlen=PRE_BUFFER_CHUNKS)
        self._speech_buf: list[bytes] = []
        self._raw_buf: bytes = b""
        self._speaking: bool = False
        self._silence_count: int = 0

    def feed(self, frame: bytes) -> bytes | None:
        self._raw_buf += frame
        result = None
        while len(self._raw_buf) >= CHUNK_BYTES:
            chunk, self._raw_buf = self._raw_buf[:CHUNK_BYTES], self._raw_buf[CHUNK_BYTES:]
            result = self._process(chunk)
            if result:
                break
        return result

    def _process(self, chunk: bytes) -> bytes | None:
        prob = _vad_prob(chunk)

        if not self._speaking:
            self._pre_buf.append(chunk)
            if prob > SPEECH_THRESHOLD:
                self._speaking = True
                self._silence_count = 0
                self._speech_buf = list(self._pre_buf)
                logger.debug("Speech started (prob=%.2f)", prob)
        else:
            self._speech_buf.append(chunk)
            if prob < SILENCE_THRESHOLD:
                self._silence_count += 1
                if self._silence_count >= SILENCE_CHUNKS_TO_END:
                    result = b"".join(self._speech_buf)
                    self._reset()
                    logger.debug("Speech ended: %d bytes", len(result))
                    return result
            else:
                self._silence_count = 0

        return None

    def _reset(self):
        self._speaking = False
        self._silence_count = 0
        self._speech_buf = []
        self._pre_buf.clear()
