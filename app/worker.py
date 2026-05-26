import asyncio
import json
import shutil
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.pipelines.classify import classify
from app.pipelines.extract import extract
from app.pipelines.qualify import qualify
from app.schemas.pipeline import (
    ExtractionResult,
    QualificationResult,
    Scoring,
    WebhookPayload,
)
from app.schemas.pipeline import EndUser

logger = get_logger(__name__)


async def handle_task(task: dict) -> None:
    task_id: str = task["task_id"]
    meta: dict = task["meta"]
    body: dict = task["body"]
    file_paths: list[str] = task.get("file_paths", [])

    subject = meta.get("subject", "")
    body_text = body.get("text")
    body_html = body.get("html")
    message_id = meta.get("message_id", "unknown")

    log = logger.bind(task_id=task_id, message_id=message_id)

    # ── Stage 1: Classification ──
    log.info("pipeline.started", stage="classification")
    try:
        classification = await classify(subject, body_text, body_html)
    except Exception as exc:
        log.error("pipeline.failed", stage="classification", error=str(exc))
        return

    if classification.category.value != "new_request":
        log.info(
            "pipeline.skipped",
            stage="classification",
            reason=f"category={classification.category.value}",
            notes=classification.notes,
        )
        _cleanup_files(file_paths)
        return

    log.info("pipeline.passed", stage="classification", category=classification.category.value)

    # ── Stage 2: Qualification ──
    log.info("pipeline.started", stage="qualification")
    try:
        qualification: QualificationResult = await qualify(subject, body_text, body_html)
    except Exception as exc:
        log.error("pipeline.failed", stage="qualification", error=str(exc))
        return

    if qualification.verdict.value == "неберем":
        log.info(
            "pipeline.skipped",
            stage="qualification",
            reason=f"verdict={qualification.verdict.value}",
            rationale=qualification.verdict_rationale,
        )
        _cleanup_files(file_paths)
        return

    log.info(
        "pipeline.passed",
        stage="qualification",
        verdict=qualification.verdict.value,
        pros=qualification.pros,
        cons=qualification.cons,
    )

    # ── Stage 3: Extraction ──
    log.info("pipeline.started", stage="extraction")
    try:
        extraction: ExtractionResult = await extract(subject, body_text, body_html)
    except Exception as exc:
        log.error("pipeline.failed", stage="extraction", error=str(exc))
        return

    validation_errors = extraction.validate_required()
    if validation_errors:
        log.warning("pipeline.validation_errors", errors=validation_errors)

    log.info("pipeline.passed", stage="extraction", title=extraction.title)

    # ── Send webhook ──
    missing_title = extraction.title or "Без названия"
    payload = WebhookPayload(
        title=missing_title,
        request_type=extraction.request_type.value if extraction.request_type else "contest",
        activity_direction=extraction.activity_direction.value if extraction.activity_direction else "SP",
        description=extraction.description or "",
        end_user=EndUser(
            inn=extraction.end_user.inn if extraction.end_user else None,
            name=extraction.end_user.name if extraction.end_user else None,
        ),
        source="email",
        lot_number=extraction.lot_number or "",
        tkp_deadline=extraction.tkp_deadline or "",
        tender_files_url=_build_files_url(task_id, file_paths),
        scoring=Scoring(
            pros=qualification.pros,
            cons=qualification.cons,
        ),
    )

    await _send_webhook(payload, file_paths, task_id, log)

    _cleanup_files(file_paths)
    log.info("pipeline.completed", task_id=task_id)


def _build_files_url(task_id: str, file_paths: list[str]) -> str:
    if not file_paths:
        return ""
    return f"/uploads/{task_id}"


def _cleanup_files(file_paths: list[str]) -> None:
    for fp in file_paths:
        try:
            p = Path(fp)
            if p.is_file():
                p.unlink(missing_ok=True)
        except Exception:
            pass

    if file_paths:
        task_dir = Path(file_paths[0]).parent
        try:
            if task_dir.is_dir() and not any(task_dir.iterdir()):
                shutil.rmtree(task_dir, ignore_errors=True)
        except Exception:
            pass


async def _send_webhook(payload: WebhookPayload, file_paths: list[str], task_id: str, log) -> None:
    webhook_url = settings.webhook_url
    if not webhook_url:
        log.warning("webhook.no_url_configured")
        return

    start = time.monotonic()
    try:
        payload_dict = payload.model_dump()
        async with httpx.AsyncClient(timeout=30) as client:
            files = {
                "json": ("payload.json", json.dumps(payload_dict, ensure_ascii=False), "application/json"),
            }
            for fp in file_paths:
                path = Path(fp)
                if path.is_file():
                    files[f"file_{path.name}"] = (path.name, path.read_bytes(), "application/octet-stream")

            response = await client.post(webhook_url, files=files)
            response.raise_for_status()

        duration = int((time.monotonic() - start) * 1000)
        log.info(
            "webhook.sent",
            status_code=response.status_code,
            duration_ms=duration,
        )
    except Exception as exc:
        log.error("webhook.failed", error=str(exc))


async def run_worker() -> None:
    from app.core.kafka import start_consumer

    logger.info("worker.starting")
    await start_consumer(handle_task)


if __name__ == "__main__":
    asyncio.run(run_worker())
