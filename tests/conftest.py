"""Shared pytest fixtures for the TRACE test suite.

The suite runs against a real PostgreSQL instance (default
``postgresql+psycopg://trace:trace@localhost:5432/trace_test``, override with
``TRACE_TEST_DATABASE_URL``). It uses ``httpx.MockTransport`` so no requests
ever leave the machine toward GitHub.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import pytest
from app import _loop
from app.config import Settings
from app.database import build_session_factory
from app.github import GitHubClient
from app.models import Developer, GithubEvent, Repository, SyncJob
from app.schema import ensure_database_schema
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

_loop.configure_asyncio_policy()

TEST_DATABASE_URL = os.getenv(
    "TRACE_TEST_DATABASE_URL",
    "postgresql+psycopg://trace:trace@localhost:5432/trace_test",
)

USERNAME = "octocat"


def now() -> str:
    return datetime.now(UTC).isoformat()


def make_user(username: str = USERNAME) -> dict:
    return {
        "id": 1,
        "login": username,
        "name": "Mona Octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
        "html_url": f"https://github.com/{username}",
        "company": "GitHub",
        "location": "San Francisco",
        "bio": "A friendly cat.",
        "followers": 10,
        "following": 5,
        "public_repos": 3,
    }


def make_repo(idx: int, username: str = USERNAME) -> dict:
    languages = ["Python", "Go", "Rust", "JavaScript"][idx % 4]
    topics = ["api", "backend", "docker", "data", "testing", "docs"][idx % 6]
    return {
        "id": 100 + idx,
        "name": f"repo-{idx}",
        "full_name": f"{username}/repo-{idx}",
        "description": f"Repository {idx} for building {topics} services.",
        "html_url": f"https://github.com/{username}/repo-{idx}",
        "homepage": None,
        "default_branch": "main",
        "language": languages,
        "topics": [topics],
        "fork": False,
        "stargazers_count": idx * 2,
        "forks_count": idx,
        "open_issues_count": 1,
        "watchers_count": idx * 2,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "pushed_at": f"2026-08-0{idx + 1}T12:00:00Z",
    }


def make_event(idx: int, username: str = USERNAME) -> dict:
    event_types = [
        ("PushEvent", {"ref": "refs/heads/main"}),
        ("PullRequestEvent", {"pull_request": {"number": 7}}),
        ("IssuesEvent", {"issue": {"number": 3}}),
        ("ReleaseEvent", {"release": {"tag_name": "v1.2.0"}}),
        ("CreateEvent", {"ref_type": "repository", "ref": "repo-5"}),
    ]
    event_type, payload = event_types[idx % len(event_types)]
    return {
        "id": f"30000000{idx}",
        "type": event_type,
        "created_at": f"2026-08-0{idx + 1}T10:00:00Z",
        "actor": {"login": username},
        "repo": {"id": 101, "name": f"{username}/repo-{idx % 3}"},
        "payload": payload,
    }


def make_github_handler(
    *,
    user: dict | None = None,
    repos: list[dict] | None = None,
    events: list[dict] | None = None,
    languages: dict | None = None,
    unavailable_paths: set[str] | None = None,
    username: str = USERNAME,
):
    """Build an ``httpx.MockTransport`` handler serving canned GitHub data."""
    user = user if user is not None else make_user(username)
    repos = repos if repos is not None else [
        make_repo(i, username) for i in range(3)
    ]
    events = events if events is not None else [
        make_event(i, username) for i in range(4)
    ]
    languages = languages if languages is not None else {"Python": 1000, "HTML": 200}
    unavailable = unavailable_paths or set()

    def _paginate(items: list[dict], request: httpx.Request) -> list[dict]:
        page = int(request.url.params.get("page", "1"))
        per_page = int(request.url.params.get("per_page", "30"))
        start = (page - 1) * per_page
        return items[start : start + per_page]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in unavailable:
            return httpx.Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"Retry-After": "0", "X-RateLimit-Remaining": "0"},
            )

        if path == f"/users/{username}":
            return httpx.Response(200, json=user)
        if path == f"/users/{username}/repos":
            return httpx.Response(200, json=_paginate(repos, request))
        if path == f"/users/{username}/events":
            return httpx.Response(200, json=_paginate(events, request))
        if path.startswith(f"/repos/{username}/") and path.endswith("/languages"):
            return httpx.Response(200, json=languages)
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


@pytest.fixture
def test_settings() -> Settings:
    return Settings(database_url=TEST_DATABASE_URL, github_token=None)


@pytest.fixture(scope="session")
async def test_engine():
    # NullPool so connections are never shared across pytest event loops.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    await ensure_database_schema(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(test_engine):
    factory = build_session_factory(test_engine)
    async with test_engine.begin() as conn:
        for model in (GithubEvent, Repository, SyncJob, Developer):
            await conn.execute(delete(model))
    return factory


@pytest.fixture
def make_client():
    """Factory for GitHubClient instances backed by MockTransport."""

    def _make(
        client: httpx.AsyncClient, settings: Settings | None = None
    ) -> GitHubClient:
        return GitHubClient(settings or Settings(), client=client)

    return _make


@pytest.fixture
def mock_github_client(test_settings) -> GitHubClient:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(make_github_handler()),
        base_url="https://api.github.com",
    )
    return GitHubClient(test_settings, client=client)


@pytest.fixture
def ingestion_service(session_factory, mock_github_client):
    from app.services.ingestion import IngestionService

    return IngestionService(mock_github_client, session_factory)


@pytest.fixture
def app(session_factory, mock_github_client):
    from app.main import create_app

    app = create_app(
        session_factory=session_factory,
        github_client=mock_github_client,
    )
    yield app


@pytest.fixture
def now_utc() -> datetime:
    return datetime.now(UTC)


def async_test_client(app) -> httpx.AsyncClient:
    """Return an AsyncClient wired to ``app`` via the ASGI transport."""
    from httpx import ASGITransport

    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )