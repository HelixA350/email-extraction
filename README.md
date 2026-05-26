# Email Extraction Service

Сервис для автоматической обработки входящих писем с тендерными приглашениями.  
Реализует трёхэтапный AI-пайплайн (классификация → квалификация → извлечение атрибутов) и отправку результатов на вебхук.

## Архитектура

```
Входящее письмо (multipart)
        │
        ▼
  ┌──────────────┐     Kafka      ┌──────────────────┐
  │  /emails/extract │──────────►│  Worker (consumer) │
  │  (FastAPI)    │              │                   │
  └──────────────┘              │ 1. Classify       │
                                │ 2. Qualify        │
                                │ 3. Extract        │
                                └────────┬──────────┘
                                         │
                                         ▼
                                  ┌──────────────┐
                                  │   Webhook     │
                                  │   (CRM/API)   │
                                  └──────────────┘
```

## Этапы обработки

1. **Классификация** — определяет, является ли письмо новым приглашением к тендеру (`new_request`) или чем-то другим (`other`). Если не `new_request` — обработка прекращается.
2. **Квалификация** — бизнес-оценка целесообразности: проверка профиля, надёжности заказчика, финансов и географии. Вердикты: `берем`, `неберем`, `непонятно`. Если `неберем` — обработка прекращается.
3. **Извлечение атрибутов** — извлекает структурированные поля для CRM: название, тип, направление, описание, заказчика, номер лота, дедлайн.

Каждый этап использует LLM (по умолчанию `openai/gpt-5-mini`) с retry-логикой (exponential backoff, до 3 попыток).

## Быстрый старт

### Локально

```bash
# 1. Клонировать и перейти в директорию
cd email-extraction

# 2. Создать виртуальное окружение
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # Linux/Mac

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить окружение
cp .env.example .env
# отредактировать .env, указав ключи и адреса

# 5. Запустить API сервер
uvicorn app.main:app --host 0.0.0.0 --port 9002

# 6. (отдельный терминал) Запустить воркер
python -m app.worker
```

### Docker

```bash
# Сборка и запуск всех сервисов
docker compose up --build

# Только API + Worker (если Kafka уже запущен)
docker compose up api worker

# Остановка
docker compose down

# С полной очисткой томов
docker compose down -v
```

После запуска:
- **API**: http://localhost:9002
- **Kafbat UI**: http://localhost:9005

## API

### `GET /health`

Проверка работоспособности.

```json
{"status": "ok", "timestamp": "2026-05-26T10:00:00+00:00"}
```

### `POST /emails/extract`

Принимает письмо, ставит задачу в очередь Kafka.

**Content-Type:** `multipart/form-data`

| Поле | Тип | Описание |
|---|---|---|
| `meta` | JSON string | message_id, from, to[], subject, received_at (ISO8601) |
| `body` | JSON string | text (string|null), html (string|null) |
| `files` | binary[] | Вложения (опционально) |

**Ответ:**
```json
{"status": "success", "task_id": "uuid"}
```

### `POST /test`

Тестовый эндпоинт с идентичным входом. Возвращает task_id и немедленно отправляет тестовый вебхук с заглушкой на `TEST_WEBHOOK_URL`.

## Webhook (результат)

После успешной обработки сервис отправляет POST-запрос (multipart/form-data) на `WEBHOOK_URL`:

**JSON-часть:**
```json
{
  "title": "Название тендера",
  "request_type": "contest|survey",
  "activity_direction": "SP|S",
  "description": "Описание",
  "end_user": {"inn": "string", "name": "string"},
  "source": "email",
  "lot_number": "string",
  "tkp_deadline": "YYYY-MM-DD",
  "tender_files_url": "string",
  "scoring": {
    "pros": ["string"],
    "cons": ["string"]
  }
}
```

**Дополнительно:** файлы вложений (поле `files`).

## Переменные окружения (.env)

| Ключ | По умолчанию | Описание |
|---|---|---|
| `OPENAI_API_KEY` | — | API ключ OpenAI |
| `OPENAI_BASE_URL` | `https://api.agentplatform.ru/v1` | Базовый URL |
| `OPENAI_MODEL` | `openai/gpt-5-mini` | Модель |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9004` | Kafka brokers |
| `KAFKA_TOPIC_EMAILS` | `email-extraction-tasks` | Топик входящих задач |
| `KAFKA_CONSUMER_GROUP` | `email-extraction-workers` | Consumer group |
| `WEBHOOK_URL` | — | URL для результата |
| `TEST_WEBHOOK_URL` | — | URL для тестового вебхука |
| `MAX_RETRIES` | 3 | Попыток на LLM вызов |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `HOST` / `PORT` | `0.0.0.0:9002` | Сервер |
| `UPLOAD_DIR` | `./uploads` | Папка вложений |
| `UPLOAD_CLEANUP_HOURS` | 24 | Часов до удаления файлов |

## Структура проекта

```
email-extraction/
├── Dockerfile               # Образ для API и Worker
├── docker-compose.yml       # Оркестрация: ZK, Kafka, UI, API, Worker
├── references/              # Исходные демо-скрипты
├── uploads/                 # Временное хранение вложений
├── app/
│   ├── main.py              # FastAPI приложение
│   ├── worker.py            # Kafka consumer + пайплайн
│   ├── core/
│   │   ├── config.py        # Pydantic-settings
│   │   ├── logging.py       # Structlog
│   │   ├── kafka.py         # AIOKafka producer/consumer
│   │   └── prompts.py       # Централизованный загрузчик промптов
│   ├── schemas/
│   │   ├── email.py         # Модели входящего письма
│   │   ├── pipeline.py      # Модели этапов пайплайна
│   │   └── api.py           # Модели ответов API
│   ├── pipelines/
│   │   ├── classify.py      # Этап 1: классификация
│   │   ├── qualify.py       # Этап 2: квалификация
│   │   ├── extract.py       # Этап 3: извлечение
│   │   └── utils.py         # Утилиты (html_to_text и др.)
│   └── prompts/
│       ├── classify.md      # Промпт для классификации (MD)
│       ├── qualify.md       # Промпт для квалификации (MD)
│       └── extract.md       # Промпт для извлечения (MD)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```
