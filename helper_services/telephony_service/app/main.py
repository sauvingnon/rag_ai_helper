"""
AudioSocket сервер — принимает звонки от Asterisk, обрабатывает голос,
отвечает синтезированной речью.

Протокол AudioSocket (бинарный, поверх TCP):
  [1 байт тип] [2 байта длина big-endian] [N байт payload]
  0x00 HANGUP — звонок завершён
  0x01 UUID   — идентификатор звонка (первое сообщение)
  0x10 AUDIO  — PCM-фрейм: 8kHz, 16-bit, signed, LE, mono
  0xff ERROR  — ошибка Asterisk
"""

import asyncio
import io
import logging
import os
import struct
import wave

import httpx

from app.services.vad import SpeechCollector, load_vad
from app.services.tts import load_tts, synthesize_8k

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai_service:8005")
AUDIOSOCKET_PORT = int(os.getenv("AUDIOSOCKET_PORT", 9093))

T_HANGUP, T_UUID, T_AUDIO, T_ERROR = 0x00, 0x01, 0x10, 0xff


# ─── AudioSocket helpers ──────────────────────────────────────────────────────

async def read_msg(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(3)
    msg_type = header[0]
    length = struct.unpack(">H", header[1:3])[0]
    payload = await reader.readexactly(length) if length else b""
    return msg_type, payload


_SILENCE_LEAD = b"\x00" * 960  # 60ms тишины перед ответом — RTP-сессия успевает подняться


async def send_audio(writer: asyncio.StreamWriter, pcm: bytes) -> None:
    frame_size = 320  # 20ms при 8kHz 16-bit
    data = _SILENCE_LEAD + pcm
    for idx, i in enumerate(range(0, len(data), frame_size)):
        frame = data[i:i + frame_size]
        writer.write(bytes([T_AUDIO]) + struct.pack(">H", len(frame)) + frame)
        await asyncio.sleep(0.02)        # реальное время — не перегружаем буфер Asterisk
        if idx % 25 == 0:               # flush каждые ~500ms
            await writer.drain()
    await writer.drain()


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(pcm)
    return buf.getvalue()


# ─── AI pipeline ─────────────────────────────────────────────────────────────

async def query_ai(wav: bytes) -> tuple[str, str]:
    """Возвращает (user_msg, response) из ai_service."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{AI_SERVICE_URL}/ai_service/voice",
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("user_msg", ""), data.get("response", "")


# ─── Call handler ─────────────────────────────────────────────────────────────

async def handle_call(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr = writer.get_extra_info("peername")
    logger.info("Call connected from %s", addr)
    collector = SpeechCollector()

    try:
        while True:
            msg_type, payload = await read_msg(reader)

            if msg_type == T_UUID:
                logger.info("Call UUID: %s", payload.hex())

            elif msg_type == T_AUDIO:
                speech_pcm = collector.feed(payload)
                if speech_pcm:
                    logger.info("Utterance ready — %d bytes PCM", len(speech_pcm))
                    user_msg, answer = await query_ai(pcm_to_wav(speech_pcm))
                    logger.info("Q: %s | A: %s", user_msg[:60], answer[:60])
                    if answer:
                        response_pcm = synthesize_8k(answer)
                        await send_audio(writer, response_pcm)

            elif msg_type == T_HANGUP:
                logger.info("Call ended (HANGUP)")
                break

            elif msg_type == T_ERROR:
                logger.error("AudioSocket error payload: %s", payload)
                break

    except (asyncio.IncompleteReadError, ConnectionResetError):
        logger.info("Connection lost from %s", addr)
    finally:
        writer.close()


# ─── Entry point ─────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("Initialising models...")
    load_vad()
    load_tts()

    server = await asyncio.start_server(handle_call, "0.0.0.0", AUDIOSOCKET_PORT)
    logger.info("AudioSocket server ready on port %d", AUDIOSOCKET_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
