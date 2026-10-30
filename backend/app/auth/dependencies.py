from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.cookies import SESSION_COOKIE
from app.auth.sessions import get_session_user
from app.db import get_db
from app.models import User


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    user = get_session_user(db, session_token) if session_token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user
