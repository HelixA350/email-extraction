import json

import threading

from concurrent.futures import ThreadPoolExecutor

from typing import Literal, Optional

from bs4 import BeautifulSoup

from pydantic import BaseModel, Field

from langchain_openai import ChatOpenAI

from langchain_core.prompts import ChatPromptTemplate





def html_to_text(html: str) -> str:

    if not html:

        return ""

    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)



def normalize_intro(text: str) -> str:

    return " ".join(text.split()) if text else ""





class EndUser(BaseModel):

    inn: Optional[str] = Field(None, description="ИНН организации-заказчика")

    name: Optional[str] = Field(None, description="Название организации-заказчика")





class TenderExtraction(BaseModel):

    request_type: Optional[Literal["contest", "survey"]] = Field(

        None, description="contest = конкурс, survey = опрос рынка"

    )

    activity_direction: Optional[Literal["SP", "S"]] = Field(

        None, description="SP = закупка, S = сервис/услуги"

    )

    description: Optional[str] = Field(None, description="Краткое описание закупки в одну строку")

    end_user: Optional[EndUser] = Field(None, description="Организация-заказчик")

    lot_number: Optional[str] = Field(None, description="Номер лота если указан")

    tkp_deadline: Optional[str] = Field(None, description="Срок подачи предложения YYYY-MM-DD")

    title: Optional[str] = Field(None, description="Название тендера")





llm = ChatOpenAI(api_key="sk-ap-gdRncSF3YchRWBBvrR_bSQ", base_url="https://api.agentplatform.ru/v1", model="openai/gpt-5-mini", temperature=0)

chain = ChatPromptTemplate.from_messages([

    ("system", "Ты извлекаешь структурированные данные из тендерных писем. Отвечай строго по схеме. Старайся извлечь все поля. Запрещено выдумывать информацию, отвечай строго по содержанию письма"),

    ("user", "Тема: {subject}\n\nСодержание:\n{body}"),

]) | llm.with_structured_output(TenderExtraction)





DATA_PATH = "classified.jsonl"



emails = []

with open(DATA_PATH, "r", encoding="utf-8") as f:

    for line in f:

        if line.strip():

            emails.append(json.loads(line))



new_requests = [e for e in emails if e.get("classification", {}).get("category") == "new_request"]

total = len(new_requests)

print(f"Найдено new_request: {total}")



lock = threading.Lock()



def save():

    with open(DATA_PATH, "w", encoding="utf-8") as f:

        for e in emails:

            f.write(json.dumps(e, ensure_ascii=False) + "\n")



def process(args):

    idx, email = args

    subject = email.get("subject", "")

    body = normalize_intro(html_to_text(email.get("html", "") or email.get("text", "")))

    print(f"[{idx}/{total}] {subject[:60]}...")

    result: TenderExtraction = chain.invoke({"subject": subject, "body": body})

    print(f"[{idx}/{total}] ✓ {result.title} | {result.request_type} | {result.activity_direction}")

    with lock:

        email["review"] = result.model_dump()

        save()



with ThreadPoolExecutor(max_workers=4) as pool:

    pool.map(process, enumerate(new_requests, 1))



print("Готово.") 

