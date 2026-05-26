from langchain_openai import ChatOpenAI

from app.core.config import settings


def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def normalize_intro(text: str, limit: int | None = None) -> str:
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if limit:
        return collapsed[:limit]
    return collapsed


def resolve_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        temperature=0,
    )
