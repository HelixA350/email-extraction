import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.core.prompts import read_prompt
from app.pipelines.utils import html_to_text, normalize_intro, resolve_llm
from app.schemas.pipeline import ExtractionResult

logger = get_logger(__name__)


def _load_prompt() -> ChatPromptTemplate:
    template = read_prompt("extract")
    return ChatPromptTemplate.from_messages([
        ("system", template),
        ("user", "Тема: {subject}\nСодержание: {body}"),
    ])


def _build_chain():
    llm: BaseChatModel = resolve_llm().with_structured_output(ExtractionResult)
    prompt = _load_prompt()
    return prompt | llm


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)
async def extract(subject: str, body_text: str | None, body_html: str | None) -> ExtractionResult:
    start = time.monotonic()
    raw_text = body_text or ""
    if not raw_text and body_html:
        raw_text = html_to_text(body_html)
    body = normalize_intro(raw_text)

    chain = _build_chain()
    result: ExtractionResult = await chain.ainvoke({"subject": subject, "body": body})

    duration = int((time.monotonic() - start) * 1000)
    logger.info(
        "extraction.complete",
        title=result.title,
        request_type=result.request_type.value if result.request_type else None,
        activity_direction=result.activity_direction.value if result.activity_direction else None,
        duration_ms=duration,
    )

    validation_errors = result.validate_required()
    if validation_errors:
        logger.warning("extraction.validation_errors", errors=validation_errors)

    return result
