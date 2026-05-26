from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Stage 1: Classification ──

class ClassificationCategory(str, Enum):
    new_request = "new_request"
    other = "other"


class ClassificationResult(BaseModel):
    category: ClassificationCategory = Field(..., description="Тип письма")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность модели")
    notes: str = Field(..., description="Пояснение")


# ── Stage 2: Qualification ──

class VerdictEnum(str, Enum):
    APPROVE = "берем"
    REJECT = "неберем"
    UNCERTAIN = "непонятно"


class ProfileAnalysis(BaseModel):
    is_matching: bool = Field(
        ...,
        description="Соответствует ли профилю компании (нефтегаз, энергетика, горно-рудная промышленность)",
    )
    context_notes: str = Field(..., description="Краткий анализ профиля")


class CustomerReliability(BaseModel):
    company_name: Optional[str] = Field(None, description="Название организации-заказчика")
    inn: Optional[str] = Field(None, description="ИНН организации-заказчика")
    is_subsidiary_or_connected: bool = Field(
        ...,
        description="Является ли заказчик дочерней структурой крупных холдингов",
    )
    reliability_notes: str = Field(..., description="Анализ надежности")


class FinancialAndGeoAnalysis(BaseModel):
    extracted_amount: Optional[float] = Field(None, description="Явно указанная сумма контракта в рублях")
    implied_scale: str = Field(
        ...,
        description="Косвенная оценка масштаба",
    )
    is_geo_acceptable: bool = Field(
        ...,
        description="Приемлема ли география",
    )


class QualificationResult(BaseModel):
    profile_assessment: ProfileAnalysis = Field(..., description="Анализ соответствия профилю")
    customer_assessment: CustomerReliability = Field(..., description="Анализ надежности заказчика")
    finance_and_geo_assessment: FinancialAndGeoAnalysis = Field(..., description="Анализ денег и локации")
    pros: list[str] = Field(..., description="Аргументы ЗА участие")
    cons: list[str] = Field(..., description="Аргументы ПРОТИВ участия")
    verdict: VerdictEnum = Field(..., description="Итоговое решение")
    verdict_rationale: str = Field(..., description="Объяснение вердикта")


# ── Stage 3: Extraction ──

class EndUser(BaseModel):
    inn: Optional[str] = Field(None, description="ИНН организации-заказчика")
    name: Optional[str] = Field(None, description="Название организации-заказчика")


class RequestTypeEnum(str, Enum):
    contest = "contest"
    survey = "survey"


class ActivityDirectionEnum(str, Enum):
    SP = "SP"
    S = "S"


class ExtractionResult(BaseModel):
    title: Optional[str] = Field(None, description="Название тендера")
    request_type: Optional[RequestTypeEnum] = Field(None, description="contest = конкурс, survey = опрос рынка")
    activity_direction: Optional[ActivityDirectionEnum] = Field(None, description="SP = закупка, S = сервис")
    description: Optional[str] = Field(None, description="Краткое описание закупки")
    end_user: Optional[EndUser] = Field(None, description="Организация-заказчик")
    lot_number: Optional[str] = Field(None, description="Номер лота")
    tkp_deadline: Optional[str] = Field(None, description="Срок подачи предложения YYYY-MM-DD")

    def validate_required(self) -> dict:
        errors = {}
        if not self.request_type:
            errors["request_type"] = "Обязательное поле"
        if not self.activity_direction:
            errors["activity_direction"] = "Обязательное поле"
        if not self.description:
            errors["description"] = "Обязательное поле"
        if not self.end_user or (not self.end_user.inn and not self.end_user.name):
            errors["end_user"] = "Должно быть заполнено хотя бы одно из полей inn/name"
        if not self.lot_number:
            errors["lot_number"] = "Обязательное поле"
        if not self.tkp_deadline:
            errors["tkp_deadline"] = "Обязательное поле"
        return errors


# ── Webhook payload ──

class Scoring(BaseModel):
    pros: list[str] = Field(..., description="Флаги ЗА участие")
    cons: list[str] = Field(..., description="Флаги ПРОТИВ участия")


class WebhookPayload(BaseModel):
    title: str = Field(..., description="Название тендера")
    request_type: str = Field(..., description="contest | survey")
    activity_direction: str = Field(..., description="SP | S")
    description: str = Field(..., description="Описание закупки")
    end_user: EndUser = Field(..., description="Заказчик")
    source: str = Field("email", description="Источник, всегда email")
    lot_number: str = Field(..., description="Номер лота")
    tkp_deadline: str = Field(..., description="Срок подачи YYYY-MM-DD")
    tender_files_url: str = Field(..., description="Ссылка на скачивание файлов закупки")
    scoring: Scoring = Field(..., description="Скоринг тендера")
