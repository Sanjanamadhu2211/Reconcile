import pytest
from pydantic import ValidationError

from app.config import DEFAULT_SESSION_SECRET, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("DATABASE_URL", "SESSION_SECRET", "ENV"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_load():
    settings = Settings(_env_file=None)

    assert (
        settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/reconcile"
    )
    assert settings.session_secret == DEFAULT_SESSION_SECRET
    assert settings.env == "development"
    assert settings.max_upload_mb == 10
    assert settings.google_client_id is None


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError, match="SESSION_SECRET must be at least 32 characters"):
        Settings(_env_file=None, env="production")


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError, match="SESSION_SECRET must be at least 32 characters"):
        Settings(_env_file=None, env="production", session_secret="too-short")


def test_production_accepts_long_secret():
    settings = Settings(_env_file=None, env="production", session_secret="x" * 32)

    assert settings.session_secret == "x" * 32
