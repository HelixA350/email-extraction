import time

from langchain_core.prompts import PromptTemplate
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
from app.schemas.pipeline import ClassificationResult

logger = get_logger(__name__)


def _load_prompt() -> PromptTemplate:
    template = read_prompt("classify")
    return PromptTemplate(input_variables=["subject", "body_intro"], template=template)


def _build_chain():
    llm: BaseChatModel = resolve_llm().with_structured_output(ClassificationResult)
    prompt = _load_prompt()
    return prompt | llm


@retry(
    stop=stop_after_attempt(settings.max_retries),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)
async def classify(subject: str, body_text: str | None, body_html: str | None) -> ClassificationResult:
    start = time.monotonic()
    raw_text = body_text or ""
    if not raw_text and body_html:
        raw_text = html_to_text(body_html)
    body_intro = normalize_intro(raw_text, limit=250)

    chain = _build_chain()
    result: ClassificationResult = await chain.ainvoke({"subject": subject, "body_intro": body_intro})

    duration = int((time.monotonic() - start) * 1000)
    logger.info(
        "classification.complete",
        category=result.category.value,
        confidence=result.confidence,
        duration_ms=duration,
    )
    return result
