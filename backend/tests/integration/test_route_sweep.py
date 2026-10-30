import hashlib
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import get_engine, get_session_factory
from app.main import app
from app.models import ImportBatch, Organization, OrganizationMembership, Workspace

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
ORGANIZATIONS = "/api/v1/organizations"
WORKSPACES = "/api/v1/workspaces"
PASSWORD = "correct horse battery"
ORDERS_CSV = (Path(__file__).parents[1] / "fixtures" / "reconciliation" / "orders.csv").read_bytes()
UPLOAD_ROUTES = {
    ("POST", "/api/v1/workspaces/{workspace_id}/imports"),
    ("POST", "/api/v1/workspaces/{workspace_id}/imports/preview"),
}

# A new public route must be added here on purpose; everything else is swept.
PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("POST", REGISTER),
    ("POST", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/providers"),
    ("GET", "/api/v1/auth/google/login"),
    ("GET", "/api/v1/auth/google/callback"),
}

# Bodies that the cross-tenant call sends; they must be valid so the 404 is what decides.
TENANT_BODIES = {
    ("POST", "/api/v1/organizations/{organization_id}/members"): lambda t: {
        "email": t.analyst_email,
        "role": "analyst",
    },
    ("PATCH", "/api/v1/organizations/{organization_id}/members/{user_id}"): lambda t: {
        "role": "analyst"
    },
    ("POST", WORKSPACES): lambda t: {"organization_id": t.org_id, "name": "Stolen"},
    ("PATCH", "/api/v1/workspaces/{workspace_id}"): lambda t: {"name": "Renamed"},
}


def _send(client, method, template, url, headers, body=None):
    if (method, template) in UPLOAD_ROUTES:
        files = {"file": ("orders.csv", ORDERS_CSV, "text/csv")}
        return client.request(
            method, url, headers=headers, data={"source_name": "orders"}, files=files
        )
    return client.request(method, url, headers=headers, json=body)


def _endpoints(routes):
    # included routers are nested, so walk down to the effective endpoints
    for route in routes:
        if hasattr(route, "effective_candidates"):
            yield from _endpoints(route.effective_candidates())
        elif isinstance(getattr(route, "original_route", None), APIRoute):
            yield route.path, route.original_route.methods


def _all_routes() -> set[tuple[str, str]]:
    return {(method, path) for path, methods in _endpoints(app.routes) for method in methods}


PROTECTED_ROUTES = sorted(_all_routes() - PUBLIC_ROUTES)
STATE_CHANGING_ROUTES = [route for route in PROTECTED_ROUTES if route[0] != "GET"]
TENANT_ROUTES = [route for route in PROTECTED_ROUTES if "{" in route[1] or route in TENANT_BODIES]
LIST_ROUTES = [path for method, path in PROTECTED_ROUTES if method == "GET" and "{" not in path]


def _path(template: str, ids: dict | None = None) -> str:
    ids = ids or {}
    return re.sub(r"{(\w+)}", lambda match: str(ids.get(match.group(1), uuid.uuid4())), template)


def _email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _signed_in() -> tuple[TestClient, dict]:
    client = TestClient(app)
    registered = client.post(REGISTER, json={"email": _email(), "password": PASSWORD})
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _with_session_cookie(token: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set("session", token)
    return client


def _organization(client: TestClient) -> dict:
    response = client.post(
        ORGANIZATIONS, json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()


def _workspace(client: TestClient, org_id: str) -> dict:
    response = client.post(
        WORKSPACES,
        json={"organization_id": org_id, "name": f"Ledger {uuid.uuid4()}"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def signed_in():
    client, _ = _signed_in()
    return client


@pytest.fixture
def victim():
    owner, owner_user = _signed_in()
    org = _organization(owner)
    workspace = _workspace(owner, org["id"])
    imported = owner.post(
        f"{WORKSPACES}/{workspace['id']}/imports",
        data={"source_name": "orders"},
        files={"file": ("orders.csv", ORDERS_CSV, "text/csv")},
        headers=_csrf(owner),
    )
    assert imported.status_code == 201
    # The run lives in a second workspace: a workspace with runs cannot be deleted yet,
    # and the reviewer-only test deletes the victim workspace.
    run_workspace = _workspace(owner, org["id"])
    reconciled = owner.post(
        f"{WORKSPACES}/{run_workspace['id']}/reconciliation-runs", headers=_csrf(owner)
    )
    assert reconciled.status_code == 201
    analyst, analyst_user = _signed_in()
    added = owner.post(
        f"{ORGANIZATIONS}/{org['id']}/members",
        json={"email": analyst_user["email"], "role": "analyst"},
        headers=_csrf(owner),
    )
    assert added.status_code == 201
    return SimpleNamespace(
        client=owner,
        analyst=analyst,
        org_id=org["id"],
        workspace_id=workspace["id"],
        import_id=imported.json()["id"],
        run_id=reconciled.json()["id"],
        owner_id=owner_user["id"],
        analyst_id=analyst_user["id"],
        analyst_email=analyst_user["email"],
        identifiers=[
            org["id"],
            workspace["id"],
            owner_user["id"],
            analyst_user["id"],
            owner_user["email"],
            analyst_user["email"],
        ],
    )


@pytest.fixture
def attacker():
    client, _ = _signed_in()
    _organization(client)
    return client


def _snapshot(victim) -> tuple:
    with get_session_factory()() as db:
        organization = db.execute(
            select(Organization.id, Organization.name).where(Organization.id == victim.org_id)
        ).all()
        workspaces = db.execute(
            select(Workspace.id, Workspace.name, Workspace.timestamp_tolerance_hours)
            .where(Workspace.organization_id == victim.org_id)
            .order_by(Workspace.id)
        ).all()
        memberships = db.execute(
            select(OrganizationMembership.user_id, OrganizationMembership.role)
            .where(OrganizationMembership.organization_id == victim.org_id)
            .order_by(OrganizationMembership.user_id)
        ).all()
        imports = db.execute(
            select(ImportBatch.id, ImportBatch.status, ImportBatch.rows_total)
            .where(ImportBatch.workspace_id == victim.workspace_id)
            .order_by(ImportBatch.id)
        ).all()
    return organization, workspaces, memberships, imports


def test_public_allowlist_names_real_routes():
    assert PUBLIC_ROUTES <= _all_routes()
    assert PROTECTED_ROUTES


@pytest.mark.parametrize("method, path", PROTECTED_ROUTES)
def test_anonymous_request_gets_401(method, path):
    response = TestClient(app).request(method, _path(path))

    assert response.status_code == 401


@pytest.mark.parametrize("method, path", STATE_CHANGING_ROUTES)
def test_state_change_without_a_matching_csrf_header_gets_403(method, path, signed_in):
    missing = signed_in.request(method, _path(path))
    wrong = signed_in.request(method, _path(path), headers={"X-CSRF-Token": "not-the-token"})

    assert missing.status_code == 403
    assert wrong.status_code == 403


@pytest.mark.parametrize("method, path", TENANT_ROUTES)
def test_another_organization_gets_404_and_its_data_is_unchanged(method, path, victim, attacker):
    before = _snapshot(victim)
    ids = {
        "organization_id": victim.org_id,
        "workspace_id": victim.workspace_id,
        "user_id": victim.analyst_id,
        "import_id": victim.import_id,
        "run_id": victim.run_id,
    }
    body = TENANT_BODIES[(method, path)](victim) if (method, path) in TENANT_BODIES else None

    response = _send(attacker, method, path, _path(path, ids), _csrf(attacker), body)

    assert response.status_code == 404
    assert _snapshot(victim) == before


@pytest.mark.parametrize("path", LIST_ROUTES)
def test_lists_never_show_another_organizations_ids(path, victim, attacker):
    response = attacker.get(path, params={"organization_id": victim.org_id})

    assert response.status_code == 200
    for identifier in victim.identifiers:
        assert str(identifier) not in response.text


def test_reviewer_only_routes_refuse_analysts_and_admit_reviewers(victim):
    analyst, reviewer = victim.analyst, victim.client
    members = f"{ORGANIZATIONS}/{victim.org_id}/members"
    member_url = f"{members}/{victim.analyst_id}"
    workspace_url = f"{WORKSPACES}/{victim.workspace_id}"
    _, invitee = _signed_in()
    new_workspace = {"organization_id": victim.org_id, "name": f"Ledger {uuid.uuid4()}"}
    invite = {"email": invitee["email"], "role": "analyst"}

    analyst_attempts = [
        analyst.post(WORKSPACES, json=new_workspace, headers=_csrf(analyst)),
        analyst.patch(workspace_url, json={"name": "Renamed"}, headers=_csrf(analyst)),
        analyst.delete(workspace_url, headers=_csrf(analyst)),
        analyst.post(members, json=invite, headers=_csrf(analyst)),
        analyst.patch(member_url, json={"role": "reviewer"}, headers=_csrf(analyst)),
        analyst.delete(member_url, headers=_csrf(analyst)),
    ]

    assert [attempt.status_code for attempt in analyst_attempts] == [403] * 6
    assert reviewer.post(WORKSPACES, json=new_workspace, headers=_csrf(reviewer)).status_code == 201
    assert (
        reviewer.patch(workspace_url, json={"name": "Renamed"}, headers=_csrf(reviewer)).status_code
        == 200
    )
    assert reviewer.post(members, json=invite, headers=_csrf(reviewer)).status_code == 201
    assert (
        reviewer.patch(member_url, json={"role": "reviewer"}, headers=_csrf(reviewer)).status_code
        == 200
    )
    assert reviewer.delete(member_url, headers=_csrf(reviewer)).status_code == 204
    assert reviewer.delete(workspace_url, headers=_csrf(reviewer)).status_code == 204


def test_deleted_session_cookie_is_rejected():
    client, _ = _signed_in()
    token = client.cookies["session"]
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM sessions WHERE token_hash = :hash"), {"hash": _digest(token)}
        )

    assert _with_session_cookie(token).get(ME).status_code == 401


def test_expired_session_cookie_is_rejected():
    client, _ = _signed_in()
    token = client.cookies["session"]
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET expires_at = now() - interval '1 second' "
                "WHERE token_hash = :hash"
            ),
            {"hash": _digest(token)},
        )

    assert _with_session_cookie(token).get(ME).status_code == 401


def test_tampered_session_cookie_is_rejected():
    client, _ = _signed_in()
    token = client.cookies["session"]

    assert _with_session_cookie(f"{token}x").get(ME).status_code == 401


def test_session_cookie_is_dead_after_logout():
    client, _ = _signed_in()
    token = client.cookies["session"]

    assert client.post(LOGOUT, headers=_csrf(client)).status_code == 200
    assert _with_session_cookie(token).get(ME).status_code == 401
