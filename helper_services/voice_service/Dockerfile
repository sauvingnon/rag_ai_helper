FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch — значительно меньше образ (~700 МБ вместо ~2.5 ГБ)
RUN pip install --no-cache-dir \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Silero TTS кешируется сюда при первом запуске
# Монтируем как volume чтобы не скачивать при каждом перезапуске
ENV TORCH_HOME=/app/.torch_cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
