import pytest
from fastapi import HTTPException

from app.auth.csrf import require_csrf


def test_matching_cookie_and_header_pass():
    require_csrf(csrf_cookie="token", csrf_header="token")


@pytest.mark.parametrize(
    "cookie, header",
    [(None, "token"), ("token", None), (None, None), ("token", "other"), ("token", "tokén")],
)
def test_missing_or_different_token_is_forbidden(cookie, header):
    with pytest.raises(HTTPException) as error:
        require_csrf(csrf_cookie=cookie, csrf_header=header)

    assert error.value.status_code == 403
