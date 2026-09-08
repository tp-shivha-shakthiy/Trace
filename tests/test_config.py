"""Tests for configuration loading and normalization."""

from app.config import Settings


def test_default_database_url():
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://trace:trace@localhost:5432/trace"


def test_psycopg_url_passthrough():
    url = "postgresql+psycopg://u:p@db:5432/db"
    assert Settings(database_url=url, _env_file=None).database_url == url


def test_plain_postgres_url_is_normalized():
    settings = Settings(
        database_url="postgres://u:p@db:5432/db",
        _env_file=None,
    )
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/db"


def test_plain_postgresql_url_is_normalized():
    settings = Settings(
        database_url="postgresql://u:p@db:5432/db",
        _env_file=None,
    )
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/db"