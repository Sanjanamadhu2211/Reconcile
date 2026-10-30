import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import User, UserSession

SESSION_LIFETIME = timedelta(days=7)
LAST_SEEN_INTERVAL = timedelta(minutes=1)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        UserSession(
            token_hash=_digest(token),
            user_id=user.id,
            last_seen_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    db.commit()
    return token


def get_session_user(db: Session, token: str) -> User | None:
    row = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == _digest(token))
    ).first()
    if row is None:
        return None

    session, user = row
    now = datetime.now(UTC)
    if session.expires_at <= now:
        return None
    if now - session.last_seen_at >= LAST_SEEN_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return user


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))
    db.commit()
