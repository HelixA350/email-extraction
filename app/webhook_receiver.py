import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

app = FastAPI(title="Webhook Receiver")

received: list[dict] = []


@app.get("/")
async def list_webhooks():
    return JSONResponse(content={"received": len(received), "webhooks": received[-10:]})


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    source = request.client.host if request.client else "unknown"
    logger.info("webhook.received", payload=body, source=source)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": body,
        "source": source,
    }
    received.append(entry)
    return {"status": "ok"}


@app.post("/webhook-files")
async def receive_webhook_with_files(request: Request):
    form = await request.form()
    source = request.client.host if request.client else "unknown"

    form_keys = list(form.keys())
    logger.info("webhook.form_fields", keys=form_keys, source=source)

    json_part = form.get("json")
    if hasattr(json_part, "read"):
        raw = await json_part.read()
        logger.debug("webhook.json_raw", size=len(raw), preview=raw[:200])
        payload = json.loads(raw) if raw else {}
    elif isinstance(json_part, str):
        payload = json.loads(json_part) if json_part else {}
    else:
        logger.warning("webhook.json_missing", type=type(json_part).__name__ if json_part else "None")
        payload = {}

    raw_files = form.getlist("files")
    filenames = [f.filename for f in raw_files if hasattr(f, "read") and f.filename]

    logger.info("webhook.received_with_files", payload=payload, files=filenames, source=source)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "files": filenames,
        "source": source,
    }
    received.append(entry)

    return JSONResponse(content={"status": "ok", "id": len(received)})
