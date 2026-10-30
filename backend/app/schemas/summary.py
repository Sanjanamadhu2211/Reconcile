import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BatchCounts(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0


class RecentBatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    filename: str | None
    status: str
    rows_total: int
    rows_failed: int
    created_at: datetime


class ImportsSummary(BaseModel):
    batches_by_status: BatchCounts
    rows_imported: int
    rows_invalid: int
    recent_batches: list[RecentBatch]


class LatestRunSummary(BaseModel):
    id: uuid.UUID
    completed_at: datetime | None
    matches_count: int
    exceptions_count: int
    match_rate: str | None


class ExceptionStatusCounts(BaseModel):
    open: int = 0
    proposed: int = 0
    resolved: int = 0


class ExceptionCategoryCounts(BaseModel):
    unmatched: int = 0
    ambiguous: int = 0
    amount_mismatch: int = 0
    duplicate: int = 0


class ExceptionsSummary(BaseModel):
    by_status: ExceptionStatusCounts
    by_category: ExceptionCategoryCounts


class WorkspaceSummary(BaseModel):
    imports: ImportsSummary
    latest_run: LatestRunSummary | None
    exceptions: ExceptionsSummary
