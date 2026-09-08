"""ORM model persistence and constraint behaviour."""

from datetime import UTC, datetime

import pytest
from app.models import Developer, GithubEvent, Repository, SyncJob
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def _insert_developer(session, **overrides):
    defaults = {
        "github_id": 42,
        "username": "testuser",
        "name": "Test User",
        "bio": "Unit testing.",
        "followers": 5,
        "following": 2,
        "public_repos": 10,
    }
    defaults.update(overrides)
    session.add(Developer(**defaults))
    await session.flush()
    return defaults


async def test_developer_basic(session_factory):
    async with session_factory() as session:
        async with session.begin():
            await _insert_developer(session)
        rows = list(await session.scalars(select(Developer)))
        assert len(rows) == 1
        dev = rows[0]
        assert dev.id is not None
        assert dev.username == "testuser"
        assert dev.created_at is not None


async def test_developer_unique_username_constraint(session_factory):
    async with session_factory() as session:
        async with session.begin():
            await _insert_developer(session, github_id=1)
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await _insert_developer(session, github_id=2)


async def test_repository_persists_domains_and_languages(session_factory):
    async with session_factory() as session:
        async with session.begin():
            dev = Developer(
                github_id=99,
                username="repoowner",
                name="Repo Owner",
                followers=0,
                following=0,
                public_repos=2,
            )
            session.add(dev)
            await session.flush()
            repo = Repository(
                developer_id=dev.id,
                github_id=101,
                name="demo",
                full_name="repoowner/demo",
                language="Python",
                languages={"Python": 1200, "HTML": 50},
                topics=["api", "backend"],
                domains=["backend"],
                is_fork=False,
                stargazers_count=3,
                forks_count=1,
                open_issues_count=0,
                watchers_count=3,
            )
            session.add(repo)

    async with session_factory() as session:
        repo = await session.scalar(select(Repository).limit(1))
        assert repo is not None
        assert repo.domains == ["backend"]
        assert repo.languages == {"Python": 1200, "HTML": 50}
        assert repo.stargazers_count == 3


async def test_unique_constraints_on_event(session_factory):
    async with session_factory() as session:
        async with session.begin():
            dev = Developer(
                github_id=88,
                username="eventowner",
                name="Event Owner",
                followers=0,
                following=0,
                public_repos=1,
            )
            session.add(dev)
            await session.flush()
            event = GithubEvent(
                developer_id=dev.id,
                provider="github",
                event_type="commit",
                github_event_id="999",
                occurred_at=datetime.now(UTC),
                payload={"ref": "main"},
            )
            session.add(event)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                duplicate = GithubEvent(
                    developer_id=dev.id,
                    provider="github",
                    event_type="commit",
                    github_event_id="999",
                    occurred_at=datetime.now(UTC),
                    payload={"ref": "main"},
                )
                session.add(duplicate)


async def test_sync_job_defaults(session_factory):
    async with session_factory() as session:
        async with session.begin():
            job = SyncJob(developer_username="testuser")
            session.add(job)
    async with session_factory() as session:
        stored = await session.get(SyncJob, job.id)
        assert stored is not None
        assert stored.status == "queued"
        assert stored.events_fetched == 0
        assert stored.error_message is None