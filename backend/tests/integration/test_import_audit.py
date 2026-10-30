import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import audit, cli
from app.db import get_session_factory
from app.imports import create_or_get_batch, process_batch, service
from app.main import app
from app.models import AuditEvent, ImportBatch, User, Workspace

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reconciliation"
REGISTER = "/api/v1/auth/register"
ORGANIZATIONS = "/api/v1/organizations"
WORKSPACES = "/api/v1/workspaces"
AUDIT = "/api/v1/audit-events"
PASSWORD = "correct horse battery"


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


@pytest.fixture
def owner():
    client = TestClient(app)
    user = client.post(
        REGISTER, json={"email": f"{uuid.uuid4()}@example.com", "password": PASSWORD}
    ).json()
    org = client.post(
        ORGANIZATIONS, json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    ).json()
    workspace = client.post(
        WORKSPACES,
        json={"organization_id": org["id"], "name": f"Ledger {uuid.uuid4()}"},
        headers=_csrf(client),
    ).json()
    return SimpleNamespace(client=client, user=user, org=org, workspace=workspace)


def _upload(client: TestClient, workspace_id: str, data: bytes):
    return client.post(
        f"{WORKSPACES}/{workspace_id}/imports",
        data={"source_name": "orders"},
        files={"file": ("orders.csv", data, "text/csv")},
        headers=_csrf(client),
    )


def _new_batch(owner, data: bytes) -> uuid.UUID:
    with get_session_factory()() as db:
        batch, _ = create_or_get_batch(
            db,
            user=db.get(User, uuid.UUID(owner.user["id"])),
            workspace=db.get(Workspace, uuid.UUID(owner.workspace["id"])),
            source_name="orders",
            filename="orders.csv",
            stream=io.BytesIO(data),
        )
        return batch.id


def _process(batch_id: uuid.UUID, data: bytes, chunk_size: int = 1000):
    return process_batch(
        get_session_factory(),
        batch_id,
        io.BytesIO(data),
        chunk_size=chunk_size,
        max_rows=None,
    )


def _batch_id(workspace_id: str) -> uuid.UUID:
    with get_session_factory()() as db:
        return db.scalar(
            select(ImportBatch.id)
            .where(ImportBatch.workspace_id == uuid.UUID(workspace_id))
            .order_by(ImportBatch.created_at.desc())
        )


def _events(batch_id: uuid.UUID) -> list[AuditEvent]:
    with get_session_factory()() as db:
        return list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.target_id == batch_id)
                .order_by(AuditEvent.created_at)
            )
        )


def _event_count(organization_id: str) -> int:
    with get_session_factory()() as db:
        return db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.organization_id == uuid.UUID(organization_id))
        )


def test_new_upload_records_created_then_completed(owner):
    data = (FIXTURES / "orders.csv").read_bytes()

    response = _upload(owner.client, owner.workspace["id"], data)

    assert response.status_code == 201
    batch = response.json()
    created, completed = _events(uuid.UUID(batch["id"]))
    assert [created.action, completed.action] == ["import.created", "import.completed"]
    for event in (created, completed):
        assert event.organization_id == uuid.UUID(owner.org["id"])
        assert event.actor_user_id == uuid.UUID(owner.user["id"])
        assert event.actor_email == owner.user["email"]
        assert event.target_type == "import_batch"
        assert event.target_id == uuid.UUID(batch["id"])
    assert created.event_metadata == {
        "source_name": "orders",
        "filename": "orders.csv",
        "file_size_bytes": len(data),
    }
    assert completed.event_metadata == {
        "rows_total": batch["rows_total"],
        "rows_processed": batch["rows_processed"],
        "rows_failed": batch["rows_failed"],
    }


def test_same_file_again_writes_no_events(owner):
    data = (FIXTURES / "orders.csv").read_bytes()
    _upload(owner.client, owner.workspace["id"], data)
    before = _event_count(owner.org["id"])

    again = _upload(owner.client, owner.workspace["id"], data)

    assert again.status_code == 200
    assert _event_count(owner.org["id"]) == before


def test_garbage_file_records_created_then_failed(owner):
    response = _upload(owner.client, owner.workspace["id"], b"\x00\xffnot a csv\x00")

    assert response.status_code == 422
    events = _events(_batch_id(owner.workspace["id"]))
    assert [event.action for event in events] == ["import.created", "import.failed"]
    assert set(events[1].event_metadata) == {"error_summary"}


def test_crash_then_resume_records_failed_then_completed(owner, monkeypatch):
    data = (FIXTURES / "orders.csv").read_bytes()
    batch_id = _new_batch(owner, data)
    real_insert_chunk = service._insert_chunk
    calls = []

    def fail_second_chunk(session, batch_row, rows, seen):
        calls.append(seen)
        if len(calls) == 2:
            raise RuntimeError("simulated crash")
        real_insert_chunk(session, batch_row, rows, seen)

    monkeypatch.setattr(service, "_insert_chunk", fail_second_chunk)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _process(batch_id, data, chunk_size=3)
    monkeypatch.undo()
    _process(batch_id, data, chunk_size=3)
    assert [event.action for event in _events(batch_id)] == [
        "import.created",
        "import.failed",
        "import.completed",
    ]

    _process(batch_id, data)

    assert len(_events(batch_id)) == 3


def test_cli_without_a_user_records_the_system_actor(owner):
    exit_code = cli.main(
        [
            "import",
            str(FIXTURES / "orders.csv"),
            "--workspace",
            owner.workspace["id"],
            "--source",
            "orders",
        ]
    )

    assert exit_code == 0
    events = _events(_batch_id(owner.workspace["id"]))
    assert [(event.action, event.actor_email, event.actor_user_id) for event in events] == [
        ("import.created", "system", None),
        ("import.completed", "system", None),
    ]


def test_failed_audit_write_leaves_the_batch_status_unchanged(owner, monkeypatch):
    data = (FIXTURES / "orders.csv").read_bytes()
    batch_id = _new_batch(owner, data)

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(audit, "record", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        _process(batch_id, data)
    monkeypatch.undo()

    with get_session_factory()() as db:
        assert db.get(ImportBatch, batch_id).status == "processing"


def test_import_events_are_visible_to_members_only(owner):
    batch = _upload(owner.client, owner.workspace["id"], (FIXTURES / "orders.csv").read_bytes())
    params = {"organization_id": owner.org["id"], "target_id": batch.json()["id"]}

    member = owner.client.get(AUDIT, params=params)

    assert member.status_code == 200
    assert sorted(event["action"] for event in member.json()) == [
        "import.completed",
        "import.created",
    ]
    outsider = TestClient(app)
    outsider.post(REGISTER, json={"email": f"{uuid.uuid4()}@example.com", "password": PASSWORD})

    assert outsider.get(AUDIT, params=params).status_code == 404
