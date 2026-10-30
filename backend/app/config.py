from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SESSION_SECRET = "dev-only-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/reconcile"
    database_direct_url: str | None = None
    session_secret: str = DEFAULT_SESSION_SECRET
    env: str = "development"
    web_origin: str = "http://localhost:3000"
    max_upload_mb: int = 10
    max_import_rows: int = 50000
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None

    @model_validator(mode="after")
    def check_production_secret(self):
        weak = len(self.session_secret) < 32 or self.session_secret == DEFAULT_SESSION_SECRET
        if self.env == "production" and weak:
            raise ValueError(
                "SESSION_SECRET must be at least 32 characters and not the default "
                "when ENV is production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
