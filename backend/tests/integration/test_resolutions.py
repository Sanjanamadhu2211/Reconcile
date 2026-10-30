import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import audit
from app.db import get_engine
from app.main import app

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
ORGANIZATIONS = "/api/v1/organizations"
EXCEPTIONS = "/api/v1/exceptions"
AUDIT = "/api/v1/audit-events"
DECISIONS = ("propose", "approve", "reject", "reopen")


def _signed_in() -> tuple[TestClient, dict]:
    client = TestClient(app)
    registered = client.post(
        "/api/v1/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": PASSWORD}
    )
    assert registered.status_code == 201
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _organization(client: TestClient) -> str:
    response = client.post(
        ORGANIZATIONS, json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()["id"]


def _join(owner: TestClient, org_id: str, role: str) -> tuple[TestClient, str]:
    member, user = _signed_in()
    added = owner.post(
        f"{ORGANIZATIONS}/{org_id}/members",
        json={"email": user["email"], "role": role},
        headers=_csrf(owner),
    )
    assert added.status_code == 201
    return member, user["email"]


def _seed_exception(org_id: str) -> uuid.UUID:
    with get_engine().begin() as conn:
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (organization_id, name) VALUES (:org, :name) RETURNING id"
            ),
            {"org": org_id, "name": f"Ledger {uuid.uuid4()}"},
        ).scalar_one()
        run_id = conn.execute(
            text(
                "INSERT INTO reconciliation_runs (organization_id, workspace_id, rule_version, "
                "tolerance_hours) VALUES (:org, :workspace, 'v1', 24) RETURNING id"
            ),
            {"org": org_id, "workspace": workspace_id},
        ).scalar_one()
        batch_id = conn.execute(
            text(
                "INSERT INTO import_batches (organization_id, workspace_id, source_name, "
                "file_size_bytes, file_checksum) "
                "VALUES (:org, :workspace, 'orders', 10, :checksum) RETURNING id"
            ),
            {"org": org_id, "workspace": workspace_id, "checksum": uuid.uuid4().hex},
        ).scalar_one()
        row_id = conn.execute(
            text(
                "INSERT INTO import_rows (organization_id, import_batch_id, row_number, payload, "
                "validation_status) VALUES (:org, :batch, 1, '{}', 'VALID') RETURNING id"
            ),
            {"org": org_id, "batch": batch_id},
        ).scalar_one()
        return conn.execute(
            text(
                "INSERT INTO exceptions (organization_id, workspace_id, reconciliation_run_id, "
                "category, import_row_id) "
                "VALUES (:org, :workspace, :run, 'unmatched', :row) RETURNING id"
            ),
            {"org": org_id, "workspace": workspace_id, "run": run_id, "row": row_id},
        ).scalar_one()


def _rows(sql: str, **params) -> list:
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params).all()


def _state(client: TestClient, exception_id) -> dict:
    response = client.get(f"{EXCEPTIONS}/{exception_id}")
    assert response.status_code == 200
    return response.json()


def _decide(client: TestClient, exception_id, decision: str, version: int, note="Checked"):
    return client.post(
        f"{EXCEPTIONS}/{exception_id}/{decision}",
        json={"version": version, "note": note},
        headers=_csrf(client),
    )


def _resolution_count(exception_id) -> int:
    return _rows("SELECT count(*) FROM resolutions WHERE exception_id = :id", id=exception_id)[0][0]


@pytest.fixture
def team():
    owner, owner_user = _signed_in()
    org_id = _organization(owner)
    other, other_email = _join(owner, org_id, "reviewer")
    third, _ = _join(owner, org_id, "reviewer")
    analyst, analyst_email = _join(owner, org_id, "analyst")
    return SimpleNamespace(
        org_id=org_id,
        reviewer=owner,
        reviewer_email=owner_user["email"],
        other_reviewer=other,
        other_reviewer_email=other_email,
        third_reviewer=third,
        analyst=analyst,
        analyst_email=analyst_email,
    )


@pytest.fixture
def exception_id(team):
    return _seed_exception(team.org_id)


def test_full_cycle_writes_one_resolution_and_one_audit_event_per_transition(team, exception_id):
    assert _decide(team.analyst, exception_id, "propose", 1).status_code == 200
    assert _decide(team.other_reviewer, exception_id, "reject", 2).status_code == 200
    assert _decide(team.analyst, exception_id, "propose", 3).status_code == 200
    assert _decide(team.other_reviewer, exception_id, "approve", 4).status_code == 200
    response = _decide(team.other_reviewer, exception_id, "reopen", 5)

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    assert response.json()["version"] == 6
    assert _rows(
        "SELECT decision, exception_version FROM resolutions "
        "WHERE exception_id = :id ORDER BY created_at, id",
        id=exception_id,
    ) == [("propose", 2), ("reject", 3), ("propose", 4), ("approve", 5), ("reopen", 6)]
    assert _rows(
        "SELECT action, actor_email FROM audit_events "
        "WHERE target_id = :id ORDER BY created_at, id",
        id=exception_id,
    ) == [
        ("exception.proposed", team.analyst_email),
        ("exception.rejected", team.other_reviewer_email),
        ("exception.proposed", team.analyst_email),
        ("exception.approved", team.other_reviewer_email),
        ("exception.reopened", team.other_reviewer_email),
    ]


def test_history_lists_decisions_oldest_first_for_any_member(team, exception_id):
    _decide(team.analyst, exception_id, "propose", 1, "Matches the bank line")
    _decide(team.reviewer, exception_id, "reject", 2, "Wrong amount")

    response = team.analyst.get(f"{EXCEPTIONS}/{exception_id}/history")

    assert response.status_code == 200
    assert [
        (item["decision"], item["note"], item["actor_email"], item["exception_version"])
        for item in response.json()
    ] == [
        ("propose", "Matches the bank line", team.analyst_email, 2),
        ("reject", "Wrong amount", team.reviewer_email, 3),
    ]


@pytest.mark.parametrize(
    "setup, decision",
    [
        ("open", "approve"),
        ("open", "reject"),
        ("open", "reopen"),
        ("proposed", "propose"),
        ("proposed", "reopen"),
        ("resolved", "propose"),
        ("resolved", "approve"),
        ("resolved", "reject"),
    ],
)
def test_transitions_outside_the_table_are_409_and_name_the_status(
    team, exception_id, setup, decision
):
    if setup != "open":
        _decide(team.analyst, exception_id, "propose", 1)
    if setup == "resolved":
        _decide(team.other_reviewer, exception_id, "approve", 2)
    before = _state(team.reviewer, exception_id)

    response = _decide(team.other_reviewer, exception_id, decision, before["version"])

    assert response.status_code == 409
    assert f"an exception that is {setup}" in response.json()["detail"]
    assert _state(team.reviewer, exception_id) == before


def test_analyst_may_only_propose(team, exception_id):
    assert _decide(team.analyst, exception_id, "propose", 1).status_code == 200

    assert _decide(team.analyst, exception_id, "approve", 2).status_code == 403
    assert _decide(team.analyst, exception_id, "reject", 2).status_code == 403
    assert _decide(team.analyst, exception_id, "reopen", 2).status_code == 403
    assert _state(team.analyst, exception_id)["status"] == "proposed"


def test_reviewer_cannot_approve_their_own_proposal(team, exception_id):
    assert _decide(team.other_reviewer, exception_id, "propose", 1).status_code == 200

    response = _decide(team.other_reviewer, exception_id, "approve", 2)

    assert response.status_code == 403
    assert "own proposal" in response.json()["detail"]
    assert _decide(team.reviewer, exception_id, "approve", 2).status_code == 200


def test_blank_notes_are_refused_where_a_note_is_required(team, exception_id):
    assert _decide(team.analyst, exception_id, "propose", 1, note="   ").status_code == 422
    assert _decide(team.analyst, exception_id, "propose", 1, note=None).status_code == 422
    assert _decide(team.analyst, exception_id, "propose", 1).status_code == 200

    assert _decide(team.reviewer, exception_id, "reject", 2, note=" ").status_code == 422
    assert _decide(team.reviewer, exception_id, "reject", 2).status_code == 200
    assert _decide(team.analyst, exception_id, "propose", 3).status_code == 200
    assert _decide(team.reviewer, exception_id, "approve", 4, note=None).status_code == 200
    assert _decide(team.reviewer, exception_id, "reopen", 5, note="").status_code == 422
    assert _decide(team.reviewer, exception_id, "reopen", 5, note="Found more").status_code == 200


def test_stale_version_is_409_and_changes_nothing(team, exception_id):
    response = _decide(team.analyst, exception_id, "propose", 7)

    assert response.status_code == 409
    assert "stale" in response.json()["detail"]
    assert _state(team.analyst, exception_id)["status"] == "open"
    assert _resolution_count(exception_id) == 0

    assert _decide(team.analyst, exception_id, "propose", 1).status_code == 200
    stale_approval = _decide(team.reviewer, exception_id, "approve", 1)

    assert stale_approval.status_code == 409
    assert _state(team.analyst, exception_id)["version"] == 2


def test_two_approvals_of_the_same_version_let_exactly_one_win(team, exception_id):
    assert _decide(team.analyst, exception_id, "propose", 1).status_code == 200
    barrier = threading.Barrier(2)

    def approve(client: TestClient) -> int:
        barrier.wait()
        return _decide(client, exception_id, "approve", 2, note=None).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(approve, [team.other_reviewer, team.third_reviewer]))

    assert sorted(statuses) == [200, 409]
    assert _resolution_count(exception_id) == 2
    assert _rows(
        "SELECT count(*) FROM resolutions WHERE exception_id = :id AND decision = 'approve'",
        id=exception_id,
    ) == [(1,)]
    assert _rows(
        "SELECT count(*) FROM audit_events WHERE target_id = :id AND action = 'exception.approved'",
        id=exception_id,
    ) == [(1,)]


def test_failed_audit_write_rolls_back_the_state_change(team, exception_id, monkeypatch):
    def broken_audit(*args, **kwargs):
        raise RuntimeError("audit is down")

    monkeypatch.setattr(audit, "record", broken_audit)

    with pytest.raises(RuntimeError, match="audit is down"):
        _decide(team.analyst, exception_id, "propose", 1)

    assert _rows("SELECT status, version FROM exceptions WHERE id = :id", id=exception_id) == [
        ("open", 1)
    ]
    assert _resolution_count(exception_id) == 0


def test_another_organizations_exception_is_not_found(team, exception_id):
    attacker, _ = _signed_in()
    _organization(attacker)

    for decision in DECISIONS:
        assert _decide(attacker, exception_id, decision, 1).status_code == 404
    assert attacker.get(f"{EXCEPTIONS}/{exception_id}/history").status_code == 404
    assert _state(team.reviewer, exception_id)["status"] == "open"
    assert _resolution_count(exception_id) == 0


def test_anonymous_and_csrf_less_requests_are_refused(team, exception_id):
    anonymous = TestClient(app)
    body = {"version": 1, "note": "Checked"}

    assert anonymous.post(f"{EXCEPTIONS}/{exception_id}/propose", json=body).status_code == 401
    assert team.analyst.post(f"{EXCEPTIONS}/{exception_id}/propose", json=body).status_code == 403


def _two_audit_events(team, exception_id) -> None:
    _decide(team.analyst, exception_id, "propose", 1)
    _decide(team.other_reviewer, exception_id, "reject", 2)


def test_audit_list_is_newest_first_with_the_event_fields(team, exception_id):
    _two_audit_events(team, exception_id)

    response = team.reviewer.get(AUDIT, params={"organization_id": team.org_id})

    assert response.status_code == 200
    events = response.json()
    assert [event["action"] for event in events] == ["exception.rejected", "exception.proposed"]
    assert set(events[0]) == {
        "id",
        "actor_email",
        "action",
        "target_type",
        "target_id",
        "metadata",
        "created_at",
    }
    assert events[0]["actor_email"] == team.other_reviewer_email
    assert events[0]["target_type"] == "exception"
    assert events[1]["metadata"] == {"from": "open", "to": "proposed", "version": 2}


def test_audit_list_pages_and_filters(team, exception_id):
    _two_audit_events(team, exception_id)
    other_target = uuid.uuid4()
    params = {"organization_id": team.org_id}

    first = team.reviewer.get(AUDIT, params={**params, "limit": 1, "offset": 0}).json()
    second = team.reviewer.get(AUDIT, params={**params, "limit": 1, "offset": 1}).json()
    assert [event["action"] for event in first + second] == [
        "exception.rejected",
        "exception.proposed",
    ]
    assert team.reviewer.get(AUDIT, params={**params, "limit": 0}).status_code == 422
    assert team.reviewer.get(AUDIT, params={**params, "limit": 101}).status_code == 422

    proposed = team.reviewer.get(AUDIT, params={**params, "action": "exception.proposed"}).json()
    assert [event["action"] for event in proposed] == ["exception.proposed"]
    target = team.reviewer.get(
        AUDIT, params={**params, "target_type": "exception", "target_id": str(exception_id)}
    ).json()
    assert len(target) == 2
    unknown = team.reviewer.get(AUDIT, params={**params, "target_id": str(other_target)}).json()
    assert unknown == []


def test_audit_list_needs_organization_id_only_for_several_organizations(team, exception_id):
    _two_audit_events(team, exception_id)
    _organization(team.reviewer)

    assert team.reviewer.get(AUDIT).status_code == 422
    assert team.reviewer.get(AUDIT, params={"organization_id": team.org_id}).status_code == 200
    assert team.analyst.get(AUDIT).status_code == 200


def test_audit_list_hides_other_organizations_and_unknown_members_get_404(team, exception_id):
    _two_audit_events(team, exception_id)
    attacker, _ = _signed_in()
    own_org = _organization(attacker)

    assert team.reviewer.get(AUDIT, params={"organization_id": team.org_id}).status_code == 200
    assert attacker.get(AUDIT, params={"organization_id": team.org_id}).status_code == 404
    listed = attacker.get(AUDIT, params={"organization_id": own_org})
    assert listed.status_code == 200
    assert listed.json() == []
    assert str(exception_id) not in listed.text
