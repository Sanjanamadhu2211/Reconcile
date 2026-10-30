import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.permissions import load_membership
from app.main import app
from app.models import User
from app.routers.organizations import (
    _keep_a_reviewer,
    _locked_membership,
)

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
ORGANIZATIONS = "/api/v1/organizations"
WORKSPACES = "/api/v1/workspaces"
PASSWORD = "correct horse battery"
ORDERS_CSV = (Path(__file__).parents[1] / "fixtures" / "reconciliation" / "orders.csv").read_bytes()


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4()}"


def _signed_in_client() -> tuple[TestClient, dict]:
    client = TestClient(app)
    email = f"{uuid.uuid4()}@example.com"
    registered = client.post(REGISTER, json={"email": email, "password": PASSWORD})
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _create_org(client: TestClient, name: str | None = None) -> dict:
    response = client.post(
        ORGANIZATIONS, json={"name": name or _unique("Org")}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()


def _add_member(client: TestClient, org_id: str, email: str, role: str = "analyst"):
    return client.post(
        f"{ORGANIZATIONS}/{org_id}/members",
        json={"email": email, "role": role},
        headers=_csrf(client),
    )


def _post_workspace(client: TestClient, org_id: str, name: str | None = None, **extra):
    body = {"organization_id": org_id, "name": name or _unique("Ledger"), **extra}
    return client.post(WORKSPACES, json=body, headers=_csrf(client))


def _create_workspace(client: TestClient, org_id: str) -> dict:
    response = _post_workspace(client, org_id)
    assert response.status_code == 201
    return response.json()


def test_creator_becomes_a_reviewer():
    owner, _ = _signed_in_client()
    name = _unique("Acme")

    org = _create_org(owner, name)

    assert org["name"] == name
    assert org["role"] == "reviewer"
    assert org in owner.get(ORGANIZATIONS).json()


def test_analyst_cannot_create_workspaces_or_manage_members():
    owner, owner_user = _signed_in_client()
    org = _create_org(owner)
    analyst, analyst_user = _signed_in_client()
    _add_member(owner, org["id"], analyst_user["email"], "analyst")
    members = f"{ORGANIZATIONS}/{org['id']}/members"
    _, outsider_user = _signed_in_client()

    assert _post_workspace(analyst, org["id"]).status_code == 403
    assert _add_member(analyst, org["id"], outsider_user["email"]).status_code == 403
    assert (
        analyst.patch(
            f"{members}/{owner_user['id']}", json={"role": "analyst"}, headers=_csrf(analyst)
        ).status_code
        == 403
    )
    assert (
        analyst.delete(f"{members}/{owner_user['id']}", headers=_csrf(analyst)).status_code == 403
    )


def test_another_organizations_data_is_not_found():
    owner, owner_user = _signed_in_client()
    org = _create_org(owner)
    workspace = _create_workspace(owner, org["id"])
    outsider, outsider_user = _signed_in_client()
    outsider_org = _create_org(outsider)
    members = f"{ORGANIZATIONS}/{org['id']}/members"
    workspace_url = f"{WORKSPACES}/{workspace['id']}"

    assert outsider.get(workspace_url).status_code == 404
    assert (
        outsider.patch(workspace_url, json={"name": "x"}, headers=_csrf(outsider)).status_code
        == 404
    )
    assert outsider.delete(workspace_url, headers=_csrf(outsider)).status_code == 404
    assert outsider.get(members).status_code == 404
    assert _add_member(outsider, org["id"], outsider_user["email"]).status_code == 404
    assert (
        outsider.patch(
            f"{members}/{owner_user['id']}", json={"role": "analyst"}, headers=_csrf(outsider)
        ).status_code
        == 404
    )
    assert (
        outsider.delete(f"{members}/{owner_user['id']}", headers=_csrf(outsider)).status_code == 404
    )
    assert workspace["id"] not in [w["id"] for w in outsider.get(WORKSPACES).json()]
    assert outsider.get(WORKSPACES, params={"organization_id": org["id"]}).json() == []
    assert org["id"] not in [o["id"] for o in outsider.get(ORGANIZATIONS).json()]
    assert outsider_org["id"] in [o["id"] for o in outsider.get(ORGANIZATIONS).json()]


def test_member_is_added_by_email_in_any_letter_case():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    invitee, invitee_user = _signed_in_client()

    response = _add_member(owner, org["id"], invitee_user["email"].upper(), "analyst")

    assert response.status_code == 201
    assert response.json() == {
        "user_id": invitee_user["id"],
        "email": invitee_user["email"],
        "role": "analyst",
    }
    assert _add_member(owner, org["id"], "nobody@example.com").status_code == 404


def test_adding_the_same_user_twice_is_a_conflict():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    _, invitee_user = _signed_in_client()

    assert _add_member(owner, org["id"], invitee_user["email"]).status_code == 201
    assert _add_member(owner, org["id"], invitee_user["email"].upper()).status_code == 409


def test_last_reviewer_cannot_be_demoted_or_removed_until_a_second_reviewer_exists():
    owner, owner_user = _signed_in_client()
    org = _create_org(owner)
    member_url = f"{ORGANIZATIONS}/{org['id']}/members/{owner_user['id']}"

    demoted = owner.patch(member_url, json={"role": "analyst"}, headers=_csrf(owner))
    removed = owner.delete(member_url, headers=_csrf(owner))

    assert demoted.status_code == 409
    assert removed.status_code == 409

    second, second_user = _signed_in_client()
    _add_member(owner, org["id"], second_user["email"], "reviewer")
    demoted = owner.patch(member_url, json={"role": "analyst"}, headers=_csrf(owner))
    second_url = f"{ORGANIZATIONS}/{org['id']}/members/{second_user['id']}"

    assert demoted.status_code == 200
    assert second.delete(second_url, headers=_csrf(second)).status_code == 409


def test_workspace_names_are_unique_per_organization():
    owner, _ = _signed_in_client()
    first_org = _create_org(owner)
    second_org = _create_org(owner)
    name = _unique("Ledger")
    _post_workspace(owner, first_org["id"], name)

    assert _post_workspace(owner, first_org["id"], name).status_code == 409
    assert _post_workspace(owner, second_org["id"], name).status_code == 201


def test_workspace_update_and_delete_by_reviewer():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    workspace = _create_workspace(owner, org["id"])
    workspace_url = f"{WORKSPACES}/{workspace['id']}"

    updated = owner.patch(
        workspace_url, json={"timestamp_tolerance_hours": 6}, headers=_csrf(owner)
    )
    deleted = owner.delete(workspace_url, headers=_csrf(owner))

    assert updated.status_code == 200
    assert updated.json()["timestamp_tolerance_hours"] == 6
    assert deleted.status_code == 204
    assert owner.get(workspace_url).status_code == 404


def test_workspace_delete_refused_when_imports_exist():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    workspace = _create_workspace(owner, org["id"])
    workspace_url = f"{WORKSPACES}/{workspace['id']}"

    # Import some data
    owner.post(
        f"{workspace_url}/imports",
        data={"source_name": "orders"},
        files={"file": ("orders.csv", ORDERS_CSV, "text/csv")},
        headers=_csrf(owner),
    )

    # Try to delete - should be refused
    deleted = owner.delete(workspace_url, headers=_csrf(owner))
    assert deleted.status_code == 409
    assert "holds imported data" in deleted.json()["detail"]
    # Workspace should still exist
    assert owner.get(workspace_url).status_code == 200


def test_workspace_delete_refused_when_runs_exist():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    workspace = _create_workspace(owner, org["id"])
    workspace_url = f"{WORKSPACES}/{workspace['id']}"

    # Import data and run reconciliation
    owner.post(
        f"{workspace_url}/imports",
        data={"source_name": "orders"},
        files={"file": ("orders.csv", ORDERS_CSV, "text/csv")},
        headers=_csrf(owner),
    )
    owner.post(f"{workspace_url}/reconciliation-runs", headers=_csrf(owner))

    # Try to delete - should be refused
    deleted = owner.delete(workspace_url, headers=_csrf(owner))
    assert deleted.status_code == 409
    assert "holds imported data" in deleted.json()["detail"]
    # Workspace should still exist
    assert owner.get(workspace_url).status_code == 200


def test_tolerance_must_be_positive():
    owner, _ = _signed_in_client()
    org = _create_org(owner)

    response = _post_workspace(owner, org["id"], timestamp_tolerance_hours=0)

    assert response.status_code == 422


def test_state_changing_routes_need_the_csrf_header():
    owner, _ = _signed_in_client()
    org = _create_org(owner)
    workspace = _create_workspace(owner, org["id"])
    _, invitee_user = _signed_in_client()
    member_url = f"{ORGANIZATIONS}/{org['id']}/members/{invitee_user['id']}"
    cases = [
        ("post", ORGANIZATIONS, {"name": "Acme"}),
        ("post", f"{ORGANIZATIONS}/{org['id']}/members", {"email": invitee_user["email"]}),
        ("patch", member_url, {"role": "reviewer"}),
        ("delete", member_url, None),
        ("post", WORKSPACES, {"organization_id": org["id"], "name": "Ledger"}),
        ("patch", f"{WORKSPACES}/{workspace['id']}", {"name": "Renamed"}),
        ("delete", f"{WORKSPACES}/{workspace['id']}", None),
    ]

    for method, url, body in cases:
        assert owner.request(method, url, json=body).status_code == 403, url


def test_unauthenticated_calls_are_rejected():
    anonymous = TestClient(app)
    anonymous.cookies.set("csrf_token", "token")

    assert anonymous.get(ORGANIZATIONS).status_code == 401
    assert anonymous.get(WORKSPACES).status_code == 401
    assert (
        anonymous.post(
            ORGANIZATIONS, json={"name": "Acme"}, headers={"X-CSRF-Token": "token"}
        ).status_code
        == 401
    )


def test_pagination_limits_are_enforced():
    client, _ = _signed_in_client()

    assert client.get(ORGANIZATIONS, params={"limit": 101}).status_code == 422
    assert client.get(WORKSPACES, params={"limit": 0}).status_code == 422
    assert client.get(ORGANIZATIONS, params={"offset": -1}).status_code == 422


def test_last_reviewer_guard_counts_roles_committed_after_they_were_loaded(db):
    owner, owner_user = _signed_in_client()
    org = _create_org(owner)
    _, second_user = _signed_in_client()
    _add_member(owner, org["id"], second_user["email"], "reviewer")
    loaded = load_membership(db, db.get(User, uuid.UUID(second_user["id"])), uuid.UUID(org["id"]))
    assert loaded.role == "reviewer"

    demoted = owner.patch(
        f"{ORGANIZATIONS}/{org['id']}/members/{second_user['id']}",
        json={"role": "analyst"},
        headers=_csrf(owner),
    )
    members, target = _locked_membership(db, uuid.UUID(org["id"]), uuid.UUID(owner_user["id"]))

    assert demoted.status_code == 200
    with pytest.raises(HTTPException) as error:
        _keep_a_reviewer(members, target)
    assert error.value.status_code == 409
