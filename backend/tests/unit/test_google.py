import asyncio

import httpx
import pytest
from authlib.jose import JsonWebKey, JsonWebToken

from app.auth.google import (
    JWKS_URL,
    TOKEN_URL,
    GoogleLoginError,
    GoogleProvider,
    LoginTransaction,
    code_challenge,
    open_transaction,
    seal_transaction,
    validate_claims,
)
from app.config import Settings

NOW = 1_700_000_000
CLIENT_ID = "test-client.apps.googleusercontent.com"
NONCE = "nonce-value"


def _claims(**overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": NOW + 3600,
        "nonce": NONCE,
        "sub": "1234567890",
        "email": "person@example.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def _validate(claims):
    return validate_claims(claims, client_id=CLIENT_ID, nonce=NONCE, now=NOW)


def test_valid_claims_return_identity():
    identity = _validate(_claims())

    assert identity.sub == "1234567890"
    assert identity.email == "person@example.com"


def test_string_true_for_email_verified_is_accepted():
    assert _validate(_claims(email_verified="true")).email == "person@example.com"


@pytest.mark.parametrize("verified", [False, "false", 1, None])
def test_unverified_email_is_rejected(verified):
    with pytest.raises(GoogleLoginError) as error:
        _validate(_claims(email_verified=verified))

    assert error.value.code == "unverified_email"


def test_missing_email_verified_is_rejected():
    claims = _claims()
    del claims["email_verified"]

    with pytest.raises(GoogleLoginError) as error:
        _validate(claims)

    assert error.value.code == "unverified_email"


def test_audience_list_containing_client_id_is_accepted():
    assert _validate(_claims(aud=["other", CLIENT_ID])).sub == "1234567890"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "someone-else"},
        {"iss": "https://evil.example.com"},
        {"exp": NOW},
        {"nonce": "other-nonce"},
        {"sub": ""},
        {"email": None},
    ],
)
def test_invalid_claims_are_rejected(overrides):
    with pytest.raises(GoogleLoginError) as error:
        _validate(_claims(**overrides))

    assert error.value.code == "invalid_token"


def test_pkce_challenge_matches_rfc_7636_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_transaction_round_trips_before_expiry():
    transaction = LoginTransaction(state="s", nonce="n", code_verifier="v")

    sealed = seal_transaction(transaction, NOW)

    assert open_transaction(sealed, NOW + 60) == transaction


def test_transaction_expires():
    sealed = seal_transaction(LoginTransaction("s", "n", "v"), NOW)

    assert open_transaction(sealed, NOW + 10 * 60) is None


def test_transaction_rejects_swapped_payload():
    _, signature = seal_transaction(LoginTransaction("s", "n", "v"), NOW).split(".")
    forged_body, _ = seal_transaction(LoginTransaction("attacker", "n", "v"), NOW).split(".")

    assert open_transaction(f"{forged_body}.{signature}", NOW) is None


def test_transaction_rejects_bad_signature():
    body, _ = seal_transaction(LoginTransaction("s", "n", "v"), NOW).split(".")

    assert open_transaction(f"{body}.wrong", NOW) is None
    assert open_transaction(body, NOW) is None


def _provider(id_token, jwks):
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"id_token": id_token})
        if str(request.url) == JWKS_URL:
            return httpx.Response(200, json=jwks)
        return httpx.Response(404)

    settings = Settings(
        google_client_id=CLIENT_ID,
        google_client_secret="secret",
        google_redirect_uri="http://localhost/callback",
    )
    return GoogleProvider(settings, transport=httpx.MockTransport(handler))


def test_provider_accepts_id_token_signed_by_jwks_key():
    key = JsonWebKey.generate_key("RSA", 2048, options={"kid": "trusted"}, is_private=True)
    token = JsonWebToken(["RS256"]).encode({"alg": "RS256", "kid": "trusted"}, _claims(), key)
    jwks = {"keys": [key.as_dict(is_private=False)]}

    claims = asyncio.run(_provider(token.decode(), jwks).fetch_claims("code", "verifier"))

    assert claims["sub"] == "1234567890"


def test_provider_rejects_id_token_signed_by_another_key():
    trusted = JsonWebKey.generate_key("RSA", 2048, options={"kid": "trusted"}, is_private=True)
    attacker = JsonWebKey.generate_key("RSA", 2048, options={"kid": "trusted"}, is_private=True)
    token = JsonWebToken(["RS256"]).encode({"alg": "RS256", "kid": "trusted"}, _claims(), attacker)
    jwks = {"keys": [trusted.as_dict(is_private=False)]}

    with pytest.raises(GoogleLoginError) as error:
        asyncio.run(_provider(token.decode(), jwks).fetch_claims("code", "verifier"))

    assert error.value.code == "invalid_token"
