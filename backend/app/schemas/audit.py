import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_email: str
    action: str
    target_type: str
    target_id: uuid.UUID
    metadata: dict[str, Any] = Field(validation_alias="event_metadata")
    created_at: datetime
