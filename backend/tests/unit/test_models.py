from app.models import Base


def test_metadata_has_the_five_identity_tables():
    assert set(Base.metadata.tables) == {
        "users",
        "organizations",
        "organization_memberships",
        "workspaces",
        "sessions",
    }


def test_constraint_names_follow_the_convention():
    users = Base.metadata.tables["users"]

    constraint_names = {constraint.name for constraint in users.constraints}
    index_names = {index.name: index for index in users.indexes}

    assert {"pk_users", "uq_users_google_sub", "ck_users_password_or_google_sub"} <= (
        constraint_names
    )
    assert index_names["ix_users_email_lower"].unique
