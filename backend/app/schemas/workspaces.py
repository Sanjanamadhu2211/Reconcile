import uuid

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    timestamp_tolerance_hours: int = Field(default=24, gt=0)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timestamp_tolerance_hours: int | None = Field(default=None, gt=0)


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    timestamp_tolerance_hours: int
