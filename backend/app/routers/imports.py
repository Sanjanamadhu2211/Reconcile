import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.permissions import load_member_workspace
from app.auth.rate_limit import rate_limit
from app.config import get_settings
from app.db import get_db, get_session_factory
from app.imports import (
    VALID_SOURCE_NAMES,
    BatchBusy,
    HeaderError,
    IdempotencyConflict,
    ImportFileError,
    check_size,
    create_or_get_batch,
    get_layout,
    process_batch,
    read_header,
    read_rows,
    validate_headers,
)
from app.models import ImportBatch, ImportRow, OrganizationMembership, User
from app.pagination import Limit, Offset
from app.schemas.imports import ImportBatchOut, ImportErrorOut, ImportPreviewOut

PREVIEW_PROBLEM_LIMIT = 20

router = APIRouter(
    prefix="/api/v1",
    tags=["imports"],
    dependencies=[Depends(get_current_user)],
)

UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["source_name", "file"],
                    "properties": {
                        "source_name": {"type": "string", "enum": sorted(VALID_SOURCE_NAMES)},
                        "file": {"type": "string", "format": "binary"},
                    },
                }
            }
        },
    }
}


def reject_oversized_upload(request: Request) -> None:
    # Runs before the multipart body is read, so an oversized upload is never spooled
    declared = int(request.headers.get("content-length", 0))
    try:
        check_size(declared, get_settings().max_upload_mb)
    except ImportFileError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None


async def _read_upload(request: Request) -> tuple[str, UploadFile]:
    form = await request.form()
    source_name, upload = form.get("source_name"), form.get("file")
    if source_name not in VALID_SOURCE_NAMES or not isinstance(upload, UploadFile):
        raise HTTPException(
            status_code=422,
            detail="Send source_name (orders, payments, refunds, settlements or fees) and a file",
        )
    return source_name, upload


def _batch_out(batch: ImportBatch) -> dict:
    return ImportBatchOut.model_validate(batch).model_dump(mode="json")


def _member_batch(db: Session, user: User, import_id: uuid.UUID) -> ImportBatch:
    batch = db.scalar(
        select(ImportBatch)
        .join(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == ImportBatch.organization_id,
                OrganizationMembership.user_id == user.id,
            ),
        )
        .where(ImportBatch.id == import_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return batch


def _process(db: Session, user: User, batch: ImportBatch, stream) -> ImportBatch:
    batch_id = batch.id
    try:
        return process_batch(
            get_session_factory(),
            batch_id,
            stream,
            max_rows=get_settings().max_import_rows,
            actor=user,
        )
    except ImportFileError as exc:
        db.refresh(batch)
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "batch": _batch_out(batch)}
        ) from None
    except BatchBusy as exc:
        raise HTTPException(
            status_code=409, detail={"message": str(exc), "batch_id": str(batch_id)}
        ) from None


def _store_upload(
    db: Session,
    user: User,
    workspace_id: uuid.UUID,
    source_name: str,
    upload: UploadFile,
    idempotency_key: str | None,
) -> tuple[ImportBatch, bool]:
    workspace, _ = load_member_workspace(db, user, workspace_id)
    try:
        batch, created = create_or_get_batch(
            db,
            user=user,
            workspace=workspace,
            source_name=source_name,
            filename=upload.filename,
            stream=upload.file,
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ImportFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if batch.status != "completed":
        batch = _process(db, user, batch, upload.file)
    return batch, created


def _preview(
    db: Session,
    user: User,
    workspace_id: uuid.UUID,
    source_name: str,
    stream,
) -> ImportPreviewOut:
    load_member_workspace(db, user, workspace_id)
    required = sorted(get_layout(source_name).required_headers)
    try:
        headers = read_header(stream)
        validate_headers(headers, source_name)
        valid = invalid = 0
        problems: list[ImportErrorOut] = []
        for row in read_rows(stream, source_name, max_rows=get_settings().max_import_rows):
            if row.status == "VALID":
                valid += 1
                continue
            invalid += 1
            if len(problems) < PREVIEW_PROBLEM_LIMIT:
                problems.append(
                    ImportErrorOut(
                        row_number=row.row_number,
                        validation_status=row.status,
                        error_code=row.error_code,
                        error_detail=row.error_detail,
                    )
                )
    except HeaderError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "headers_found": headers,
                "headers_required": required,
            },
        ) from None
    except ImportFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ImportPreviewOut(
        source_name=source_name,
        headers_found=headers,
        headers_required=required,
        valid_rows=valid,
        invalid_rows=invalid,
        problems=problems,
    )


@router.post(
    "/workspaces/{workspace_id}/imports",
    status_code=201,
    response_model=ImportBatchOut,
    dependencies=[
        Depends(require_csrf),
        Depends(reject_oversized_upload),
        Depends(rate_limit("import", 20, 60)),
    ],
    openapi_extra=UPLOAD_BODY,
)
async def upload_import(
    workspace_id: uuid.UUID,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    source_name, upload = await _read_upload(request)
    batch, created = await run_in_threadpool(
        _store_upload, db, user, workspace_id, source_name, upload, idempotency_key
    )
    response.status_code = 201 if created else 200
    return batch


@router.post(
    "/workspaces/{workspace_id}/imports/preview",
    response_model=ImportPreviewOut,
    dependencies=[
        Depends(require_csrf),
        Depends(reject_oversized_upload),
        Depends(rate_limit("import", 20, 60)),
    ],
    openapi_extra=UPLOAD_BODY,
)
async def preview_import(
    workspace_id: uuid.UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    source_name, upload = await _read_upload(request)
    return await run_in_threadpool(_preview, db, user, workspace_id, source_name, upload.file)


@router.get("/workspaces/{workspace_id}/imports", response_model=list[ImportBatchOut])
def list_imports(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
):
    load_member_workspace(db, user, workspace_id)
    return db.scalars(
        select(ImportBatch)
        .where(ImportBatch.workspace_id == workspace_id)
        .order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/imports/{import_id}", response_model=ImportBatchOut)
def get_import(
    import_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return _member_batch(db, user, import_id)


@router.get("/imports/{import_id}/errors", response_model=list[ImportErrorOut])
def list_import_errors(
    import_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
):
    batch = _member_batch(db, user, import_id)
    return db.scalars(
        select(ImportRow)
        .where(ImportRow.import_batch_id == batch.id, ImportRow.validation_status != "VALID")
        .order_by(ImportRow.row_number)
        .limit(limit)
        .offset(offset)
    ).all()
