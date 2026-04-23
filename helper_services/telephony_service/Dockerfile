FROM python:3.11-slim

WORKDIR /app

# CPU-only torch — меньше размер образа
RUN pip install --no-cache-dir \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV TORCH_HOME=/app/.torch_cache

CMD ["python", "-m", "app.main"]
