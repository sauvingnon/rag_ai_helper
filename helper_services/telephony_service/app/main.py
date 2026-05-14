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
import json
import logging
import os
import re
import struct
import uuid
import wave
from collections import deque

import httpx
from num2words import num2words

from app.services.vad import SpeechCollector, load_vad, _vad_prob, CHUNK_BYTES
from app.services.tts import load_tts, synthesize_8k
from app.services.session_store import load_session, save_session

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://ai_service:8005")
AUDIOSOCKET_PORT = int(os.getenv("AUDIOSOCKET_PORT", 9093))

GREETING_NEW      = "Здравствуйте! Вы позвонили в справочную службу Ижевского Государственного технического Университета имени Михаила Тимофеевича Калашникова. Как я могу к вам обращаться?"
GREETING_RETURN   = "Здравствуйте, {name}! Рада вас слышать снова. Чем могу помочь?"
MAX_USER_TURNS    = 20  # реплик пользователя в истории (каждая = 2 сообщения)

STOP_WORDS = {"стоп", "хватит", "прекрати", "остановись", "замолчи", "подожди", "тихо"}
_ECHO_WINDOW = 0.35   # секунд — игнорируем эхо после начала воспроизведения
_BARGE_IN_THRESHOLD = 0.75  # VAD порог для barge-in (выше чем обычный 0.65)
_MAX_BARGE_IN_SEC = 6.0  # максимальная длительность сбора barge-in фразы


def extract_name(text: str) -> str:
    """Вытаскивает имя из фразы типа 'меня зовут Иван' → 'Иван'."""
    t = text.strip()
    for pattern in [
        r'зовите\s+меня\s+(\w+)',
        r'меня\s+зовут\s+(\w+)',
        r'зовут\s+меня\s+(\w+)',
        r'^я\s+(\w+)',
    ]:
        m = re.search(pattern, t, re.IGNORECASE)
        if m:
            return m.group(1).capitalize()
    # Если просто одно слово или ничего не совпало — берём первое слово
    words = t.split()
    return words[0].capitalize() if words else t


class CallSession:
    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.name: str = ""
        self.name_received: bool = False
        self._history: deque = deque(maxlen=MAX_USER_TURNS * 2)

    def load(self) -> None:
        if not self.session_id:
            return
        data = load_session(self.session_id)
        self.name = data["name"]
        self.name_received = data["name_received"]
        for msg in data["history"]:
            self._history.append(msg)
        if self.name:
            logger.info("Сессия %s восстановлена: имя=%s, история=%d сообщ.",
                        self.session_id, self.name, len(self._history))

    def save(self) -> None:
        if self.session_id:
            save_session(self.session_id, self.name, self.name_received, list(self._history))

    @property
    def history(self) -> list:
        return list(self._history)

    def add_turn(self, user_msg: str, assistant_msg: str) -> None:
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": assistant_msg})
        self.save()

T_HANGUP, T_UUID, T_AUDIO, T_ERROR = 0x00, 0x01, 0x10, 0xff


def _normalize_for_tts(text: str) -> str:
    """Конвертирует цифры в русские слова чтобы Silero не пропускал их."""
    def _replace(m: re.Match) -> str:
        try:
            return num2words(int(m.group()), lang="ru")
        except Exception:
            return m.group()
    return re.sub(r"\b\d+\b", _replace, text)


# ─── AudioSocket helpers ──────────────────────────────────────────────────────

async def read_msg(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(3)
    msg_type = header[0]
    length = struct.unpack(">H", header[1:3])[0]
    payload = await reader.readexactly(length) if length else b""
    return msg_type, payload


_SILENCE_LEAD = b"\x00" * 960  # 60ms тишины перед первым предложением


async def send_audio(
    writer: asyncio.StreamWriter,
    pcm: bytes,
    lead_in: bool = True,
    cancel_event: asyncio.Event | None = None,
) -> None:
    frame_size = 320  # 20ms при 8kHz 16-bit
    data = (_SILENCE_LEAD if lead_in else b"") + pcm
    n_frames = (len(data) + frame_size - 1) // frame_size
    duration_ms = n_frames * 20
    t0 = asyncio.get_event_loop().time()
    logger.debug("send_audio: %d байт → %d фреймов (~%d мс)", len(pcm), n_frames, duration_ms)
    for idx, i in enumerate(range(0, len(data), frame_size)):
        if cancel_event and cancel_event.is_set():
            logger.info("send_audio: прерван barge-in на фрейме %d/%d", idx, n_frames)
            return
        frame = data[i:i + frame_size]
        writer.write(bytes([T_AUDIO]) + struct.pack(">H", len(frame)) + frame)
        await asyncio.sleep(0.02)
        if idx % 25 == 0:
            await writer.drain()
    await writer.drain()
    logger.debug("send_audio: готово за %.2f с (ожидалось %.2f с)", asyncio.get_event_loop().time() - t0, duration_ms / 1000)


def pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(pcm)
    return buf.getvalue()


# ─── AI pipeline ─────────────────────────────────────────────────────────────

async def query_ai_stream(
    wav: bytes,
    session: CallSession,
    writer: asyncio.StreamWriter,
    reader: asyncio.StreamReader | None = None,
) -> tuple[str, str, bytes | None]:
    """Стримит предложения из ai_service и воспроизводит их.
    Поддерживает barge-in: пользователь может прервать воспроизведение.
    Возвращает (user_msg, full_response, barge_in_pcm).
    """
    user_msg = ""
    full_response = ""
    first_sentence = True
    barge_in_pcm: bytes | None = None
    loop = asyncio.get_event_loop()
    pcm_queue: asyncio.Queue = asyncio.Queue()
    cancel_event = asyncio.Event()
    t_start = loop.time()

    async def _producer() -> None:
        nonlocal user_msg, full_response
        sentence_idx = 0
        try:
            logger.info("[producer] старт HTTP-стрима к ai_service")
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{AI_SERVICE_URL}/ai_service/voice/stream",
                    data={"history": json.dumps(session.history), "user_name": session.name},
                    files={"file": ("audio.wav", wav, "audio/wav")},
                ) as resp:
                    resp.raise_for_status()
                    logger.info("[producer] соединение установлено, ждём предложения")
                    async for line in resp.aiter_lines():
                        if cancel_event.is_set():
                            break
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("user_msg"):
                            user_msg = data["user_msg"]
                            logger.info("[producer] STT: %s", user_msg[:60])
                        sentence = data.get("sentence", "")
                        _HOLD_PHRASES = {"Минуточку, ищу информацию.", "Почти нашла информацию для вас."}
                        if sentence and not cancel_event.is_set():
                            sentence_idx += 1
                            if sentence not in _HOLD_PHRASES:
                                full_response += sentence + " "
                            t_tts = loop.time()
                            pcm = await loop.run_in_executor(None, synthesize_8k, _normalize_for_tts(sentence))
                            logger.info("[producer] предл.%d TTS %.2f с", sentence_idx, loop.time() - t_tts)
                            if not cancel_event.is_set():
                                await pcm_queue.put((sentence_idx, pcm))
            logger.info("[producer] стрим завершён, %d предл.", sentence_idx)
        except (httpx.ConnectError, asyncio.CancelledError):
            logger.warning("[producer] прерван или ai_service недоступен")
        except Exception as e:
            logger.error("[producer] ошибка: %s", e, exc_info=True)
        finally:
            await pcm_queue.put(None)

    async def _barge_in_detector() -> None:
        nonlocal barge_in_pcm
        if reader is None:
            return
        bc = SpeechCollector()
        raw_buf = b""
        speech_onset = False
        speech_onset_time: float = 0.0
        t0 = loop.time()

        while True:
            try:
                mtype, payload = await asyncio.wait_for(read_msg(reader), timeout=0.04)
            except asyncio.TimeoutError:
                if cancel_event.is_set() and not speech_onset:
                    return  # отменён по другой причине, речи не было
                continue
            except asyncio.CancelledError:
                return

            if mtype == T_HANGUP:
                cancel_event.set()
                return
            if mtype != T_AUDIO:
                continue

            # Эхо-окно: пропускаем первые 350мс
            if loop.time() - t0 < _ECHO_WINDOW:
                continue

            raw_buf += payload
            while len(raw_buf) >= CHUNK_BYTES:
                chunk, raw_buf = raw_buf[:CHUNK_BYTES], raw_buf[CHUNK_BYTES:]

                if not speech_onset:
                    prob = _vad_prob(chunk)
                    if prob > _BARGE_IN_THRESHOLD:
                        speech_onset = True
                        speech_onset_time = loop.time()
                        logger.info("[barge-in] речь обнаружена (prob=%.2f), останавливаем TTS", prob)
                        cancel_event.set()

                if speech_onset:
                    result = bc.feed(chunk)
                    if result:
                        barge_in_pcm = result
                        logger.info("[barge-in] фраза собрана: %d байт", len(result))
                        return
                    # Защита от бесконечного сбора на шумной линии
                    if loop.time() - speech_onset_time > _MAX_BARGE_IN_SEC:
                        barge_in_pcm = b"".join(bc._speech_buf) if bc._speech_buf else b""
                        logger.warning("[barge-in] лимит %.0fs достигнут, форсируем: %d байт",
                                       _MAX_BARGE_IN_SEC, len(barge_in_pcm))
                        return

    producer_task = asyncio.create_task(_producer())
    barge_in_task = asyncio.create_task(_barge_in_detector())

    # Плеер
    while True:
        try:
            item = await asyncio.wait_for(pcm_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            if cancel_event.is_set():
                logger.info("[player] прерван barge-in")
                break
            continue

        if item is None:
            logger.info("[player] очередь исчерпана")
            break

        if cancel_event.is_set():
            break

        sentence_idx, pcm = item
        duration_ms = len(pcm) // 320 * 20
        logger.info("[player] предл.%d: %d мс", sentence_idx, duration_ms)
        await send_audio(writer, pcm, lead_in=first_sentence, cancel_event=cancel_event)
        first_sentence = False

        if cancel_event.is_set():
            logger.info("[player] прерван во время предл.%d", sentence_idx)
            break

    # Ждём завершения barge-in (сбора полной фразы) если было прерывание
    if cancel_event.is_set():
        try:
            await asyncio.wait_for(barge_in_task, timeout=_MAX_BARGE_IN_SEC + 1.0)
        except asyncio.TimeoutError:
            logger.warning("[barge-in] timeout — фраза не собрана")

    barge_in_task.cancel()
    try:
        await barge_in_task
    except asyncio.CancelledError:
        pass

    producer_task.cancel()
    try:
        await producer_task
    except asyncio.CancelledError:
        pass

    logger.info("[stream] итого %.1f с", loop.time() - t_start)
    return user_msg, full_response.strip(), barge_in_pcm


async def transcribe_only(wav: bytes) -> str:
    """Только STT — для захвата имени без RAG."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/ai_service/transcribe",
                files={"file": ("audio.wav", wav, "audio/wav")},
            )
            resp.raise_for_status()
            return resp.json().get("text", "")
    except Exception as e:
        logger.error("Ошибка transcribe: %s", e)
        return ""


async def query_ai(wav: bytes, session: CallSession) -> tuple[str, str]:
    """Возвращает (user_msg, response) из ai_service."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/ai_service/voice",
                data={
                    "history": json.dumps(session.history),
                    "user_name": session.name,
                },
                files={"file": ("audio.wav", wav, "audio/wav")},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("user_msg", ""), data.get("response", "")
    except httpx.ConnectError:
        logger.warning("ai_service недоступен — звонок продолжается")
        return "", ""
    except Exception as e:
        logger.error("Ошибка запроса к ai_service: %s", e)
        return "", ""


# ─── Call handler ─────────────────────────────────────────────────────────────

async def handle_call(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr = writer.get_extra_info("peername")
    logger.info("Call connected from %s", addr)
    collector = SpeechCollector()
    session = CallSession()
    mute_until: float = 0.0

    async def drain_echo() -> None:
        nonlocal mute_until
        drained = 0
        while True:
            try:
                await asyncio.wait_for(read_msg(reader), timeout=0.012)
                drained += 1
            except asyncio.TimeoutError:
                break
        if drained:
            logger.debug("drain_echo: слито %d фреймов эха", drained)
        collector.__init__()
        mute_until = asyncio.get_event_loop().time() + 0.05

    async def play(pcm: bytes) -> None:
        logger.info("play: %d байт (~%d мс)", len(pcm), len(pcm) // 320 * 20)
        await send_audio(writer, pcm, lead_in=True)
        await drain_echo()
        logger.info("play: завершено")

    try:
        while True:
            msg_type, payload = await read_msg(reader)

            if msg_type == T_UUID:
                call_uuid = str(uuid.UUID(bytes=payload))
                logger.info("Call UUID: %s", call_uuid)
                session.session_id = call_uuid
                session.load()
                if session.name_received:
                    greeting = GREETING_RETURN.format(name=session.name)
                else:
                    greeting = GREETING_NEW
                await play(synthesize_8k(greeting))

            elif msg_type == T_AUDIO:
                if asyncio.get_event_loop().time() < mute_until:
                    continue  # эхо — отбрасываем

                speech_pcm = collector.feed(payload)
                if speech_pcm:
                    logger.info("Utterance ready — %d bytes PCM", len(speech_pcm))

                    if not session.name_received:
                        user_msg = await transcribe_only(pcm_to_wav(speech_pcm))
                        if user_msg:
                            name = extract_name(user_msg)
                            session.name = name
                            session.name_received = True
                            logger.info("Имя пользователя: %s", name)
                            answer = f"Очень приятно, {name}. Чем могу вам помочь?"
                        else:
                            answer = ""
                    else:
                        user_msg, answer, barge_in = await query_ai_stream(
                            pcm_to_wav(speech_pcm), session, writer, reader
                        )
                        await drain_echo()
                        logger.info("Q: %s | A: %s", (user_msg or "")[:60], (answer or "")[:60])
                        if answer and user_msg:
                            session.add_turn(user_msg, answer)

                        if barge_in:
                            barge_text = await transcribe_only(pcm_to_wav(barge_in))
                            logger.info("[barge-in] распознано: «%s»", (barge_text or "")[:80])
                            if not barge_text or any(w in barge_text.lower() for w in STOP_WORDS):
                                logger.info("[barge-in] стоп-команда")
                                await play(synthesize_8k("Хорошо."))
                            else:
                                logger.info("[barge-in] новый вопрос во время воспроизведения")
                                user_msg2, answer2, _ = await query_ai_stream(
                                    pcm_to_wav(barge_in), session, writer, reader
                                )
                                await drain_echo()
                                if user_msg2 and answer2:
                                    session.add_turn(user_msg2, answer2)

                        continue  # answer уже сыгран потоком, пропускаем play ниже

                    if answer:
                        await play(synthesize_8k(_normalize_for_tts(answer)))

            elif msg_type == T_HANGUP:
                logger.info("Call ended (HANGUP)")
                break

            elif msg_type == T_ERROR:
                logger.error("AudioSocket error payload: %s", payload)
                break

    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, OSError):
        logger.info("Connection lost from %s", addr)
    finally:
        try:
            writer.close()
        except Exception:
            pass


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
