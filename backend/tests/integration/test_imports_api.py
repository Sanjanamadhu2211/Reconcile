import csv
import io
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_session_factory
from app.imports import create_or_get_batch, process_batch, service
from app.main import app
from app.models import ImportBatch, ImportRow, User, Workspace

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reconciliation"
REGISTER = "/api/v1/auth/register"
ORGANIZATIONS = "/api/v1/organizations"
WORKSPACES = "/api/v1/workspaces"
IMPORTS = "/api/v1/imports"
PASSWORD = "correct horse battery"
REQUIRED_ORDER_HEADERS = ["amount", "currency", "order_date", "order_id"]


def _fixture(filename: str) -> bytes:
    return (FIXTURES / filename).read_bytes()


def _golden_rows(filename: str) -> list[tuple]:
    with (FIXTURES / "expected_import_rows.csv").open(newline="") as f:
        return [
            (int(row["row_number"]), row["validation_status"], row["error_code"] or None)
            for row in csv.DictReader(f)
            if row["source_file"] == filename
        ]


def _golden_problems(filename: str) -> list[tuple]:
    return [row for row in _golden_rows(filename) if row[1] != "VALID"]


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _signed_in() -> tuple[TestClient, dict]:
    client = TestClient(app)
    registered = client.post(
        REGISTER, json={"email": f"{uuid.uuid4()}@example.com", "password": PASSWORD}
    )
    return client, registered.json()


def _workspace(client: TestClient) -> dict:
    org = client.post(
        ORGANIZATIONS, json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    ).json()
    response = client.post(
        WORKSPACES,
        json={"organization_id": org["id"], "name": f"Ledger {uuid.uuid4()}"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    return response.json()


def _upload(client, workspace_id, filename, data=None, source=None, key=None):
    headers = _csrf(client)
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(
        f"{WORKSPACES}/{workspace_id}/imports",
        data={"source_name": source or filename.removesuffix(".csv")},
        files={"file": (filename, data if data is not None else _fixture(filename), "text/csv")},
        headers=headers,
    )


def _preview(client, workspace_id, filename, data=None):
    return client.post(
        f"{WORKSPACES}/{workspace_id}/imports/preview",
        data={"source_name": filename.removesuffix(".csv")},
        files={"file": (filename, data if data is not None else _fixture(filename), "text/csv")},
        headers=_csrf(client),
    )


def _stored_rows(batch_id) -> list[tuple]:
    with get_session_factory()() as db:
        rows = db.scalars(
            select(ImportRow)
            .where(ImportRow.import_batch_id == uuid.UUID(str(batch_id)))
            .order_by(ImportRow.row_number)
        ).all()
        return [(row.row_number, row.validation_status, row.error_code) for row in rows]


def _batch_and_row_counts() -> tuple[int, int]:
    with get_session_factory()() as db:
        batches = db.scalar(select(func.count()).select_from(ImportBatch))
        rows = db.scalar(select(func.count()).select_from(ImportRow))
        return batches, rows


@pytest.fixture
def owner():
    client, user = _signed_in()
    workspace = _workspace(client)
    return SimpleNamespace(client=client, user=user, workspace=workspace)


def test_upload_then_poll_the_batch(owner):
    created = _upload(owner.client, owner.workspace["id"], "orders.csv")
    polled = owner.client.get(f"{IMPORTS}/{created.json()['id']}")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert polled.status_code == 200
    assert polled.json() == created.json()
    expected = _golden_rows("orders.csv")
    assert polled.json()["rows_total"] == len(expected)
    assert polled.json()["rows_failed"] == len(_golden_problems("orders.csv"))


@pytest.mark.parametrize("source", ["orders", "payments", "refunds", "settlements", "fees"])
def test_stored_rows_match_the_golden_expectation(owner, source):
    filename = f"{source}.csv"

    created = _upload(owner.client, owner.workspace["id"], filename)

    assert created.status_code == 201
    assert _stored_rows(created.json()["id"]) == _golden_rows(filename)


def test_same_file_again_returns_the_existing_batch(owner):
    first = _upload(owner.client, owner.workspace["id"], "fees.csv")
    rows_before = _stored_rows(first.json()["id"])

    again = _upload(owner.client, owner.workspace["id"], "fees.csv")

    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert _stored_rows(first.json()["id"]) == rows_before


def test_same_idempotency_key_with_a_different_file_is_a_conflict(owner):
    key = str(uuid.uuid4())
    first = _upload(owner.client, owner.workspace["id"], "orders.csv", key=key)

    conflict = _upload(owner.client, owner.workspace["id"], "fees.csv", key=key)

    assert first.status_code == 201
    assert conflict.status_code == 409


def test_oversized_upload_gets_413(owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    too_big = b"x" * (1024 * 1024 + 1)

    response = _upload(owner.client, owner.workspace["id"], "orders.csv", data=too_big)

    assert response.status_code == 413


def test_unknown_source_name_gets_422(owner):
    response = _upload(owner.client, owner.workspace["id"], "orders.csv", source="invoices")

    assert response.status_code == 422


def test_binary_garbage_leaves_a_failed_batch_with_a_short_summary(owner):
    garbage = bytes(range(256)) * 4

    response = _upload(owner.client, owner.workspace["id"], "orders.csv", data=garbage)

    batch = response.json()["detail"]["batch"]
    assert response.status_code == 422
    assert batch["status"] == "failed"
    assert batch["error_summary"] == "ENCODING_ERROR"
    assert (
        owner.client.get(f"{WORKSPACES}/{owner.workspace['id']}/imports").json()[0]["id"]
        == batch["id"]
    )


def test_too_many_rows_gets_422_and_a_failed_batch(owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_import_rows", 3)

    response = _upload(owner.client, owner.workspace["id"], "orders.csv")

    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "too many rows"
    assert response.json()["detail"]["batch"]["status"] == "failed"


def test_resuming_a_failed_batch_matches_a_clean_run(owner, db, monkeypatch):
    data = _fixture("payments.csv")
    user = db.get(User, uuid.UUID(owner.user["id"]))
    workspace = db.get(Workspace, uuid.UUID(owner.workspace["id"]))
    batch, _ = create_or_get_batch(
        db,
        user=user,
        workspace=workspace,
        source_name="payments",
        filename="payments.csv",
        stream=io.BytesIO(data),
    )
    real_insert_chunk = service._insert_chunk
    chunks_written = []

    def fail_second_chunk(session, batch_row, rows, seen):
        if len(chunks_written) == 1:
            raise RuntimeError("simulated crash")
        chunks_written.append(rows)
        real_insert_chunk(session, batch_row, rows, seen)

    with monkeypatch.context() as patch:
        patch.setattr(service, "_insert_chunk", fail_second_chunk)
        with pytest.raises(RuntimeError):
            process_batch(
                get_session_factory(), batch.id, io.BytesIO(data), chunk_size=3, max_rows=None
            )

    resumed = _upload(owner.client, owner.workspace["id"], "payments.csv")

    assert resumed.status_code == 200
    assert resumed.json()["id"] == str(batch.id)
    assert resumed.json()["status"] == "completed"
    assert _stored_rows(batch.id) == _golden_rows("payments.csv")


def test_preview_reports_problems_and_writes_nothing(owner):
    before = _batch_and_row_counts()

    response = _preview(owner.client, owner.workspace["id"], "orders.csv")

    assert response.status_code == 200
    body = response.json()
    assert body["headers_required"] == REQUIRED_ORDER_HEADERS
    assert body["valid_rows"] == len(_golden_rows("orders.csv")) - len(
        _golden_problems("orders.csv")
    )
    assert body["invalid_rows"] == len(_golden_problems("orders.csv"))
    assert [
        (problem["row_number"], problem["validation_status"], problem["error_code"])
        for problem in body["problems"]
    ] == _golden_problems("orders.csv")
    assert _batch_and_row_counts() == before


def test_preview_lists_at_most_twenty_problems(owner):
    header = b"order_id,amount,currency,order_date\n"
    rows = b"".join(b"ORD-%d,abc,USD,2024-01-01T00:00:00Z\n" % i for i in range(25))

    response = _preview(owner.client, owner.workspace["id"], "orders.csv", data=header + rows)

    assert response.json()["invalid_rows"] == 25
    assert len(response.json()["problems"]) == 20


def test_preview_with_the_wrong_headers_reports_both_header_sets(owner):
    fees = _fixture("fees.csv")

    response = _preview(owner.client, owner.workspace["id"], "orders.csv", data=fees)

    assert response.status_code == 422
    assert response.json()["detail"]["headers_found"] == fees.decode().splitlines()[0].split(",")
    assert response.json()["detail"]["headers_required"] == REQUIRED_ORDER_HEADERS


def test_errors_list_only_invalid_rows_and_pages(owner):
    created = _upload(owner.client, owner.workspace["id"], "orders.csv")
    url = f"{IMPORTS}/{created.json()['id']}/errors"

    listed = [
        row
        for offset in range(0, len(_golden_problems("orders.csv")), 3)
        for row in owner.client.get(url, params={"limit": 3, "offset": offset}).json()
    ]

    assert [
        (row["row_number"], row["validation_status"], row["error_code"]) for row in listed
    ] == _golden_problems("orders.csv")
    assert owner.client.get(url, params={"limit": 101}).status_code == 422
    assert owner.client.get(url, params={"limit": 0}).status_code == 422


def test_listing_is_newest_first_and_bounded(owner):
    first = _upload(owner.client, owner.workspace["id"], "orders.csv")
    second = _upload(owner.client, owner.workspace["id"], "fees.csv")
    url = f"{WORKSPACES}/{owner.workspace['id']}/imports"

    listed = owner.client.get(url, params={"limit": 2}).json()
    second_page = owner.client.get(url, params={"limit": 1, "offset": 1}).json()

    assert [batch["id"] for batch in listed] == [second.json()["id"], first.json()["id"]]
    assert [batch["id"] for batch in second_page] == [first.json()["id"]]


def test_analyst_can_upload(owner):
    analyst, analyst_user = _signed_in()
    org_id = owner.workspace["organization_id"]
    added = owner.client.post(
        f"{ORGANIZATIONS}/{org_id}/members",
        json={"email": analyst_user["email"], "role": "analyst"},
        headers=_csrf(owner.client),
    )
    assert added.status_code == 201

    response = _upload(analyst, owner.workspace["id"], "fees.csv")

    assert response.status_code == 201
