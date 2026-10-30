import hmac
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.cookies import (
    OAUTH_TX_COOKIE,
    clear_oauth_tx_cookie,
    secure_cookies,
    set_auth_cookies,
    set_oauth_tx_cookie,
)
from app.auth.google import (
    GoogleLoginError,
    GoogleProvider,
    LoginTransaction,
    code_challenge,
    get_google_provider,
    new_code_verifier,
    open_transaction,
    seal_transaction,
    validate_claims,
)
from app.auth.linking import resolve_user
from app.auth.sessions import create_session
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def enabled_google_provider(
    provider: Annotated[GoogleProvider, Depends(get_google_provider)],
) -> GoogleProvider:
    if not provider.enabled:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    return provider


@router.get("/providers")
def providers(provider: Annotated[GoogleProvider, Depends(get_google_provider)]):
    return {"google": provider.enabled}


@router.get("/google/login")
def google_login(provider: Annotated[GoogleProvider, Depends(enabled_google_provider)]):
    transaction = LoginTransaction(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=new_code_verifier(),
    )
    url = provider.authorization_url(
        transaction.state, transaction.nonce, code_challenge(transaction.code_verifier)
    )
    response = RedirectResponse(url, status_code=302)
    set_oauth_tx_cookie(
        response, seal_transaction(transaction, int(time.time())), secure=secure_cookies()
    )
    return response


@router.get("/google/callback")
async def google_callback(
    db: Annotated[Session, Depends(get_db)],
    provider: Annotated[GoogleProvider, Depends(enabled_google_provider)],
    oauth_tx: Annotated[str | None, Cookie(alias=OAUTH_TX_COOKIE)] = None,
    code: str | None = None,
    state: str | None = None,
):
    now = int(time.time())
    try:
        transaction = open_transaction(oauth_tx, now) if oauth_tx else None
        if transaction is None or not state:
            raise GoogleLoginError("invalid_state")
        if not hmac.compare_digest(state.encode(), transaction.state.encode()):
            raise GoogleLoginError("invalid_state")
        if not code:
            raise GoogleLoginError("provider_error")
        claims = await provider.fetch_claims(code, transaction.code_verifier)
        identity = validate_claims(
            claims, client_id=provider.client_id, nonce=transaction.nonce, now=now
        )
        user = resolve_user(db, identity.sub, identity.email)
    except GoogleLoginError as error:
        response = RedirectResponse(
            f"{get_settings().web_origin}/login?error=google_{error.code}", status_code=302
        )
        clear_oauth_tx_cookie(response, secure=secure_cookies())
        return response

    response = RedirectResponse(f"{get_settings().web_origin}/", status_code=302)
    set_auth_cookies(response, create_session(db, user), secure=secure_cookies())
    clear_oauth_tx_cookie(response, secure=secure_cookies())
    return response
