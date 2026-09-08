"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for TRACE.

    Values are read from environment variables or a local ``.env`` file.
    See ``.env.example`` for the full list and descriptions.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TRACE"
    app_version: str = "0.3.0"

    api_v1_prefix: str = "/api/v1"

    # Async SQLAlchemy URL. Plain ``postgres://`` / ``postgresql://`` URLs
    # (as used by hosted providers such as Render) are normalized to the
    # ``postgresql+psycopg://`` driver automatically.
    database_url: str = "postgresql+psycopg://trace:trace@localhost:5432/trace"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgresql+psycopg://"):
            return value
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        return value

    # Optional GitHub Personal Access Token (fine-grained or classic).
    # Without a token the client is unauthenticated (60 req/hour IP limit).
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    github_timeout_seconds: float = 15.0
    github_retries: int = 2

    # Ingestion bounds keep a single sync bounded and demo-friendly.
    ingestion_events_per_page: int = 30
    ingestion_events_max_pages: int = 3
    ingestion_repos_per_page: int = 100
    ingestion_repos_max_pages: int = 2
    ingestion_language_repos_limit: int = 10

    # Number of background ingestion workers pulling from the in-process queue.
    sync_worker_concurrency: int = 2


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env vars are read once)."""
    return Settings()