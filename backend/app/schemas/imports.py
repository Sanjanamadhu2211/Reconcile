import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    source_name: str
    filename: str | None
    status: str
    rows_total: int
    rows_processed: int
    rows_failed: int
    error_summary: str | None
    started_at: datetime | None
    updated_at: datetime
    created_at: datetime


class ImportErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    validation_status: str
    error_code: str | None
    error_detail: str | None


class ImportPreviewOut(BaseModel):
    source_name: str
    headers_found: list[str]
    headers_required: list[str]
    valid_rows: int
    invalid_rows: int
    problems: list[ImportErrorOut]
