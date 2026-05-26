from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EmailMeta(BaseModel):
    message_id: str = Field(..., description="Уникальный идентификатор письма")
    from_: str = Field(..., alias="from", description="Отправитель")
    to: list[str] = Field(..., description="Получатели")
    subject: str = Field(..., description="Тема письма")
    received_at: datetime = Field(..., description="Дата получения (ISO8601)")


class EmailBody(BaseModel):
    text: Optional[str] = Field(None, description="Текстовая версия письма")
    html: Optional[str] = Field(None, description="HTML-версия письма")


class EmailInput(BaseModel):
    meta: EmailMeta
    body: EmailBody
