import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.permissions import load_member_exception
from app.db import get_db
from app.models import Resolution, User
from app.reconciliation.resolution import transition
from app.routers.reconciliation_results import exception_item
from app.schemas.reconciliation_results import ExceptionItem
from app.schemas.resolutions import NoteRequest, OptionalNoteRequest, ResolutionOut

router = APIRouter(
    prefix="/api/v1/exceptions",
    tags=["exceptions"],
    dependencies=[Depends(get_current_user)],
)


def _decide(
    decision: str,
    exception_id: uuid.UUID,
    body: NoteRequest | OptionalNoteRequest,
    user: User,
    db: Session,
) -> ExceptionItem:
    exception, membership = load_member_exception(db, user, exception_id)
    transition(
        db,
        decision=decision,
        exception=exception,
        membership=membership,
        user=user,
        version=body.version,
        note=body.note,
    )
    return exception_item(exception)


@router.post(
    "/{exception_id}/propose",
    response_model=ExceptionItem,
    dependencies=[Depends(require_csrf)],
)
def propose_exception(
    exception_id: uuid.UUID,
    body: NoteRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return _decide("propose", exception_id, body, user, db)


@router.post(
    "/{exception_id}/approve",
    response_model=ExceptionItem,
    dependencies=[Depends(require_csrf)],
)
def approve_exception(
    exception_id: uuid.UUID,
    body: OptionalNoteRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return _decide("approve", exception_id, body, user, db)


@router.post(
    "/{exception_id}/reject",
    response_model=ExceptionItem,
    dependencies=[Depends(require_csrf)],
)
def reject_exception(
    exception_id: uuid.UUID,
    body: NoteRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return _decide("reject", exception_id, body, user, db)


@router.post(
    "/{exception_id}/reopen",
    response_model=ExceptionItem,
    dependencies=[Depends(require_csrf)],
)
def reopen_exception(
    exception_id: uuid.UUID,
    body: NoteRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return _decide("reopen", exception_id, body, user, db)


@router.get("/{exception_id}/history", response_model=list[ResolutionOut])
def exception_history(
    exception_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    load_member_exception(db, user, exception_id)
    rows = db.execute(
        select(Resolution, User.email)
        .outerjoin(User, User.id == Resolution.actor_user_id)
        .where(Resolution.exception_id == exception_id)
        .order_by(Resolution.created_at, Resolution.id)
    ).all()
    return [
        ResolutionOut(
            decision=resolution.decision,
            note=resolution.note,
            actor_email=email,
            exception_version=resolution.exception_version,
            created_at=resolution.created_at,
        )
        for resolution, email in rows
    ]
