import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session_factory
from app.main import app
from app.models import (
    Exception as ExceptionModel,
)
from app.models import (
    ImportBatch,
    ImportRow,
    Match,
    ReconciliationRun,
    Transaction,
)

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"


def _unique_email() -> str:
    return f"{uuid.uuid4()}@example.com"


def _signed_in_client() -> tuple[TestClient, dict]:
    client = TestClient(app)
    email = _unique_email()
    registered = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201
    return client, registered.json()


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _create_org(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/organizations", json={"name": f"Org {uuid.uuid4()}"}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()


def _create_workspace(client: TestClient, org_id: str) -> dict:
    response = client.post(
        "/api/v1/workspaces",
        json={"organization_id": org_id, "name": f"Ledger {uuid.uuid4()}"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    return response.json()


def _add_analyst(owner: TestClient, org_id: str) -> tuple[TestClient, dict]:
    analyst, analyst_user = _signed_in_client()
    added = owner.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": analyst_user["email"], "role": "analyst"},
        headers=_csrf(owner),
    )
    assert added.status_code == 201
    return analyst, analyst_user


def _seed_run_with_data(
    db, org_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, seed: int = 1
) -> tuple[uuid.UUID, list[uuid.UUID], list[uuid.UUID]]:
    """Create a reconciliation run with matches and exceptions directly via models.
    Returns (run_id, match_ids, exception_ids)."""
    # Create a dummy import batch for the transactions
    batch = ImportBatch(
        organization_id=org_id,
        workspace_id=workspace_id,
        source_name="orders",
        file_size_bytes=1000,
        file_checksum=f"dummy-seed-{uuid.uuid4()}",
        status="completed",
        rows_total=10,
        rows_processed=10,
    )
    db.add(batch)
    db.flush()

    run = ReconciliationRun(
        organization_id=org_id,
        workspace_id=workspace_id,
        rule_version="v1",
        status="completed",
        tolerance_hours=24,
        matches_count=2,
        exceptions_count=5,
        created_by=user_id,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        completed_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db.add(run)
    db.flush()
    run_id = run.id

    # Create transactions with seed-suffixed external_ids to allow multiple runs per workspace
    base_ids = [
        ("orders", "ORD-001", Decimal("100.00")),
        ("payments", "PAY-001", Decimal("100.00")),
        ("orders", "ORD-002", Decimal("200.00")),
        ("payments", "PAY-002", Decimal("200.00")),
        ("orders", "ORD-003", Decimal("300.00")),
        ("payments", "PAY-003", Decimal("300.00")),
        ("refunds", "REF-001", Decimal("50.00")),
        ("settlements", "SET-001", Decimal("250.00")),
        ("fees", "FEE-001", Decimal("5.00")),
    ]
    txns = []
    for i, (src, ext_id, amt) in enumerate(base_ids):
        txn = Transaction(
            organization_id=org_id,
            workspace_id=workspace_id,
            import_batch_id=batch.id,
            source_name=src,
            external_id=f"{ext_id}-{seed}",
            amount=amt,
            currency="USD",
            transaction_type=src[:-1] if src != "fees" else "fee",
            occurred_at=datetime.now(UTC) - timedelta(days=i),
        )
        db.add(txn)
        txns.append(txn)
    db.flush()

    # Create matches: ORD-001 <-> PAY-001 (exact_id), ORD-002 <-> PAY-002 (amount_currency_time)
    match1 = Match(
        organization_id=org_id,
        reconciliation_run_id=run_id,
        rule="exact_id",
        left_transaction_id=txns[0].id,  # ORD-001
        right_transaction_id=txns[1].id,  # PAY-001
    )
    match2 = Match(
        organization_id=org_id,
        reconciliation_run_id=run_id,
        rule="amount_currency_time",
        left_transaction_id=txns[2].id,  # ORD-002
        right_transaction_id=txns[3].id,  # PAY-002
    )
    db.add_all([match1, match2])
    db.flush()
    match_ids = [match1.id, match2.id]

    # Create exceptions
    # unmatched: ORD-003
    exc1 = ExceptionModel(
        organization_id=org_id,
        workspace_id=workspace_id,
        reconciliation_run_id=run_id,
        category="unmatched",
        transaction_id=txns[4].id,  # ORD-003
        status="open",
        details={"note": "no payment found"},
    )
    # ambiguous: PAY-003 (multiple candidates)
    exc2 = ExceptionModel(
        organization_id=org_id,
        workspace_id=workspace_id,
        reconciliation_run_id=run_id,
        category="ambiguous",
        transaction_id=txns[5].id,  # PAY-003
        status="proposed",
        assigned_reviewer_id=user_id,
        details={"candidates": ["txn1", "txn2"]},
    )
    # amount_mismatch: REF-001
    exc3 = ExceptionModel(
        organization_id=org_id,
        workspace_id=workspace_id,
        reconciliation_run_id=run_id,
        category="amount_mismatch",
        transaction_id=txns[6].id,  # REF-001
        status="resolved",
        details={"expected": "100.00", "actual": "50.00"},
    )
    # duplicate: SET-001 (simulate duplicate via import_row)
    batch2 = ImportBatch(
        organization_id=org_id,
        workspace_id=workspace_id,
        source_name="settlements",
        file_size_bytes=100,
        file_checksum=f"dummy-duplicate-{uuid.uuid4()}",
        status="completed",
        rows_total=1,
        rows_processed=1,
    )
    db.add(batch2)
    db.flush()
    imp_row = ImportRow(
        organization_id=org_id,
        import_batch_id=batch2.id,
        row_number=5,
        payload={"external_id": "SET-001", "amount": "250.00"},
        validation_status="DUPLICATE_IN_FILE",
    )
    db.add(imp_row)
    db.flush()
    exc4 = ExceptionModel(
        organization_id=org_id,
        workspace_id=workspace_id,
        reconciliation_run_id=run_id,
        category="duplicate",
        import_row_id=imp_row.id,
        status="open",
        details={"first_row": 1},
    )
    # unmatched fee
    exc5 = ExceptionModel(
        organization_id=org_id,
        workspace_id=workspace_id,
        reconciliation_run_id=run_id,
        category="unmatched",
        transaction_id=txns[8].id,  # FEE-001
        status="open",
    )
    db.add_all([exc1, exc2, exc3, exc4, exc5])
    db.commit()

    exception_ids = [exc1.id, exc2.id, exc3.id, exc4.id, exc5.id]
    return run_id, match_ids, exception_ids


class TestListReconciliationRuns:
    def test_list_runs_requires_auth(self):
        client = TestClient(app)
        response = client.get(f"/api/v1/workspaces/{uuid.uuid4()}/reconciliation-runs")
        assert response.status_code == 401

    def test_list_runs_404_for_unknown_workspace(self):
        owner, _ = _signed_in_client()
        response = owner.get(f"/api/v1/workspaces/{uuid.uuid4()}/reconciliation-runs")
        assert response.status_code == 404

    def test_list_runs_404_for_other_org_workspace(self):
        owner, _ = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        attacker, _ = _signed_in_client()
        _create_org(attacker)
        response = attacker.get(f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs")
        assert response.status_code == 404

    def test_list_runs_empty(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        response = owner.get(f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_runs_with_data(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        org_id = uuid.UUID(org["id"])
        ws_id = uuid.UUID(workspace["id"])
        user_id = uuid.UUID(owner_user["id"])

        with get_session_factory()() as db:
            _seed_run_with_data(db, org_id, ws_id, user_id, 1)
            _seed_run_with_data(db, org_id, ws_id, user_id, 2)

        response = owner.get(f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs")
        assert response.status_code == 200
        runs = response.json()
        assert len(runs) == 2
        # Newest first
        assert runs[0]["id"] != runs[1]["id"]
        for run in runs:
            assert run["status"] == "completed"
            assert run["rule_version"] == "v1"
            assert run["tolerance_hours"] == 24
            assert run["matches_count"] == 2
            assert run["exceptions_count"] == 5
            assert run["started_at"] is not None
            assert run["completed_at"] is not None

    def test_list_runs_pagination_limit(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        org_id = uuid.UUID(org["id"])
        ws_id = uuid.UUID(workspace["id"])
        user_id = uuid.UUID(owner_user["id"])

        with get_session_factory()() as db:
            for i in range(3):
                _seed_run_with_data(db, org_id, ws_id, user_id, i + 1)

        response = owner.get(
            f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs",
            params={"limit": 2},
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

        response = owner.get(
            f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs",
            params={"limit": 2, "offset": 2},
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_runs_limit_validation(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])

        response = owner.get(
            f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs", params={"limit": 0}
        )
        assert response.status_code == 422

        response = owner.get(
            f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs", params={"limit": 101}
        )
        assert response.status_code == 422

        response = owner.get(
            f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs", params={"offset": -1}
        )
        assert response.status_code == 422

    def test_both_roles_can_read(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        analyst, analyst_user = _add_analyst(owner, org["id"])
        org_id = uuid.UUID(org["id"])
        ws_id = uuid.UUID(workspace["id"])
        user_id = uuid.UUID(owner_user["id"])

        with get_session_factory()() as db:
            _seed_run_with_data(db, org_id, ws_id, user_id)

        for client in [owner, analyst]:
            response = client.get(f"/api/v1/workspaces/{workspace['id']}/reconciliation-runs")
            assert response.status_code == 200
            assert len(response.json()) == 1


class TestListMatches:
    def test_list_matches_requires_auth(self):
        client = TestClient(app)
        response = client.get(f"/api/v1/reconciliation-runs/{uuid.uuid4()}/matches")
        assert response.status_code == 401

    def test_list_matches_404_for_unknown_run(self):
        owner, _ = _signed_in_client()
        response = owner.get(f"/api/v1/reconciliation-runs/{uuid.uuid4()}/matches")
        assert response.status_code == 404

    def test_list_matches_404_for_other_org_run(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
        attacker, _ = _signed_in_client()
        _create_org(attacker)
        response = attacker.get(f"/api/v1/reconciliation-runs/{run_id}/matches")
        assert response.status_code == 404

    def test_list_matches_with_data(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"]), 1
            )

        response = owner.get(f"/api/v1/reconciliation-runs/{run_id}/matches")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        # Check first match (exact_id)
        m1 = next(m for m in data if m["rule"] == "exact_id")
        assert m1["left_transaction"]["source_name"] == "orders"
        assert m1["left_transaction"]["external_id"] == "ORD-001-1"
        assert m1["left_transaction"]["amount"] == "100.0000"
        assert m1["right_transaction"]["source_name"] == "payments"
        assert m1["right_transaction"]["external_id"] == "PAY-001-1"
        assert m1["right_transaction"]["amount"] == "100.0000"

        # Check second match (amount_currency_time)
        m2 = next(m for m in data if m["rule"] == "amount_currency_time")
        assert m2["left_transaction"]["source_name"] == "orders"
        assert m2["left_transaction"]["external_id"] == "ORD-002-1"
        assert m2["left_transaction"]["amount"] == "200.0000"
        assert m2["right_transaction"]["source_name"] == "payments"
        assert m2["right_transaction"]["external_id"] == "PAY-002-1"
        assert m2["right_transaction"]["amount"] == "200.0000"

    def test_list_matches_filter_by_rule(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/matches", params={"rule": "exact_id"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["rule"] == "exact_id"

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/matches", params={"rule": "amount_currency_time"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["rule"] == "amount_currency_time"

    def test_list_matches_invalid_rule(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/matches", params={"rule": "invalid"}
        )
        assert response.status_code == 422

    def test_list_matches_pagination(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(f"/api/v1/reconciliation-runs/{run_id}/matches", params={"limit": 1})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_both_roles_can_read(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        analyst, analyst_user = _add_analyst(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        for client in [owner, analyst]:
            response = client.get(f"/api/v1/reconciliation-runs/{run_id}/matches")
            assert response.status_code == 200
            assert len(response.json()) == 2


class TestListExceptions:
    def test_list_exceptions_requires_auth(self):
        client = TestClient(app)
        response = client.get(f"/api/v1/reconciliation-runs/{uuid.uuid4()}/exceptions")
        assert response.status_code == 401

    def test_list_exceptions_404_for_other_org(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
        attacker, _ = _signed_in_client()
        _create_org(attacker)
        response = attacker.get(f"/api/v1/reconciliation-runs/{run_id}/exceptions")
        assert response.status_code == 404

    def test_list_exceptions_with_data(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(f"/api/v1/reconciliation-runs/{run_id}/exceptions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5

        # Check ordering: category, created_at, id
        categories = [e["category"] for e in data]
        assert categories == ["ambiguous", "amount_mismatch", "duplicate", "unmatched", "unmatched"]

        # Check transaction summary for unmatched
        unmatched = [e for e in data if e["category"] == "unmatched"]
        for exc in unmatched:
            assert exc["transaction"] is not None
            assert exc["transaction"]["source_name"] in ("orders", "fees")
            assert exc["import_row"] is None

        # Check import_row for duplicate
        duplicate = next(e for e in data if e["category"] == "duplicate")
        assert duplicate["transaction"] is None
        assert duplicate["import_row"] is not None
        assert duplicate["import_row"]["row_number"] == 5

    def test_list_exceptions_filter_category(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"category": "unmatched"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(e["category"] == "unmatched" for e in data)

    def test_list_exceptions_filter_status(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"status": "open"}
        )
        assert response.status_code == 200
        data = response.json()
        assert all(e["status"] == "open" for e in data)

    def test_list_exceptions_filter_source_name(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"source_name": "orders"}
        )
        assert response.status_code == 200
        data = response.json()
        assert all(e["transaction"]["source_name"] == "orders" for e in data if e["transaction"])

    def test_list_exceptions_search_q(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"]), 1
            )

        # Case-insensitive search
        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"q": "ord-003-1"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["transaction"]["external_id"] == "ORD-003-1"

        # Search with % and _ escaped
        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"q": "ORD%"}
        )
        assert response.status_code == 200
        data = response.json()
        # Should match literal "ORD%" not pattern - none should match
        assert len(data) == 0

    def test_list_exceptions_search_escapes_percent_and_underscore(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"]), 1
            )

        # The existing data has ORD-001-1, ORD-002-1, ORD-003-1
        # Search for "ORD_" should match literally (underscore), not as wildcard
        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"q": "ORD_"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0  # No external_id is literally "ORD_"

    def test_list_exceptions_pagination(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        response = owner.get(
            f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"limit": 2, "offset": 1}
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_both_roles_can_read(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        analyst, analyst_user = _add_analyst(owner, org["id"])
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        for client in [owner, analyst]:
            response = client.get(f"/api/v1/reconciliation-runs/{run_id}/exceptions")
            assert response.status_code == 200
            assert len(response.json()) == 5


class TestGetException:
    def test_get_exception_requires_auth(self):
        client = TestClient(app)
        response = client.get(f"/api/v1/exceptions/{uuid.uuid4()}")
        assert response.status_code == 401

    def test_get_exception_404_for_unknown(self):
        owner, _ = _signed_in_client()
        response = owner.get(f"/api/v1/exceptions/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_get_exception_404_for_other_org(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        exc_id: uuid.UUID
        with get_session_factory()() as db:
            _, _, exception_ids = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
            exc_id = exception_ids[0]
        attacker, _ = _signed_in_client()
        _create_org(attacker)
        response = attacker.get(f"/api/v1/exceptions/{exc_id}")
        assert response.status_code == 404

    def test_get_exception_with_transaction(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        exc_id: uuid.UUID
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, exception_ids = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
            # Get the unmatched exception with transaction (ORD-003 is the first unmatched)
            # We need to query to find which exception has transaction
            exc = (
                db.execute(
                    select(ExceptionModel).where(
                        ExceptionModel.reconciliation_run_id == run_id,
                        ExceptionModel.category == "unmatched",
                        ExceptionModel.transaction_id.is_not(None),
                    )
                )
                .scalars()
                .first()
            )
            exc_id = exc.id

        response = owner.get(f"/api/v1/exceptions/{exc_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(exc_id)
        assert data["category"] == "unmatched"
        assert data["transaction"] is not None
        assert data["transaction"]["source_name"] == "orders"
        assert data["import_row"] is None
        assert data["reconciliation_run_id"] == str(run_id)

    def test_get_exception_with_import_row(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        exc_id: uuid.UUID
        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, exception_ids = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
            # Find the duplicate exception
            exc = (
                db.execute(
                    select(ExceptionModel).where(
                        ExceptionModel.reconciliation_run_id == run_id,
                        ExceptionModel.category == "duplicate",
                    )
                )
                .scalars()
                .first()
            )
            exc_id = exc.id

        response = owner.get(f"/api/v1/exceptions/{exc_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(exc_id)
        assert data["category"] == "duplicate"
        assert data["transaction"] is None
        assert data["import_row"] is not None
        assert data["import_row"]["row_number"] == 5
        assert "batch_id" in data["import_row"]
        assert data["reconciliation_run_id"] == str(run_id)

    def test_both_roles_can_read(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])
        analyst, analyst_user = _add_analyst(owner, org["id"])
        exc_id: uuid.UUID
        with get_session_factory()() as db:
            _, _, exception_ids = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )
            exc_id = exception_ids[0]

        for client in [owner, analyst]:
            response = client.get(f"/api/v1/exceptions/{exc_id}")
            assert response.status_code == 200
            assert response.json()["id"] == str(exc_id)


class TestNPlusOneGuard:
    """Guard against N+1 queries - the number of SQL statements should stay constant."""

    def test_list_matches_no_n_plus_one(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])

        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        # Count queries using SQLAlchemy event listener
        from sqlalchemy import event

        from app.db import get_engine

        query_count = 0

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            query_count += 1

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            response = owner.get(
                f"/api/v1/reconciliation-runs/{run_id}/matches", params={"limit": 50}
            )
            assert response.status_code == 200
            # Should be a small constant number of queries
            # (1 for run access + 1 for matches with joins)
            # The exact count depends on SQLAlchemy but should not grow with limit
            print(f"Query count for matches: {query_count}")
            # With joinedload, we expect ~2-3 queries total
            assert query_count <= 5, f"Too many queries: {query_count}"
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)

    def test_list_exceptions_no_n_plus_one(self):
        owner, owner_user = _signed_in_client()
        org = _create_org(owner)
        workspace = _create_workspace(owner, org["id"])

        run_id: uuid.UUID
        with get_session_factory()() as db:
            run_id, _, _ = _seed_run_with_data(
                db, uuid.UUID(org["id"]), uuid.UUID(workspace["id"]), uuid.UUID(owner_user["id"])
            )

        from sqlalchemy import event

        from app.db import get_engine

        query_count = 0

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            query_count += 1

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", before_cursor_execute)
        try:
            response = owner.get(
                f"/api/v1/reconciliation-runs/{run_id}/exceptions", params={"limit": 50}
            )
            assert response.status_code == 200
            print(f"Query count for exceptions: {query_count}")
            # With outerjoin, we expect ~2-3 queries total
            assert query_count <= 5, f"Too many queries: {query_count}"
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor_execute)
