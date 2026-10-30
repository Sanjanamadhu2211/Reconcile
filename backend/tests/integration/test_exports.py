import csv
import io
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, insert

from app.db import get_engine, get_session_factory
from app.main import app
from app.models import Exception as ExceptionModel
from app.models import ImportBatch, ImportRow, Match, ReconciliationRun, Transaction
from app.routers import exports

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"
OCCURRED = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
OCCURRED_TEXT = "2024-01-15T10:30:00Z"
EXPORTS = ["matches.csv", "exceptions.csv", "import-errors.csv"]
MATCH_HEADER = [
    "run_id",
    "rule",
    "left_source",
    "left_external_id",
    "left_amount",
    "left_currency",
    "left_occurred_at",
    "right_source",
    "right_external_id",
    "right_amount",
    "right_currency",
    "right_occurred_at",
]
EXCEPTION_HEADER = [
    "run_id",
    "exception_id",
    "category",
    "status",
    "source_name",
    "external_id",
    "amount",
    "currency",
    "occurred_at",
    "row_number",
    "version",
]
IMPORT_ERROR_HEADER = [
    "batch_id",
    "filename",
    "source_name",
    "row_number",
    "validation_status",
    "error_code",
    "error_detail",
]


def _session():
    # ids stay readable after the commit, so tests can build URLs from them
    return get_session_factory()(expire_on_commit=False)


def _unique(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4()}"


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


def _signed_in() -> tuple[TestClient, dict]:
    client = TestClient(app)
    registered = client.post(
        "/api/v1/auth/register", json={"email": f"{_unique()}@example.com", "password": PASSWORD}
    )
    assert registered.status_code == 201
    return client, registered.json()


def _workspace(client: TestClient, org_id: str, name: str) -> dict:
    response = client.post(
        "/api/v1/workspaces", json={"organization_id": org_id, "name": name}, headers=_csrf(client)
    )
    assert response.status_code == 201
    return response.json()


def _owner(workspace_name: str | None = None) -> SimpleNamespace:
    client, user = _signed_in()
    org = client.post(
        "/api/v1/organizations", json={"name": f"Org {_unique()}"}, headers=_csrf(client)
    ).json()
    workspace = _workspace(client, org["id"], workspace_name or f"Ledger {_unique()}")
    return SimpleNamespace(
        client=client,
        user_id=uuid.UUID(user["id"]),
        org_id=uuid.UUID(org["id"]),
        workspace_id=uuid.UUID(workspace["id"]),
        workspace_name=workspace["name"],
    )


@pytest.fixture
def owner():
    return _owner()


@pytest.fixture
def attacker():
    return _owner()


def _url(workspace_id: uuid.UUID, export: str) -> str:
    return f"/api/v1/workspaces/{workspace_id}/exports/{export}"


def _rows(response) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.text)))


def _batch(db, owner, filename: str = "orders.csv") -> ImportBatch:
    batch = ImportBatch(
        organization_id=owner.org_id,
        workspace_id=owner.workspace_id,
        source_name="orders",
        filename=filename,
        file_size_bytes=1,
        file_checksum=_unique(),
        status="completed",
    )
    db.add(batch)
    db.flush()
    return batch


def _transaction(db, owner, batch, source: str, external_id: str, amount: str) -> Transaction:
    txn = Transaction(
        organization_id=owner.org_id,
        workspace_id=owner.workspace_id,
        import_batch_id=batch.id,
        source_name=source,
        external_id=external_id,
        amount=Decimal(amount),
        currency="USD",
        transaction_type=source.rstrip("s"),
        occurred_at=OCCURRED,
    )
    db.add(txn)
    db.flush()
    return txn


def _run(db, owner, status: str = "completed", completed_at: datetime | None = OCCURRED):
    run = ReconciliationRun(
        organization_id=owner.org_id,
        workspace_id=owner.workspace_id,
        rule_version="v1",
        status=status,
        tolerance_hours=24,
        created_by=owner.user_id,
        completed_at=completed_at,
    )
    db.add(run)
    db.flush()
    return run


def _match(db, owner, run, batch, left_id: str, right_id: str, amount: str = "100.0000"):
    left = _transaction(db, owner, batch, "orders", left_id, amount)
    right = _transaction(db, owner, batch, "payments", right_id, amount)
    db.add(
        Match(
            organization_id=owner.org_id,
            reconciliation_run_id=run.id,
            rule="exact_id",
            left_transaction_id=left.id,
            right_transaction_id=right.id,
        )
    )
    db.flush()


def _exception(db, owner, run, txn: Transaction) -> ExceptionModel:
    exception = ExceptionModel(
        organization_id=owner.org_id,
        workspace_id=owner.workspace_id,
        reconciliation_run_id=run.id,
        category="unmatched",
        transaction_id=txn.id,
        status="open",
    )
    db.add(exception)
    db.flush()
    return exception


def _import_row(db, batch, row_number: int, status: str, code=None, detail=None) -> ImportRow:
    row = ImportRow(
        organization_id=batch.organization_id,
        import_batch_id=batch.id,
        row_number=row_number,
        payload={},
        validation_status=status,
        error_code=code,
        error_detail=detail,
    )
    db.add(row)
    db.flush()
    return row


def _add_analyst(owner) -> TestClient:
    analyst, analyst_user = _signed_in()
    added = owner.client.post(
        f"/api/v1/organizations/{owner.org_id}/members",
        json={"email": analyst_user["email"], "role": "analyst"},
        headers=_csrf(owner.client),
    )
    assert added.status_code == 201
    return analyst


def test_matches_csv_has_header_and_one_row_per_match(owner):
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        _match(db, owner, run, batch, "ORD-1", "PAY-1", "149.9900")
        db.commit()

    response = owner.client.get(_url(owner.workspace_id, "matches.csv"))

    assert response.status_code == 200
    assert _rows(response) == [
        MATCH_HEADER,
        [
            str(run.id),
            "exact_id",
            "orders",
            "ORD-1",
            "149.9900",
            "USD",
            OCCURRED_TEXT,
            "payments",
            "PAY-1",
            "149.9900",
            "USD",
            OCCURRED_TEXT,
        ],
    ]


def test_exceptions_csv_has_header_and_row_content(owner):
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        txn = _transaction(db, owner, batch, "orders", "ORD-9", "-12.5000")
        exception = _exception(db, owner, run, txn)
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "exceptions.csv")))

    assert rows == [
        EXCEPTION_HEADER,
        [
            str(run.id),
            str(exception.id),
            "unmatched",
            "open",
            "orders",
            "ORD-9",
            "-12.5000",
            "USD",
            OCCURRED_TEXT,
            "",
            "1",
        ],
    ]


def test_exceptions_csv_carries_the_row_number_of_duplicates(owner):
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        row = _import_row(db, batch, 7, "DUPLICATE_IN_FILE", "DUPLICATE_IN_FILE")
        db.add(
            ExceptionModel(
                organization_id=owner.org_id,
                workspace_id=owner.workspace_id,
                reconciliation_run_id=run.id,
                category="duplicate",
                import_row_id=row.id,
                status="open",
            )
        )
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "exceptions.csv")))

    assert rows[1][2:4] == ["duplicate", "open"]
    assert rows[1][9] == "7"


def test_import_errors_csv_lists_only_non_valid_rows(owner):
    with _session() as db:
        batch = _batch(db, owner)
        _import_row(db, batch, 2, "VALID")
        _import_row(db, batch, 3, "BAD_AMOUNT", "BAD_AMOUNT", "not a number")
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "import-errors.csv")))

    assert rows == [
        IMPORT_ERROR_HEADER,
        [str(batch.id), "orders.csv", "orders", "3", "BAD_AMOUNT", "BAD_AMOUNT", "not a number"],
    ]


def test_import_errors_csv_respects_import_id(owner):
    with _session() as db:
        first = _batch(db, owner, filename="first.csv")
        second = _batch(db, owner, filename="second.csv")
        _import_row(db, first, 2, "BAD_AMOUNT", "BAD_AMOUNT")
        _import_row(db, second, 2, "BAD_CURRENCY", "BAD_CURRENCY")
        db.commit()

    response = owner.client.get(
        _url(owner.workspace_id, "import-errors.csv"), params={"import_id": str(second.id)}
    )

    assert [row[1] for row in _rows(response)[1:]] == ["second.csv"]


def test_amounts_keep_their_four_decimals(owner):
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        _match(db, owner, run, batch, "ORD-1", "PAY-1", "1500.5000")
        db.commit()

    row = _rows(owner.client.get(_url(owner.workspace_id, "matches.csv")))[1]

    assert row[4] == row[9] == "1500.5000"


def test_formula_like_external_ids_are_neutralised_and_parse_back_as_one_row(owner):
    external_ids = ["=cmd|' /C calc'!A0", "-1", "+x", "@x", "\tx"]
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        for external_id in external_ids:
            _match(db, owner, run, batch, external_id, _unique("PAY-"), "-5.0000")
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "matches.csv")))

    assert len(rows) == len(external_ids) + 1
    assert sorted(row[3] for row in rows[1:]) == sorted("'" + value for value in external_ids)
    assert {row[4] for row in rows[1:]} == {"-5.0000"}


def test_commas_quotes_and_newlines_round_trip(owner):
    external_id = 'ORD, "quoted"\nsecond line'
    with _session() as db:
        batch = _batch(db, owner, filename='a,"b".csv')
        run = _run(db, owner)
        _match(db, owner, run, batch, external_id, "PAY-1")
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "matches.csv")))

    assert len(rows) == 2
    assert rows[1][3] == external_id


def test_latest_completed_run_is_used_by_default(owner):
    with _session() as db:
        batch = _batch(db, owner)
        older = _run(db, owner, completed_at=datetime(2024, 1, 1, tzinfo=UTC))
        _match(db, owner, older, batch, "OLD-1", "OLD-PAY-1")
        latest = _run(db, owner, completed_at=datetime(2024, 2, 1, tzinfo=UTC))
        _match(db, owner, latest, batch, "NEW-1", "NEW-PAY-1")
        failed = _run(db, owner, status="failed", completed_at=None)
        _match(db, owner, failed, batch, "FAIL-1", "FAIL-PAY-1")
        running = _run(db, owner, status="running", completed_at=None)
        _match(db, owner, running, batch, "RUN-1", "RUN-PAY-1")
        db.commit()

    rows = _rows(owner.client.get(_url(owner.workspace_id, "matches.csv")))

    assert [row[0] for row in rows[1:]] == [str(latest.id)]
    assert rows[1][3] == "NEW-1"


def test_explicit_run_id_exports_that_run(owner):
    with _session() as db:
        batch = _batch(db, owner)
        first = _run(db, owner, completed_at=datetime(2024, 1, 1, tzinfo=UTC))
        _match(db, owner, first, batch, "OLD-1", "OLD-PAY-1")
        _match(db, owner, _run(db, owner), batch, "NEW-1", "NEW-PAY-1")
        db.commit()

    response = owner.client.get(
        _url(owner.workspace_id, "matches.csv"), params={"run_id": str(first.id)}
    )

    assert [row[3] for row in _rows(response)[1:]] == ["OLD-1"]


def test_run_from_another_workspace_or_organization_is_404(owner, attacker):
    other_workspace = _workspace(owner.client, str(owner.org_id), f"Second {_unique()}")
    with _session() as db:
        sibling = _run(
            db,
            SimpleNamespace(
                org_id=owner.org_id,
                workspace_id=uuid.UUID(other_workspace["id"]),
                user_id=owner.user_id,
            ),
        )
        foreign = _run(db, attacker)
        db.commit()
        run_ids = [sibling.id, foreign.id]

    for export in ["matches.csv", "exceptions.csv"]:
        for run_id in run_ids:
            response = owner.client.get(
                _url(owner.workspace_id, export), params={"run_id": str(run_id)}
            )
            assert response.status_code == 404


def test_no_completed_run_gives_a_header_only_csv(owner):
    with _session() as db:
        _run(db, owner, status="failed", completed_at=None)
        db.commit()

    matches = owner.client.get(_url(owner.workspace_id, "matches.csv"))
    exceptions = owner.client.get(_url(owner.workspace_id, "exceptions.csv"))

    assert matches.status_code == exceptions.status_code == 200
    assert _rows(matches) == [MATCH_HEADER]
    assert _rows(exceptions) == [EXCEPTION_HEADER]


def test_empty_workspace_gives_header_only_csvs(owner):
    responses = {export: owner.client.get(_url(owner.workspace_id, export)) for export in EXPORTS}

    assert {export: _rows(response) for export, response in responses.items()} == {
        "matches.csv": [MATCH_HEADER],
        "exceptions.csv": [EXCEPTION_HEADER],
        "import-errors.csv": [IMPORT_ERROR_HEADER],
    }


def test_repeated_exports_of_unchanged_data_are_byte_identical(owner):
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        for i in range(5):
            _match(db, owner, run, batch, f"ORD-{i}", f"PAY-{i}")
        db.commit()

    first = owner.client.get(_url(owner.workspace_id, "matches.csv"))
    second = owner.client.get(_url(owner.workspace_id, "matches.csv"))

    assert first.content == second.content


def test_response_headers(owner):
    response = owner.client.get(_url(owner.workspace_id, "import-errors.csv"))

    today = datetime.now(UTC).strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", owner.workspace_name.lower()).strip("-")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{slug}-import-errors-{today}.csv"'
    )


@pytest.mark.parametrize(
    "name, slug",
    [
        ("Ledger / Q1 2024!", "ledger-q1-2024"),
        ("Café ✓ Ledger", "caf-ledger"),
        ("../../etc", "etc"),
        ("✓✓", "workspace"),
    ],
)
def test_filename_slug_is_ascii_and_has_no_separators(name, slug):
    owner = _owner(name)

    response = owner.client.get(_url(owner.workspace_id, "matches.csv"))

    today = datetime.now(UTC).strftime("%Y%m%d")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{slug}-matches-{today}.csv"'
    )


@pytest.mark.parametrize("export", EXPORTS)
def test_another_organization_gets_404(export, owner, attacker):
    response = attacker.client.get(_url(owner.workspace_id, export))

    assert response.status_code == 404


@pytest.mark.parametrize("export", EXPORTS)
def test_anonymous_request_gets_401(export, owner):
    response = TestClient(app).get(_url(owner.workspace_id, export))

    assert response.status_code == 401


def test_any_member_of_the_organization_can_export(owner):
    analyst = _add_analyst(owner)

    responses = [analyst.get(_url(owner.workspace_id, export)) for export in EXPORTS]

    assert [response.status_code for response in responses] == [200, 200, 200]


@pytest.fixture
def big_run(owner):
    total = 20_000
    with _session() as db:
        batch = _batch(db, owner)
        run = _run(db, owner)
        transactions = [
            {
                "id": uuid.uuid4(),
                "organization_id": owner.org_id,
                "workspace_id": owner.workspace_id,
                "import_batch_id": batch.id,
                "source_name": "orders",
                "external_id": f"ORD-{i}",
                "amount": Decimal("1.0000"),
                "currency": "USD",
                "transaction_type": "order",
                "occurred_at": OCCURRED,
            }
            for i in range(total)
        ]
        db.execute(insert(Transaction), transactions)
        db.execute(
            insert(ExceptionModel),
            [
                {
                    "id": uuid.uuid4(),
                    "organization_id": owner.org_id,
                    "workspace_id": owner.workspace_id,
                    "reconciliation_run_id": run.id,
                    "category": "unmatched",
                    "transaction_id": txn["id"],
                    "status": "open",
                }
                for txn in transactions
            ],
        )
        db.commit()
    return run.id


def test_export_fetches_rows_only_as_the_body_is_read(owner, big_run):
    cursors = []

    def remember_cursor(conn, cursor, statement, parameters, context, executemany):
        cursors.append(cursor)

    event.listen(get_engine(), "after_cursor_execute", remember_cursor)
    try:
        body = exports._csv_body(EXCEPTION_HEADER, exports._exceptions_statement(big_run))
        next(body)
        next(body)
        rows_fetched = cursors[-1].rownumber
        rows_written = sum(1 for _ in body)
    finally:
        event.remove(get_engine(), "after_cursor_execute", remember_cursor)

    assert rows_fetched <= 2 * exports.BATCH_SIZE
    assert rows_written == 20_000 - 1


def test_closing_the_stream_releases_its_connection(owner, big_run):
    checked_out = get_engine().pool.checkedout()
    body = exports._csv_body(EXCEPTION_HEADER, exports._exceptions_statement(big_run))
    next(body)
    next(body)
    assert get_engine().pool.checkedout() == checked_out + 1

    body.close()

    assert get_engine().pool.checkedout() == checked_out
