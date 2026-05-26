from datetime import datetime, timezone

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    status: str = Field("success", description="Статус обработки")
    task_id: str = Field(..., description="UUID задачи")


class HealthResponse(BaseModel):
    status: str = Field("ok", description="Состояние сервиса")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Текущее время",
    )
