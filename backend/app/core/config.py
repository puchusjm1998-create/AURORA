"""Application configuration.

All values are read from environment variables (or a local ``.env`` file).
Secrets are never hard-coded for production: the application refuses to boot
when ``ENVIRONMENT=production`` and the default development secret is in use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

DEV_JWT_SECRET = "aurora-dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Identity -----------------------------------------------------------
    app_name: str = "AURORA LOGISTICS AI"
    app_version: str = "0.1.0"
    environment: str = "development"  # development | staging | production

    # --- Database -----------------------------------------------------------
    # PostgreSQL in production/staging, SQLite is supported for local dev & tests.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'aurora.db').as_posix()}"
    database_echo: bool = False

    # --- Security -----------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480  # one working shift
    cookie_name: str = "aurora_session"
    cookie_secure: bool = False
    login_max_attempts: int = 8
    login_window_seconds: int = 300

    # --- CORS (only needed when the frontend runs on another origin, i.e. next dev)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Storage ------------------------------------------------------------
    storage_dir: Path = BACKEND_DIR / "data" / "storage"
    max_upload_mb: int = 25

    # --- Domain -------------------------------------------------------------
    warehouse_timezone: str = "Europe/Madrid"
    demo_mode: bool = False

    # --- Bootstrap ----------------------------------------------------------
    run_migrations: bool = True
    bootstrap: bool = True

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        # SQLAlchemy 2.x uses postgresql+psycopg:// for the psycopg driver.
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "staging"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def assert_safe(self) -> None:
        """Fail fast on unsafe production configuration."""
        if self.is_production:
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise RuntimeError(
                    "JWT_SECRET must be set to a strong value (>=32 chars) in production."
                )
            if self.is_sqlite:
                raise RuntimeError("SQLite is not allowed in production. Use PostgreSQL.")
            if not self.cookie_secure:
                raise RuntimeError("COOKIE_SECURE must be true in production (HTTPS only).")


@lru_cache
def get_settings() -> Settings:
    return Settings()
