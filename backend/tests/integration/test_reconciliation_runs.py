import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session_factory
from app.imports import create_or_get_batch, process_batch
from app.main import app
from app.models import Exception as ExceptionRow
from app.models import Match, ReconciliationRun, User, Workspace
from app.reconciliation import runner

pytestmark = pytest.mark.integration

ORGANIZATIONS = "/api/v1/organizations"
WORKSPACES = "/api/v1/workspaces"
RUNS = "/api/v1/reconciliation-runs"
PASSWORD = "correct horse battery"

ORDERS = (
    b"order_id,amount,currency,order_date,customer_id\nORD-1,100.00,USD,2024-01-15T10:00:00Z,C-1\n"
)
PAYMENTS = (
    b"payment_id,amount,currency,paid_at,order_id\nPAY-1,100.00,USD,2024-01-15T12:00:00Z,ORD-1\n"
)


def _email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _signed_in() -> tuple[TestClient, dict]:
    client = TestClient(app)
    registered = client.post(
        "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
    )
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _create(client: TestClient, url: str, body: dict) -> dict:
    response = client.post(url, json=body, headers=_csrf(client))
    assert response.status_code == 201
    return response.json()


def _import(workspace_id: str, user_id: str, source: str, data: bytes) -> None:
    with get_session_factory()() as db:
        workspace = db.get(Workspace, uuid.UUID(workspace_id))
        batch, _ = create_or_get_batch(
            db,
            user=db.get(User, uuid.UUID(user_id)),
            workspace=workspace,
            source_name=source,
            filename=f"{source}.csv",
            stream=io.BytesIO(data),
        )
        batch_id = batch.id
    process_batch(get_session_factory(), batch_id, io.BytesIO(data), max_rows=None)


@pytest.fixture
def victim():
    owner, owner_user = _signed_in()
    org = _create(owner, ORGANIZATIONS, {"name": f"Org {uuid.uuid4()}"})
    workspace = _create(
        owner, WORKSPACES, {"organization_id": org["id"], "name": f"Ledger {uuid.uuid4()}"}
    )
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
        user_id=owner_user["id"],
    )


@pytest.fixture
def attacker():
    client, _ = _signed_in()
    _create(client, ORGANIZATIONS, {"name": f"Org {uuid.uuid4()}"})
    return client


def _start(client: TestClient, workspace_id: str):
    return client.post(f"{WORKSPACES}/{workspace_id}/reconciliation-runs", headers=_csrf(client))


def test_analyst_and_reviewer_start_a_run(victim):
    reviewer_run = _start(victim.client, victim.workspace_id)
    analyst_run = _start(victim.analyst, victim.workspace_id)

    assert reviewer_run.status_code == 201
    assert analyst_run.status_code == 201
    assert reviewer_run.json()["status"] == "completed"
    assert analyst_run.json()["workspace_id"] == victim.workspace_id


def test_run_can_be_read_back_by_members(victim):
    run_id = _start(victim.client, victim.workspace_id).json()["id"]

    response = victim.analyst.get(f"{RUNS}/{run_id}")

    assert response.status_code == 200
    assert response.json()["id"] == run_id


def test_another_organization_gets_404_for_post_and_get(victim, attacker):
    run_id = _start(victim.client, victim.workspace_id).json()["id"]

    assert _start(attacker, victim.workspace_id).status_code == 404
    assert attacker.get(f"{RUNS}/{run_id}").status_code == 404


def test_anonymous_request_gets_401(victim):
    response = TestClient(app).post(f"{WORKSPACES}/{victim.workspace_id}/reconciliation-runs")

    assert response.status_code == 401


def test_post_without_csrf_gets_403(victim):
    response = victim.client.post(f"{WORKSPACES}/{victim.workspace_id}/reconciliation-runs")

    assert response.status_code == 403


def test_tolerance_from_the_workspace_decides_the_boundary_pair(victim):
    _import(victim.workspace_id, str(victim.user_id), "orders", ORDERS)
    _import(victim.workspace_id, str(victim.user_id), "payments", PAYMENTS)
    url = f"{WORKSPACES}/{victim.workspace_id}"
    # the payment is exactly two hours after the order
    victim.client.patch(url, json={"timestamp_tolerance_hours": 2}, headers=_csrf(victim.client))
    within = _start(victim.client, victim.workspace_id).json()

    victim.client.patch(url, json={"timestamp_tolerance_hours": 1}, headers=_csrf(victim.client))
    beyond = _start(victim.client, victim.workspace_id).json()

    assert within["matches_count"] == 1
    assert beyond["matches_count"] == 0
    assert beyond["exceptions_count"] == 2


def test_every_persisted_row_carries_the_workspace_organization(victim):
    _import(victim.workspace_id, str(victim.user_id), "orders", ORDERS)
    _import(victim.workspace_id, str(victim.user_id), "payments", PAYMENTS)
    run_id = _start(victim.client, victim.workspace_id).json()["id"]

    with get_session_factory()() as db:
        matches = db.scalars(select(Match).where(Match.reconciliation_run_id == uuid.UUID(run_id)))
        exceptions = db.scalars(
            select(ExceptionRow).where(ExceptionRow.reconciliation_run_id == uuid.UUID(run_id))
        )
        organization_ids = {m.organization_id for m in matches} | {
            e.organization_id for e in exceptions
        }
        run = db.get(ReconciliationRun, uuid.UUID(run_id))

    assert organization_ids == {uuid.UUID(victim.org_id)}
    assert run.organization_id == uuid.UUID(victim.org_id)


def test_second_start_while_running_gets_409(victim, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    real_run_matching = runner.run_matching

    def slow_run_matching(records, tolerance):
        started.set()
        release.wait(10)
        return real_run_matching(records, tolerance)

    monkeypatch.setattr(runner, "run_matching", slow_run_matching)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(_start, victim.client, victim.workspace_id)
        assert started.wait(10)
        second = _start(victim.analyst, victim.workspace_id)
        release.set()
        assert first.result(timeout=10).status_code == 201

    assert second.status_code == 409
