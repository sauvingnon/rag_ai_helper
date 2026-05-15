# RAG Voice Assistant — ИжГТУ

Голосовой ассистент справочной службы Ижевского государственного технического университета имени М.Т. Калашникова. Принимает звонки по SIP-телефонии, отвечает на вопросы об университете синтезированной речью. Параллельно доступен браузерный интерфейс с голосовым и текстовым чатом.

---

## Архитектура — карта контейнеров

```
Звонящий
    │ SIP/RTP
    ▼
┌──────────────┐   AudioSocket TCP (PCM 8kHz)   ┌──────────────────────┐
│   asterisk   │ ────────────────────────────▶  │  telephony_service   │
│  порт 5060   │                                │      порт 9093       │
└──────────────┘                                │                      │
                                                │  Silero VAD          │
                                                │  faster-whisper STT  │
                                                │  Agentic RAG (HTTP)  │
                                                │  Silero TTS 8kHz     │
                                                │  barge-in детектор   │
                                                │  сессии на диске     │
                                                └──────────┬───────────┘
                                                           │ HTTP /ai_service/voice/stream
                                                           ▼
Браузер (голос+текст)                          ┌──────────────────────┐
    │ WebSocket /ws                             │     ai_service       │
    │ POST /chat                                │      порт 8005       │
    ▼                                           │                      │
┌──────────────────┐  HTTP /ai_service/*        │  faster-whisper STT  │
│  voice_service   │ ─────────────────────────▶ │  Agentic RAG loop    │
│   порт 8010      │                            │  SBERT + Cross-Enc   │
└──────────────────┘                            │  ChromaDB (векторы)  │
                                                └──────────┬───────────┘
                                                           │ bind mount (chroma_db, models)
Браузер (администратор)                                    │
    │ HTTP                                      ┌──────────▼───────────┐
    ▼                                           │    admin_service     │
┌──────────────────┐  S3 API (aiobotocore)      │      порт 8020       │
│  admin_service   │ ─────────────────────────▶ │                      │
│   порт 8020      │                            │  JWT-авторизация     │
└──────────────────┘                            │  Файлы → S3          │
                                                │  LLM-чанкер          │
                                                │  Индексация → Chroma │
                                                └──────────┬───────────┘
                                                           │ S3 API
                                                           ▼
                                                ┌──────────────────────┐
                                                │       garage         │
                                                │  порты 3900/3901/    │
                                                │        3902/3903     │
                                                │  self-hosted S3      │
                                                └──────────────────────┘
```

---

## Контейнеры

### `ai_service` — порт 8005

Мозг системы. Объединяет STT, векторный поиск и LLM-агент.

**STT — faster-whisper**

Модель `small`, CPU, int8-квантизация. Принимает WAV-файл, возвращает транскрипт.
- `beam_size=5` — баланс скорости и точности
- `vad_filter=True` — встроенная Silero-фильтрация тишины перед распознаванием
- `initial_prompt` — доменная подсказка с терминологией ИжГТУ (факультеты, специальности, топонимы) — значительно повышает точность на специфичной лексике

Защита от галлюцинаций: список маркеров (`"спасибо за просмотр"`, `"субтитр"` и т.д.) — если STT выдаёт такой текст, результат отбрасывается.

**RAG-пайплайн — двухэтапный поиск**

1. **SBERT** (`ai-forever/ru-en-RoSBERTa`) — быстрый семантический поиск по ChromaDB. Строит эмбеддинг запроса и находит `TOP_K` ближайших по cosine similarity чанков за миллисекунды.

2. **Cross-Encoder** (`DiTy/cross-encoder-russian-msmarco`) — точный реранкинг. Берёт пары `(запрос, чанк)` и вычисляет скор релевантности для каждой. Возвращает `RERANK_TOP` лучших. Если лучший скор ниже `RERANK_THRESHOLD` — возвращает `None` (запрос не релевантен базе).

Логика: SBERT быстро отсеивает кандидатов (ANN по всей базе), Cross-Encoder точно оценивает только их. Связка даёт баланс скорости и качества.

**Agentic RAG — LLM сам решает что делать**

LLM-агент получает два инструмента:
- `search_knowledge_base(query)` — вызывает RAG-пайплайн. До 2 раз за ход с разными формулировками.
- `ask_clarification(question)` — уточняющий вопрос, только если запрос совершенно непонятен.

Паттерны в реальных звонках:
- `"когда основан университет?"` → прямой ответ без поиска
- `"расскажи про кафедру ИВТ"` → один поиск → ответ
- `"что нужно для поступления на IT и есть ли общежитие?"` → два поиска → ответ

Защита от галлюцинаций: список маркеров (`"перезвоню"`, `"уточню"`, `"проверю"` и т.д.) — если LLM пытается дать такой ответ вместо поиска, форсируется поиск.

**Фразы ожидания при поиске** — рандомизированы (два пула: для первого и повторного поиска):
```
"Минуточку, ищу информацию."  /  "Сейчас посмотрю."  /  "Одну секунду, проверяю."  / ...
```

**Эндпоинты:**
| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/ai_service/chat` | Текстовый чат `{message, history[]}` → строка |
| `POST` | `/ai_service/voice` | Голос: файл + history + user_name → `{user_msg, response}` |
| `POST` | `/ai_service/voice/stream` | То же, но NDJSON-стрим предложений |
| `POST` | `/ai_service/transcribe` | Только STT, без RAG |
| `POST` | `/reload-db` | Перезагрузить ChromaDB в памяти (вызывается после индексации) |

**ChromaDB** — `PersistentClient`, коллекция `chroma`. Общая bind-mount директория с `admin_service` (`./ai_service/chroma_db`). После индексации `admin_service` дёргает `/reload-db` — `ai_service` пересоздаёт клиент и начинает видеть новые чанки без перезапуска.

---

### `telephony_service` — порт 9093

AudioSocket-сервер. Принимает TCP-соединения от Asterisk и ведёт голосовой диалог.

**Протокол AudioSocket (бинарный, поверх TCP):**
```
[1 байт тип] [2 байта длина big-endian] [N байт payload]

0x01  UUID   — первое сообщение, 16 байт идентификатора звонка
0x10  AUDIO  — PCM-фрейм: 8kHz, 16-bit signed LE mono
0x00  HANGUP — звонок завершён
0xff  ERROR  — ошибка со стороны Asterisk
```

**UUID сессии** генерируется в Asterisk из MD5(CallerID):
```
Set(H=${MD5(${CALLERID(num)})})
Set(CALL_UUID=${H:0:8}-${H:8:4}-${H:12:4}-${H:16:4}-${H:20:12})
```
Один и тот же номер → всегда один и тот же UUID → один и тот же файл сессии на диске.

**Жизненный цикл звонка:**
1. Asterisk присылает UUID → сервис загружает сессию (история + имя) из JSON-файла
2. Если имя известно: `"Здравствуйте, Иван! Рада вас слышать снова."`, иначе — стандартное приветствие с просьбой назвать имя
3. Silero VAD слушает поток, буферизует речь, детектирует паузу конца реплики
4. PCM-буфер → WAV → `POST /ai_service/voice/stream` (NDJSON по предложениям)
5. Каждое предложение ответа сразу синтезируется и отправляется в AudioSocket
6. История и имя сохраняются на диск после каждого хода

**VAD — Silero VAD:**
- Chunk: строго 256 сэмплов (512 байт) при 8kHz — иначе модель падает
- Порог обнаружения: 0.65 для обычного сбора, 0.75 для barge-in

**TTS — Silero v3 (`xenia`):**
- Генерирует 24kHz → ресэмпл до 8kHz линейной интерполяцией
- Предобработка перед синтезом:
  - Телефоны → группы с паузами: `8(3412)77-62-62` → `8, 3412, 77 62 62`
  - Email → вслух: `user@mail.ru` → `user собака mail точка ru`
  - Числа → слова (через `num2words`)
- 60мс тишины в начале каждого фрагмента (lead-in) — Asterisk обрезает первые байты без него

**Barge-in (перебивание ассистента):**
- Пока ассистент воспроизводит аудио, VAD параллельно слушает входящий поток
- Если VAD ≥ 0.75 → воспроизведение прерывается, начинается сбор новой фразы
- Эхо-окно 350мс после начала воспроизведения защищает от самопрерывания TTS
- Stop-words (`"стоп"`, `"хватит"`, `"замолчи"` и др.) мгновенно прерывают речь

**Персистентные сессии** (`session_store.py`):
- Хранятся в `/app/sessions/{UUID}.json`
- Структура: `{name, name_received, history: [{role, content}, ...]}`
- Лимит: 20 пар реплик (40 сообщений), старые обрезаются
- Том `telephony_sessions` монтируется в Docker — переживают перезапуск контейнера

**Стриминг ответа** — минимизация задержки до первого звука:
- `ai_service` отдаёт предложения по одному через NDJSON
- Каждое предложение синтезируется и отправляется сразу
- Пользователь слышит первое предложение через ~2–3с, а не ждёт весь ответ

---

### `asterisk`

Docker-образ `mlan/asterisk`. SIP-сервер для приёма звонков.

**Конфигурация** (`helper_services/config/`):
- `pjsip.conf` — учётные записи SIP-клиентов (Zoiper, MicroSIP и т.д.)
- `extensions.conf` — диалплан:
  ```
  exten => 2000,1,Answer()
  exten => 2000,n,Set(H=${MD5(${CALLERID(num)})})
  exten => 2000,n,Set(CALL_UUID=...)
  exten => 2000,n,AudioSocket(${CALL_UUID},telephony_service:9093)
  ```
- `rtp.conf` — диапазон RTP-портов: 10000–10100

Набери `2000` из SIP-клиента — попадёшь к ассистенту.

---

### `admin_service` — порт 8020

Веб-панель управления базой знаний. Доступна через браузер на `http://host:8020`.

**Авторизация:** JWT-cookie (логин/пароль из `.env`). Все `/admin/*` роуты защищены middleware.

**Вкладка «Файлы»:**
- Загрузка файлов в Garage S3 (`.txt`, `.yaml`, `.yml`, `.pdf`, `.docx`)
- Просмотр текстовых файлов (TXT/YAML) прямо в панели, PDF открывается в новой вкладке
- Скачивание, удаление
- Колонка «Чанки» показывает зелёный счётчик если файл проиндексирован
- Кнопка «▶ Индекс» — запускает фоновую индексацию файла

**Вкладка «Чанки»:**
- Просмотр всех чанков в ChromaDB (с пагинацией, фильтром по файлу)
- Редактирование чанка (name, type, text, keywords, notes)
- Удаление чанка
- **Создание чанка вручную** — кнопка «+ Создать», модальное окно с полями

**Вкладка «Задачи»:**
- Лог всех запусков индексации (статусы: ожидание / выполняется / готово / ошибка)
- Автообновление раз в 3с пока есть активные задачи

**Вкладка «Справка»:**
- Схема работы системы, FAQ, объяснение что такое чанки и как работает индексация

**Пайплайн индексации (фоновая задача):**
1. Скачать файл из Garage S3
2. Извлечь текст (TXT/YAML — напрямую, PDF — `pypdf`, DOCX — `python-docx`)
3. YAML → парсить напрямую без LLM. Всё остальное → LLM-чанкер
4. LLM-чанкер: разбить текст на части ≤9000 символов по абзацам, для каждой части вызвать LLM с промптом `"разбей на смысловые чанки, верни JSON"`
5. Удалить старые чанки файла из ChromaDB (по `source_file_id`)
6. Записать новые чанки батчами по 50
7. Вызвать `POST /reload-db` на ai_service — горячая перезагрузка ChromaDB без рестарта

**S3-слой** (`s3_manager.py`):
- Ключ объекта: `files/{uuid4}/{url-encoded-filename}`
- Метаданные (size, content_type, uploaded_at) хранятся в S3 user metadata
- Соединение — lazy, с asyncio.Lock для thread safety

**Эндпоинты:**
| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/auth/login` | Логин → JWT cookie |
| `POST` | `/auth/logout` | Выйти |
| `GET` | `/admin/files` | Список файлов |
| `POST` | `/admin/files` | Загрузить файл |
| `GET` | `/admin/files/{id}/download` | Скачать |
| `GET` | `/admin/files/{id}/view` | Просмотр inline |
| `DELETE` | `/admin/files/{id}` | Удалить |
| `POST` | `/admin/files/{id}/index` | Запустить индексацию |
| `GET` | `/admin/chunks` | Список чанков (пагинация, фильтр по file_id) |
| `POST` | `/admin/chunks` | Создать чанк вручную |
| `GET` | `/admin/chunks/stats` | Кол-во чанков по file_id |
| `GET` | `/admin/chunks/{id}` | Один чанк |
| `PUT` | `/admin/chunks/{id}` | Обновить чанк |
| `DELETE` | `/admin/chunks/{id}` | Удалить чанк |
| `GET` | `/admin/tasks` | Журнал задач индексации |

---

### `garage` — порты 3900–3903

Self-hosted S3-совместимое хранилище. Хранит исходные файлы базы знаний (до индексации).

| Порт | Назначение |
|---|---|
| 3900 | S3 API (основной) |
| 3901 | RPC (внутренний) |
| 3902 | Admin HTTP API |
| 3903 | Web UI |

Данные в Docker volume `garage_data`. Bucket: `video-bucket` (имя историческое, содержит файлы БЗ).

Healthcheck: TCP-connect к порту 3900.

---

### `voice_service` — порт 8010

Браузерный интерфейс. Два режима ввода, единая история диалога.

**Голосовой режим (WebSocket `/ws`):**
- Кнопка «держать и говорить» (push-to-talk)
- Запись через MediaRecorder (WebM/Opus)
- Перед отправкой аудио клиент шлёт JSON с историей: `ws.send({history: [...]})`
- Сервер передаёт аудио + историю в ai_service, получает текст + синтезирует WAV (Silero)
- Ответ — сначала JSON с текстом (отображается пузырём), затем бинарный WAV (воспроизводится)

**Текстовый режим (REST `POST /chat`):**
- Поле ввода текста под голосовой кнопкой, отправка Enter или кнопкой `→`
- `POST /chat {message, history}` → ai_service → текстовый ответ
- Без TTS — только текст (режим «просто переписка»)

**Единая история:** одна переменная `chatHistory` на всю страницу. Голос и текст пишут в неё и читают из неё. Написал вопрос текстом → переключился на голос → ассистент помнит контекст.

**Лимит истории:** 20 пар (40 сообщений), хранится в JS-памяти страницы (теряется при перезагрузке).

**UI:** сообщения новые сверху (prepend), тёмная тема, пузыри user/assistant.

---

## Docker Compose — порты и тома

```yaml
# Порты (хост → контейнер)
garage:           3900-3903
admin_service:    8020
ai_service:       8005
voice_service:    8010
telephony_service: 9093
asterisk:         5060 (SIP), 10000-10100/udp (RTP)

# Тома
garage_data:          данные Garage S3
ai_whisper_cache:     кэш модели Whisper
voice_torch_cache:    кэш PyTorch (Silero TTS для voice_service)
telephony_torch_cache: кэш PyTorch (Silero VAD/TTS для телефонии)
telephony_sessions:   JSON-файлы сессий по звонкам

# Bind mounts (данные на хосте)
./ai_service/chroma_db  → ai_service + admin_service (общая ChromaDB)
./ai_service/models     → ai_service + admin_service (модели SBERT/Cross-Encoder, только чтение)
./config                → asterisk (конфиги pjsip/extensions/rtp)
```

**Порядок запуска** (через healthcheck `depends_on`):
```
garage → admin_service
         ai_service → telephony_service → asterisk
                   → voice_service
```

---

## База знаний

### Формат YAML-чанка

```yaml
- type: Подразделение
  name: Кафедра информатики и вычислительной техники
  keywords: ИВТ, программирование, вычислительная техника, кафедра
  text: |
    Кафедра основана в 1985 году. Ведёт подготовку бакалавров
    по направлению 09.03.03 «Прикладная информатика».
    Штат: 12 преподавателей, из них 3 профессора.
  meta:
    notes: |
      Заведующий: Петров П.П., д.т.н.
      Телефон: 8 (3412) 77-60-55 доб. 3101
      Email: ivt@istu.ru
      Адрес: корпус 2, каб. 412
```

**Что участвует в эмбеддинге:** `name + text + keywords` → вектор SBERT

**Что попадает в контекст LLM, но не в вектор:** `notes` — контакты, адреса, уточнения

**Принцип:** один чанк = одна смысловая единица. Если смешать в один чанк 10 кафедр — SBERT сделает размытый вектор и поиск по конкретной кафедре не сработает.

### Создание и обновление чанков

**Из файла** (автоматически через admin_service):
1. Загрузить файл → «▶ Индекс»
2. LLM разбивает текст на чанки с `name`, `text`, `keywords`, `type`, `notes`
3. YAML парсится напрямую без LLM
4. При повторной индексации старые чанки файла удаляются, новые записываются

**Вручную** (через admin_service → вкладка «Чанки» → «+ Создать»):
- Поля: Название, Тип, Текст, Ключевые слова, Примечания
- Чанк сразу доступен для поиска (нет source_file_id)

**Через `db_loader`** (исходный способ, без admin_service):
```bash
cd helper_services/db_loader
python db_loader.py  # читает data/*.yaml, грузит в ChromaDB напрямую
```

---

## Конфигурация

### ai_service `.env`

```env
# LLM (OpenAI-совместимый API)
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...

# Модели
SBERT_MODEL=ai-forever/ru-en-RoSBERTa
CROSS_ENCODER_MODEL=DiTy/cross-encoder-russian-msmarco
SBERT_MODEL_PATH=/app/services/embeddings_service/models/sbert_model
CROSS_ENCODER_MODEL_PATH=/app/services/embeddings_service/models/cross_encoder_model

# RAG параметры
TOP_K=20               # кандидатов от SBERT
RERANK_TOP=5           # финальных чанков в контекст LLM
RERANK_THRESHOLD=-2.0  # ниже — считаем нерелевантным

# STT
WHISPER_MODEL=small    # tiny / base / small / medium
```

### admin_service `.env`

```env
# S3 (Garage)
S3_ENDPOINT=http://garage:3900
S3_ACCESS_KEY=GK...
S3_SECRET_KEY=...
S3_BUCKET=rag-files

# LLM (тот же для чанкера)
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-...

# Авторизация
ADMIN_LOGIN=admin
ADMIN_PASSWORD=changeme
JWT_SECRET=change-this-secret
JWT_EXPIRE_HOURS=24

# ai_service (для reload-db)
AI_SERVICE_URL=http://ai_service:8005
```

### Варианты LLM

| Провайдер | BASE_URL | MODEL | Примечание |
|---|---|---|---|
| DeepSeek (дефолт) | `https://api.deepseek.com/v1` | `deepseek-chat` | Хорошее качество, низкая цена |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | Очень быстрый, есть free tier |
| Ollama (локальный) | `http://host.docker.internal:11434/v1` | `qwen2.5:7b` | Полный offline |

---

## Запуск

### 1. Скачать модели (один раз)

```bash
python helper_services/ai_service/dowloand.py
# Сохраняет SBERT и Cross-Encoder в helper_services/ai_service/models/
```

### 2. Создать `.env` файлы

Скопировать `.env.example` (если есть) или создать вручную для:
- `helper_services/ai_service/.env`
- `helper_services/admin_service/.env`

### 3. Поднять сервисы

```bash
cd helper_services
docker compose up -d
```

### 4. Инициализировать Garage S3 (при первом запуске)

```bash
# Подождать пока garage стартует, затем:
docker exec -it <garage_container> garage layout assign ...
docker exec -it <garage_container> garage bucket create rag-files
```

### 5. Загрузить базу знаний

**Вариант A — через admin_service (рекомендуется):**
1. Открыть `http://localhost:8020`
2. Войти (логин/пароль из `.env`)
3. Загрузить YAML/TXT/PDF файлы через «Файлы»
4. Нажать «▶ Индекс» напротив каждого файла
5. Дождаться зелёного счётчика в колонке «Чанки»

**Вариант B — напрямую через db_loader:**
```bash
cd helper_services/db_loader
python db_loader.py  # читает data/*.yaml
# Скопировать chroma_db в ai_service/chroma_db/
```

### 6. Подключить SIP-клиент

Настроить Zoiper/MicroSIP на `localhost:5060`. Набрать `2000`.

---

## Структура проекта

```
helper_services/
├── ai_service/                   # RAG + LLM + STT
│   ├── app/
│   │   ├── api/endpoints/        # POST /chat, /voice, /voice/stream, /transcribe
│   │   ├── services/
│   │   │   ├── embeddings_service/  # SBERT, Cross-Encoder, ChromaDB, search_pipeline
│   │   │   └── llm_service/         # Agentic RAG loop, инструменты, STT
│   │   └── config.py
│   ├── models/                   # Веса SBERT + Cross-Encoder (bind mount)
│   ├── chroma_db/                # Векторная БД (bind mount, общая с admin_service)
│   └── .env
│
├── telephony_service/            # AudioSocket сервер
│   └── app/
│       ├── main.py               # Основной цикл, протокол AudioSocket, barge-in
│       └── services/
│           ├── vad.py            # Silero VAD, SpeechCollector
│           ├── tts.py            # Silero TTS, предобработка, ресэмпл
│           └── session_store.py  # Персистентные сессии (JSON)
│
├── voice_service/                # Браузерный интерфейс
│   └── app/
│       ├── main.py               # WS /ws (голос) + POST /chat (текст)
│       ├── services/tts.py       # Silero TTS для веба
│       └── static/index.html     # SPA: push-to-talk + текстовый чат
│
├── admin_service/                # Панель управления БЗ
│   └── app/
│       ├── api/
│       │   ├── auth.py           # JWT login/logout
│       │   ├── files.py          # CRUD файлов S3
│       │   ├── chunks.py         # CRUD чанков ChromaDB
│       │   └── indexing.py       # Запуск индексации
│       ├── services/
│       │   ├── s3_manager.py     # S3-слой (aiobotocore)
│       │   ├── llm_chunker.py    # LLM-разбивка файлов на чанки
│       │   ├── indexer.py        # Полный пайплайн индексации
│       │   ├── embedder.py       # SBERT для admin_service
│       │   ├── chroma_client.py  # ChromaDB клиент
│       │   └── task_store.py     # In-memory журнал задач
│       └── static/index.html     # Vue 3 SPA (CDN, no build)
│
├── config/                       # Конфиги Asterisk
│   ├── pjsip.conf                # SIP-аккаунты
│   ├── extensions.conf           # Диалплан (MD5 UUID, AudioSocket)
│   └── rtp.conf                  # RTP порты 10000-10100
│
├── db_loader/                    # Утилиты загрузки БЗ (вне Docker)
│   ├── db_loader.py              # YAML → ChromaDB напрямую
│   ├── _clean_departments.py     # LLM-очистка сырого скрапа
│   └── data/                     # Исходные YAML файлы
│
├── garage.toml                   # Конфиг Garage S3
└── docker-compose.yml
```

---

## Отладка

| Симптом | Причина | Решение |
|---|---|---|
| Chroma ничего не находит | Пустая база / не та модель | Проверить что `db_loader` / `admin_service` запускались с той же SBERT что в `.env` |
| LLM отвечает мимо базы | Шумные/смешанные чанки | Один чанк = одна тема. Пересмотреть YAML |
| Rerank возвращает None | `RERANK_THRESHOLD` завышен | Понизить до `-2.0` |
| Новые чанки не находятся | ChromaDB закэширована в памяти | Нажать «▶ Индекс» снова, или вручную POST `/reload-db` |
| Нет звука из Asterisk | NAT или AudioSocket недоступен | Проверить `pjsip.conf`, порт 9093 |
| Silero падает на VAD | Неправильный размер чанка | VAD при 8kHz требует ровно 256 сэмплов (512 байт) |
| TTS обрезает начало | Нет lead-in тишины | В `send_audio` должен быть 60мс prepend |
| Garage не стартует | Неинициализированный кластер | Выполнить `garage layout assign` и создать bucket |
| Индексация зависла | LLM не отвечает / timeout | Смотреть логи `admin_service`, проверить LLM_API_KEY |
| История диалога сбрасывается (телефон) | Том `telephony_sessions` не смонтирован | Проверить volumes в docker-compose |
