import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.jose import JsonWebKey, JsonWebToken

from app.auth.cookies import OAUTH_TX_MAX_AGE
from app.config import Settings, get_settings

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPE = "openid email profile"
TIMEOUT_SECONDS = 10

_jwt = JsonWebToken(["RS256"])


class GoogleLoginError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str


@dataclass(frozen=True)
class LoginTransaction:
    state: str
    nonce: str
    code_verifier: str


class GoogleProvider:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.client_id = settings.google_client_id
        self._client_secret = settings.google_client_secret
        self._redirect_uri = settings.google_redirect_uri
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self._client_secret and self._redirect_uri)

    def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZATION_URL}?{urlencode(params)}"

    async def fetch_claims(self, code: str, code_verifier: str) -> dict:
        async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_SECONDS) as client:
            try:
                token = await client.post(
                    TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self._client_secret,
                        "redirect_uri": self._redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                )
                token.raise_for_status()
                id_token = token.json()["id_token"]
                jwks = await client.get(JWKS_URL)
                jwks.raise_for_status()
                key_set = JsonWebKey.import_key_set(jwks.json())
            except (httpx.HTTPError, KeyError, ValueError):
                raise GoogleLoginError("provider_error") from None

        try:
            return dict(_jwt.decode(id_token, key_set))
        except (AuthlibBaseError, ValueError):
            raise GoogleLoginError("invalid_token") from None


def get_google_provider() -> GoogleProvider:
    return GoogleProvider(get_settings())


def new_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return _b64(digest)


def validate_claims(claims: dict, *, client_id: str, nonce: str, now: int) -> GoogleIdentity:
    if claims.get("iss") not in ISSUERS:
        raise GoogleLoginError("invalid_token")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        raise GoogleLoginError("invalid_token")
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= now:
        raise GoogleLoginError("invalid_token")
    if claims.get("nonce") != nonce:
        raise GoogleLoginError("invalid_token")

    sub, email = claims.get("sub"), claims.get("email")
    if not (isinstance(sub, str) and sub and isinstance(email, str) and email):
        raise GoogleLoginError("invalid_token")
    if claims.get("email_verified") is not True and claims.get("email_verified") != "true":
        raise GoogleLoginError("unverified_email")
    return GoogleIdentity(sub=sub, email=email)


def seal_transaction(transaction: LoginTransaction, now: int) -> str:
    payload = {**asdict(transaction), "exp": now + OAUTH_TX_MAX_AGE}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def open_transaction(value: str, now: int) -> LoginTransaction | None:
    body, _, signature = value.partition(".")
    if not hmac.compare_digest(signature.encode(), _sign(body).encode()):
        return None
    payload = json.loads(_unb64(body))
    if payload["exp"] <= now:
        return None
    return LoginTransaction(payload["state"], payload["nonce"], payload["code_verifier"])


def _sign(body: str) -> str:
    key = get_settings().session_secret.encode()
    return _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
