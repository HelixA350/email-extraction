import json
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import List, Literal, Optional
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


# --- Pydantic-схема бизнес-анализа и скоринга ---

class VerdictEnum(str, Enum):
    APPROVE = "берем"
    REJECT = "неберем"
    UNCERTAIN = "непонятно"


class ProfileAnalysis(BaseModel):
    is_matching: bool = Field(
        ..., 
        description="Соответствует ли профилю компании (нефтегаз, энергетика, горно-рудная промышленность: насосы, компрессоры, арматура, турбины, редукторы и т.д.)"
    )
    context_notes: str = Field(
        ..., 
        description="Краткий анализ профиля: какие ключевые слова найдены, либо почему по контексту это относится/не относится к целевым отраслям."
    )


class CustomerReliability(BaseModel):
    company_name: Optional[str] = Field(None, description="Название организации-заказчика, если удалось извлечь")
    inn: Optional[str] = Field(None, description="ИНН организации-заказчика, если указан")
    is_subsidiary_or_connected: bool = Field(
        ..., 
        description="Является ли заказчик дочерней структурой или связанной компанией с крупными надежными холдингами (Газпром, Роснефть, Лукойл, Росатом, РЖД, Ростех, ТНК, Транснефть и др.)"
    )
    reliability_notes: str = Field(
        ..., 
        description="Анализ надежности. Например: 'Компания создана в 2024 году, но является дочкой Роснефти, поэтому надежна' или 'Создана давно, есть ИНН' или 'Новая компания без связей, высокий риск'."
    )


class FinancialAndGeoAnalysis(BaseModel):
    extracted_amount: Optional[float] = Field(
        None, 
        description="Явно указанная сумма контракта в рублях. Если в тексте цены нет — null."
    )
    implied_scale: Literal["крупный (миллионы)", "мелкий (<500к)", "средний", "неизвестно"] = Field(
        ..., 
        description="Косвенная оценка масштаба, ЕСЛИ цена не указана. Крупные агрегаты, турбины, капремонт ТЭЦ — это почти всегда миллионы (крупный), даже если цена не написана в лоб."
    )
    is_geo_acceptable: bool = Field(
        ..., 
        description="Приемлема ли география (европейская часть РФ — всегда True; удаленные регионы — True только если масштаб контракта крупный/миллионный, иначе False)."
    )


class TenderExtraction(BaseModel):
    """
    Чистая схема оценки тендерной заявки на основе профиля, надежности и финансов.
    """
    # 1. Промежуточный глубокий бизнес-анализ (Chain of Thought для ИИ)
    profile_assessment: ProfileAnalysis = Field(..., description="Анализ соответствия профилю деятельности завода")
    customer_assessment: CustomerReliability = Field(..., description="Анализ надежности и структуры владения заказчика")
    finance_and_geo_assessment: FinancialAndGeoAnalysis = Field(..., description="Анализ денег и локации")

    # 2. Итоговая аргументация
    pros: List[str] = Field(..., description="Плюсы тендера (аргументы ЗА участие). Минимум 1 пункт.")
    cons: List[str] = Field(..., description="Минусы и риски тендера (аргументы ПРОТИВ участия). Минимум 1 пункт.")
    
    # 3. Финальное решение
    verdict: VerdictEnum = Field(
        ..., 
        description=(
            "Итоговое решение. ПРАВИЛО ДЛЯ 'непонятно': используй только при критическом отсутствии данных (например, пустое письмо). "
            "Если цена не указана, но профиль наш и заказчик крупный (или дочка гиганта) -> ставь 'берем'. "
            "Если цена не указана, но это мелкий ремонт в удаленном регионе для неизвестного ООО -> ставь 'неберем'. "
            "Если цена явно указана и она менее 500 000 руб -> строго 'неберем' (нерентабельно)."
        )
    )
    verdict_rationale: str = Field(..., description="Краткое объяснение логики вердикта в 1-2 sentences.")


# Настройка LLM и нового системного промпта
llm = ChatOpenAI(
    api_key="sk-ap-gdRncSF3YchRWBBvrR_bSQ", 
    base_url="https://api.agentplatform.ru/v1", 
    model="openai/gpt-5-mini", 
    temperature=0
)

system_prompt = (
    "Ты — опытный коммерческий директор завода по производство и ремонту промышленного оборудования.\n"
    "Твоя задача — извлечь данные из письма и провести жесткую бизнес-оценку целесообразности тендера.\n\n"
    "ПРАВИЛА АНАЛИЗА ДЛЯ МИНИМИЗАЦИИ ВЕРДИКТА 'непонятно':\n"
    "1. Читай между строк. Если цена прямо не указана, оценивай масштаб по косвенным признакам (капремонт турбины, поставка компрессоров, насосных станций, крупных узлов — это проекты на миллионы рублей, то есть масштаб 'крупный').\n"
    "2. Анализируй связи компаний. Мелкое или новое ООО (созданное в 2024-2025 гг.) может быть дочерней структурой Газпрома, Роснефти, Лукойла, Росатома, РЖД, Ростеха или Транснефти. Если связь есть — этот заказчик считается надежным.\n"
    "3. География: Европейская часть РФ в приоритете. Удаленные регионы берем только ради крупных бюджетов (миллионы рублей).\n"
    "4. Выдавай вердикт 'непонятно' только в крайнем случае, когда данных нет совсем. Старайся принять взвешенное бизнес-решение ('берем' или 'неберем') на основе совокупности факторов."
)

chain = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
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
    
    try:
        result: TenderExtraction = chain.invoke({"subject": subject, "body": body})
        
        # Информативный лог в консоль
        client_name = result.customer_assessment.company_name or "Неизвестный заказчик"
        print(f"[{idx}/{total}] ✓ {client_name} | Вердикт: {result.verdict.value.upper()} | Обоснование: {result.verdict_rationale}")
        
        with lock:
            email["review"] = result.model_dump()
            save()
    except Exception as e:
        print(f"[{idx}/{total}] ✗ Ошибка обработки: {e}")

with ThreadPoolExecutor(max_workers=4) as pool:
    pool.map(process, enumerate(new_requests, 1))

print("Готово.")