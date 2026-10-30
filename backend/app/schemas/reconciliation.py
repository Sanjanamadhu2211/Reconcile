import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReconciliationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    rule_version: str
    status: str
    tolerance_hours: int
    matches_count: int
    exceptions_count: int
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
