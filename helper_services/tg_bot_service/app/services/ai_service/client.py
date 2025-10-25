# services/remnawave/client.py

import httpx
from config import AI_SERVICE_URL

client = httpx.AsyncClient(base_url=AI_SERVICE_URL, timeout=120.0)