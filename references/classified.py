import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pandas as pd
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


API_TOKEN = "sk-1aoPVcR8oLEcVfQimu2dKQ"
BASE_URL = "https://api.agentplatform.ru/v1"
MODEL = "openai/gpt-5-mini"

DATA_PATH = Path("data.jsonl")
OUTPUT_PATH = Path("classified2.jsonl")


class ClassificationResult(BaseModel):
    category: Literal["new_request", "other"]
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str


def read_sample(path: Path, sample_size: int = 400) -> list[dict]:
    with path.open("r", encoding="utf-8") as fp:
        rows = [json.loads(line) for line in fp]
    random.seed(42)
    return random.sample(rows, k=min(sample_size, len(rows)))


def html_to_text(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is None:
        return html
    # strip=True удаляет пробелы по краям, но не внутри
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

def normalize_intro(text: str, limit: int = 250) -> str:
    if not text:
        return ""
    # Схлопываем любые последовательности пробелов в один пробел
    collapsed = " ".join(text.split())
    # Теперь обрезаем
    return collapsed[:limit]

def build_prompt() -> PromptTemplate:
    template = (
        "Ты классифицируешь письма. Нужно решить, это новое приглашение к участию в тендере/опросе или нет.\n"
        "Ответ выведи строго в JSON, соответствующий ожидаемой схеме.\n\n"
        "Примеры: \n"
        "1) Тема: Опубликован тендер ПАО «ЛУКОЙЛ»\n"
        "   Текст: Опубликован тендер № A10-0065-26 — Поставка герметичных насосов.\n"
        "   Ответ: category=new_request\n"
        "2) Тема: Изменены условия процедуры №4338976\n"
        "   Текст: Изменены условия проведения конкурентной процедуры...\n"
        "   Ответ: category=other\n"
        "3) Тема: ЦЗ по вашей сфере деятельности за 07.03.2026\n"
        "   Текст: Сводное письмо с подборкой запросов.\n"
        "   Ответ: category=other\n\n"
        "Тема письма: {subject}\n"
        "Начало письма: {body_intro}"
    )

    return PromptTemplate(
        input_variables=["subject", "body_intro"],
        template=template,
    )


def setup_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=API_TOKEN,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0,
    )


def classify_items(rows: list[dict], output_path: Path) -> list[dict]:
    prompt = build_prompt()
    llm = setup_llm().with_structured_output(ClassificationResult)

    with output_path.open("w", encoding="utf-8") as out_fp:
        lock = __import__("threading").Lock()

        def worker(item: dict) -> dict:
            subject = item.get("subject", "") or ""
            raw_text = item.get("text")
            if not raw_text:
                raw_text = html_to_text(item.get("html", ""))
            body_intro = normalize_intro(raw_text)
            try:
                parsed = llm.invoke(prompt.format(subject=subject, body_intro=body_intro))
                print("успешно обработали тендер")
            except Exception as exc:
                parsed = ClassificationResult(
                    category="other", confidence=0.0, notes=f"llm_error: {exc}"
                )
                print("ошибка при вызове llm")
            result = {**item, "classification": parsed.dict()}
            with lock:
                out_fp.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_fp.flush()
            return result

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(worker, rows))

    return results


def write_output(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    sampled_rows = read_sample(DATA_PATH)
    preview = random.sample(sampled_rows, k=min(10, len(sampled_rows)))
    prompt = build_prompt()
    print("Preview of messages sent to the model:\n")
    for idx, item in enumerate(preview, 1):
        subject = item.get("subject", "") or ""
        raw_text = item.get("text")
        if not raw_text:
            raw_text = html_to_text(item.get("html", ""))
        else:
            raw_text = raw_text + "\n" + html_to_text(item.get("html", ""))
        body_intro = normalize_intro(raw_text)
        formatted = prompt.format(subject=subject, body_intro=body_intro)
        print(f"Example {idx}:\n{formatted}\n")

    classified = classify_items(sampled_rows, OUTPUT_PATH)
    print(pd.DataFrame(classified).head())


if __name__ == "__main__":
    main()
