from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth.permissions import Role, require_role


@pytest.mark.parametrize(
    ("held", "required", "allowed"),
    [
        (Role.reviewer, Role.analyst, True),
        (Role.reviewer, Role.reviewer, True),
        (Role.analyst, Role.analyst, True),
        (Role.analyst, Role.reviewer, False),
    ],
)
def test_role_matrix(held, required, allowed):
    assert held.covers(required) is allowed


def test_require_role_forbids_an_analyst_from_reviewer_actions():
    membership = SimpleNamespace(role="analyst")

    with pytest.raises(HTTPException) as error:
        require_role(membership, Role.reviewer)

    assert error.value.status_code == 403
