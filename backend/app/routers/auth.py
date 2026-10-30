from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.cookies import (
    SESSION_COOKIE,
    clear_auth_cookies,
    secure_cookies,
    set_auth_cookies,
)
from app.auth.csrf import require_csrf
from app.auth.dependencies import get_current_user
from app.auth.passwords import hash_password, verify_password
from app.auth.rate_limit import login_limiter
from app.auth.sessions import create_session, delete_session
from app.db import get_db
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=UserOut)
def register(
    body: RegisterRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from None

    set_auth_cookies(response, create_session(db, user), secure=secure_cookies())
    return user


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    client_ip = request.client.host if request.client else "unknown"
    key = (client_ip, body.email.lower())
    if login_limiter.is_blocked(key):
        raise HTTPException(
            status_code=429, detail="Too many failed sign-in attempts, try again later"
        )

    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok:
        login_limiter.record_failure(key)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    set_auth_cookies(response, create_session(db, user), secure=secure_cookies())
    return user


@router.post("/logout", dependencies=[Depends(get_current_user), Depends(require_csrf)])
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    if session_token:
        delete_session(db, session_token)
    clear_auth_cookies(response, secure=secure_cookies())
    return {}


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]):
    return user
