import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.permissions import Role, load_membership, require_role
from app.db import get_db
from app.models import Organization, OrganizationMembership, User
from app.pagination import Limit, Offset
from app.schemas.organizations import (
    MemberAdd,
    MemberOut,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationOut,
)

router = APIRouter(
    prefix="/api/v1/organizations",
    tags=["organizations"],
    dependencies=[Depends(get_current_user)],
)


def _locked_membership(
    db: Session, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[list[OrganizationMembership], OrganizationMembership]:
    # Locking every membership row makes concurrent role changes wait before they count reviewers
    members = list(
        db.scalars(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.id)
            .with_for_update()
        )
    )
    target = next((member for member in members if member.user_id == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return members, target


def _keep_a_reviewer(members: list[OrganizationMembership], target: OrganizationMembership) -> None:
    reviewers = [member for member in members if member.role == Role.reviewer]
    if target.role == Role.reviewer and len(reviewers) == 1:
        raise HTTPException(status_code=409, detail="An organization needs at least one reviewer")


@router.post(
    "",
    status_code=201,
    response_model=OrganizationOut,
    dependencies=[Depends(require_csrf)],
)
def create_organization(
    body: OrganizationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    organization = Organization(name=body.name)
    db.add(organization)
    db.flush()
    db.add(
        OrganizationMembership(user_id=user.id, organization_id=organization.id, role=Role.reviewer)
    )
    db.commit()
    return OrganizationOut(id=organization.id, name=organization.name, role=Role.reviewer)


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
):
    rows = db.execute(
        select(Organization, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
        .where(OrganizationMembership.user_id == user.id)
        .order_by(Organization.created_at, Organization.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [OrganizationOut(id=org.id, name=org.name, role=role) for org, role in rows]


@router.get("/{organization_id}/members", response_model=list[MemberOut])
def list_members(
    organization_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Limit = 50,
    offset: Offset = 0,
):
    load_membership(db, user, organization_id)
    rows = db.execute(
        select(User.id, User.email, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.created_at, OrganizationMembership.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [MemberOut(user_id=member_id, email=email, role=role) for member_id, email, role in rows]


@router.post(
    "/{organization_id}/members",
    status_code=201,
    response_model=MemberOut,
    dependencies=[Depends(require_csrf)],
)
def add_member(
    organization_id: uuid.UUID,
    body: MemberAdd,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_role(load_membership(db, user, organization_id), Role.reviewer)
    invitee = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if invitee is None:
        raise HTTPException(status_code=404, detail="No user has that email")

    db.add(
        OrganizationMembership(user_id=invitee.id, organization_id=organization_id, role=body.role)
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User is already a member") from None
    return MemberOut(user_id=invitee.id, email=invitee.email, role=body.role)


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=MemberOut,
    dependencies=[Depends(require_csrf)],
)
def change_member_role(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_role(load_membership(db, user, organization_id), Role.reviewer)
    members, target = _locked_membership(db, organization_id, user_id)
    if body.role != Role.reviewer:
        _keep_a_reviewer(members, target)
    target.role = body.role
    db.commit()
    return MemberOut(user_id=user_id, email=db.get(User, user_id).email, role=target.role)


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
)
def remove_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    require_role(load_membership(db, user, organization_id), Role.reviewer)
    members, target = _locked_membership(db, organization_id, user_id)
    _keep_a_reviewer(members, target)
    db.delete(target)
    db.commit()
