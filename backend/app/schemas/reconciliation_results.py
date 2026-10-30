import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TransactionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_name: str
    external_id: str
    amount: str  # decimal string with 4 places
    currency: str
    occurred_at: datetime


class ReconciliationRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    rule_version: str
    tolerance_hours: int
    matches_count: int
    exceptions_count: int
    started_at: datetime | None
    completed_at: datetime | None


class MatchItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule: str
    left_transaction: TransactionSummary
    right_transaction: TransactionSummary


class ExceptionTransactionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_name: str
    external_id: str
    amount: str
    currency: str
    occurred_at: datetime


class ExceptionImportRowSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_number: int
    batch_id: uuid.UUID


class ExceptionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    status: str
    version: int
    assigned_reviewer_id: uuid.UUID | None
    details: dict | None
    transaction: ExceptionTransactionSummary | None = None
    import_row: ExceptionImportRowSummary | None = None
    reconciliation_run_id: uuid.UUID


class ReconciliationRunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    rule_version: str
    tolerance_hours: int
    matches_count: int
    exceptions_count: int
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
