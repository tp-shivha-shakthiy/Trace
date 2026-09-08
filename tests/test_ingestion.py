"""End-to-end ingestion tests: fetch -> normalize -> persist, idempotently."""

import httpx
from app.github import GitHubClient
from app.models import Developer, GithubEvent, Repository
from app.services.ingestion import IngestionService
from sqlalchemy import func, select
from tests.conftest import make_github_handler


async def test_ingest_developer_once(session_factory, ingestion_service):
    result = await ingestion_service.run("octocat")
    assert result.events_fetched == 4
    assert result.events_persisted == 4
    assert result.events_duplicates == 0
    assert result.repositories_synced == 3

    async with session_factory() as session:
        dev = await session.scalar(select(Developer))
        assert dev is not None
        assert dev.username == "octocat"

        repo_count = (
            await session.scalar(select(func.count()).select_from(Repository))
        )
        assert repo_count == 3

        event_count = (
            await session.scalar(select(func.count()).select_from(GithubEvent))
        )
        assert event_count == 4


async def test_ingest_is_idempotent(session_factory, ingestion_service):
    first = await ingestion_service.run("octocat")
    second = await ingestion_service.run("octocat")

    assert first.events_persisted == 4
    assert second.events_persisted == 0
    assert second.events_duplicates == 4

    async with session_factory() as session:
        event_count = (
            await session.scalar(select(func.count()).select_from(GithubEvent))
        )
        assert event_count == 4  # no duplicates on re-run

        repo_count = (
            await session.scalar(select(func.count()).select_from(Repository))
        )
        assert repo_count == 3


async def test_events_persist_payload_and_repo_link(session_factory, ingestion_service):
    await ingestion_service.run("octocat")
    async with session_factory() as session:
        events = list(await session.scalars(select(GithubEvent)))
        assert all(e.payload is not None for e in events)
        # At least one event should be linked to a known repository.
        assert any(e.repository_id is not None for e in events)


async def test_ingest_empty_events(session_factory, test_settings):
    handler = make_github_handler(events=[])
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    service = IngestionService(
        GitHubClient(test_settings, client=client), session_factory
    )
    result = await service.run("octocat")
    assert result.events_fetched == 0
    assert result.events_persisted == 0
    async with session_factory() as session:
        event_count = (
            await session.scalar(select(func.count()).select_from(GithubEvent))
        )
        assert event_count == 0


async def test_ingest_empty_repositories(session_factory, test_settings):
    handler = make_github_handler(repos=[], events=[])
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    service = IngestionService(
        GitHubClient(test_settings, client=client), session_factory
    )
    result = await service.run("octocat")
    assert result.repositories_synced == 0
    assert result.events_persisted == 0