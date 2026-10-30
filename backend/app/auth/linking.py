from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.google import GoogleLoginError
from app.models import User


def resolve_user(db: Session, sub: str, email: str) -> User:
    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        # validate_claims only lets verified emails reach this lookup
        user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        user = User(email=email, google_sub=sub)
        db.add(user)
    elif user.google_sub is None:
        user.google_sub = sub
    elif user.google_sub != sub:
        raise GoogleLoginError("account_conflict")

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise GoogleLoginError("account_conflict") from None
    return user
