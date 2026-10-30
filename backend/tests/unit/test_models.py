import sqlalchemy as sa

from app.models import Base

NEW_TABLES = ("import_batches", "import_rows", "transactions")


def _constraint_names(table_name: str) -> set[str]:
    return {constraint.name for constraint in Base.metadata.tables[table_name].constraints}


def _index_names(table_name: str) -> set[str]:
    return {index.name for index in Base.metadata.tables[table_name].indexes}


def test_metadata_has_the_eight_tables():
    assert set(Base.metadata.tables) == {
        "users",
        "organizations",
        "organization_memberships",
        "workspaces",
        "sessions",
        "import_batches",
        "import_rows",
        "transactions",
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
    } <= (
        _constraint_names("import_batches")
        | _constraint_names("import_rows")
        | _constraint_names("transactions")
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


def test_amount_is_numeric_19_4():
    amount = Base.metadata.tables["transactions"].c.amount

    assert isinstance(amount.type, sa.Numeric)
    assert (amount.type.precision, amount.type.scale) == (19, 4)
