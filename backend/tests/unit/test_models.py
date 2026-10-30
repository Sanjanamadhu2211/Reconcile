import sqlalchemy as sa

from app.models import Base

NEW_TABLES = (
    "import_batches",
    "import_rows",
    "transactions",
    "reconciliation_runs",
    "matches",
    "exceptions",
)


def _constraint_names(table_name: str) -> set[str]:
    return {constraint.name for constraint in Base.metadata.tables[table_name].constraints}


def _index_names(table_name: str) -> set[str]:
    return {index.name for index in Base.metadata.tables[table_name].indexes}


def test_metadata_has_the_eleven_tables():
    assert set(Base.metadata.tables) == {
        "users",
        "organizations",
        "organization_memberships",
        "workspaces",
        "sessions",
        "import_batches",
        "import_rows",
        "transactions",
        "reconciliation_runs",
        "matches",
        "exceptions",
    }


def test_constraint_names_follow_the_convention():
    assert {"pk_users", "uq_users_google_sub", "ck_users_password_or_google_sub"} <= (
        _constraint_names("users")
    )
    assert "ix_users_email_lower" in _index_names("users")
    assert {
        "ck_import_batches_source_name",
        "ck_import_batches_status",
        "ck_import_rows_validation_status",
        "ck_import_rows_error_code",
        "ck_transactions_source_name",
        "ck_transactions_transaction_type",
        "ck_transactions_currency_upper",
        "ck_reconciliation_runs_status",
        "ck_reconciliation_runs_tolerance_hours",
        "ck_matches_rule",
        "ck_matches_left_ne_right",
        "ck_exceptions_category",
        "ck_exceptions_status",
        "ck_exceptions_transaction_or_import_row",
    } <= (
        _constraint_names("import_batches")
        | _constraint_names("import_rows")
        | _constraint_names("transactions")
        | _constraint_names("reconciliation_runs")
        | _constraint_names("matches")
        | _constraint_names("exceptions")
    )


def test_new_tables_are_tenant_scoped():
    for table_name in NEW_TABLES:
        organization_id = Base.metadata.tables[table_name].c.organization_id

        assert not organization_id.nullable
        assert organization_id.index
        assert f"ix_{table_name}_organization_id" in _index_names(table_name)


def test_unique_constraints_exist():
    assert "uq_import_batches_workspace_id_file_checksum" in _constraint_names("import_batches")
    assert "uq_import_rows_import_batch_id_row_number" in _constraint_names("import_rows")
    assert "uq_transactions_workspace_id_source_name_external_id" in _constraint_names(
        "transactions"
    )
    assert "ix_import_batches_workspace_id_idempotency_key" in _index_names("import_batches")
    assert "uq_matches_run_id_left_transaction_id" in _constraint_names("matches")
    assert "uq_matches_run_id_right_transaction_id" in _constraint_names("matches")


def test_amount_is_numeric_19_4():
    amount = Base.metadata.tables["transactions"].c.amount

    assert isinstance(amount.type, sa.Numeric)
    assert (amount.type.precision, amount.type.scale) == (19, 4)


def test_partial_unique_indexes_on_exceptions():
    assert "ix_exceptions_run_id_transaction_id" in _index_names("exceptions")
    assert "ix_exceptions_run_id_import_row_id" in _index_names("exceptions")
