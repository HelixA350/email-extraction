import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.kafka import get_producer, send_task
from app.core.logging import configure_logging, get_logger
from app.schemas.api import HealthResponse, TaskResponse
from app.schemas.email import EmailBody, EmailInput, EmailMeta
from app.schemas.pipeline import EndUser, Scoring, WebhookPayload

logger = get_logger(__name__)

configure_logging()

app = FastAPI(title="Email Extraction Service", version="1.0.0")


# ── File helpers ──

def _save_upload_files(task_id: str, files: Optional[list[UploadFile]]) -> list[str]:
    if not files:
        return []
    task_dir = Path(settings.upload_dir) / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []
    for f in files:
        if f.filename:
            dest = task_dir / f.filename
            with open(dest, "wb") as buf:
                buf.write(f.file.read())
            saved_paths.append(str(dest.resolve()))
    return saved_paths


async def _periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(settings.upload_cleanup_hours * 3600)
        _cleanup_old_uploads()


def _cleanup_old_uploads() -> None:
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.is_dir():
        return
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - settings.upload_cleanup_hours * 3600
    for entry in upload_dir.iterdir():
        if entry.is_dir():
            mtime = entry.stat().st_mtime
            if mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                logger.info("upload.cleaned", path=str(entry))


# ── Lifespan ──

@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(_periodic_cleanup())
    app.state.kafka_producer = await get_producer()
    logger.info("service.started", host=settings.host, port=settings.port)


@app.on_event("shutdown")
async def shutdown() -> None:
    producer = getattr(app.state, "kafka_producer", None)
    if producer:
        await producer.stop()
    logger.info("service.stopped")


# ── Endpoints ──

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@app.post("/emails/extract", response_model=TaskResponse)
async def extract_email(
    meta: str = Form(..., description="JSON с полями message_id, from, to, subject, received_at"),
    body: str = Form(..., description="JSON с полями text, html"),
    files: Optional[list[UploadFile]] = File(None, description="Вложения"),
) -> JSONResponse:
    meta_parsed = EmailMeta(**json.loads(meta))
    body_parsed = EmailBody(**json.loads(body))

    task_id = str(uuid.uuid4())
    saved_paths = _save_upload_files(task_id, files or [])

    task_data = {
        "task_id": task_id,
        "meta": meta_parsed.model_dump(by_alias=True, mode="json"),
        "body": body_parsed.model_dump(mode="json"),
        "file_paths": saved_paths,
    }

    producer = getattr(app.state, "kafka_producer", None)
    if producer:
        await send_task(producer, task_data)

    logger.info(
        "email.queued",
        task_id=task_id,
        message_id=meta_parsed.message_id,
        subject=meta_parsed.subject,
        file_count=len(saved_paths),
    )

    return JSONResponse(content=TaskResponse(status="success", task_id=task_id).model_dump())


@app.post("/test", response_model=TaskResponse)
async def test_endpoint(
    meta: str = Form(..., description="JSON с полями message_id, from, to, subject, received_at"),
    body: str = Form(..., description="JSON с полями text, html"),
    files: Optional[list[UploadFile]] = File(None, description="Вложения"),
) -> JSONResponse:
    meta_parsed = EmailMeta(**json.loads(meta))
    body_parsed = EmailBody(**json.loads(body))

    task_id = str(uuid.uuid4())
    saved_paths = _save_upload_files(task_id, files or [])

    logger.info(
        "test.email_received",
        task_id=task_id,
        message_id=meta_parsed.message_id,
        subject=meta_parsed.subject,
    )

    payload = WebhookPayload(
        title=f"[TEST] {meta_parsed.subject}",
        request_type="contest",
        activity_direction="SP",
        description=body_parsed.text or "Тестовое описание закупки",
        end_user=EndUser(inn="7702123456", name="ООО Тест-Заказчик"),
        source="email",
        lot_number="TEST-LOT-001",
        tkp_deadline=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        tender_files_url=f"/uploads/{task_id}" if saved_paths else "",
        scoring=Scoring(pros=["Тестовый плюс"], cons=["Тестовый минус"]),
    )

    await _send_webhook_to_url(settings.test_webhook_url, payload, saved_paths)

    return JSONResponse(content=TaskResponse(status="success", task_id=task_id).model_dump())


async def _send_webhook_to_url(
    url: str, payload: WebhookPayload, file_paths: list[str]
) -> None:
    if not url:
        logger.warning("webhook.no_url", url=url)
        return

    try:
        payload_dict = payload.model_dump()
        logger.info("webhook.sending", url=url, payload=payload_dict)
        json_str = json.dumps(payload_dict, ensure_ascii=False)
        async with httpx.AsyncClient(timeout=30) as client:
            files = {
                "json": ("payload.json", json_str, "application/json"),
            }
            for fp in file_paths:
                path = Path(fp)
                if path.is_file():
                    files[f"file_{path.name}"] = (path.name, path.read_bytes(), "application/octet-stream")

            response = await client.post(url, files=files)
            response.raise_for_status()

        logger.info("webhook.sent", url=url, status_code=response.status_code)
    except Exception as exc:
        logger.error("webhook.failed", url=url, error=str(exc))
