"""Developer profile retrieval from persisted data."""

from datetime import UTC, datetime, timedelta

import pytest
from app.errors import DeveloperNotFoundError
from app.models import Developer, GithubEvent, Repository
from app.services import profiles


def profiles_datetime(idx: int) -> datetime:
    return datetime(2026, 8, 1, 10, 0, tzinfo=UTC) + timedelta(days=idx)


async def seed_developer(session_factory, username="octocat"):
    """Insert a developer + repos + events directly (no GitHub call)."""
    github_id = sum(ord(c) for c in username) + 1000
    async with session_factory() as session:
        async with session.begin():
            dev = Developer(
                github_id=github_id,
                username=username,
                name="Mona",
                avatar_url="https://x/a",
                html_url=f"https://github.com/{username}",
                bio="Cat",
                followers=10,
                following=5,
                public_repos=2,
            )
            session.add(dev)
            await session.flush()

            repo1 = Repository(
                developer_id=dev.id,
                github_id=github_id + 1,
                name="api",
                full_name=f"{username}/api",
                description="Backend API",
                language="Python",
                languages={"Python": 5000, "HTML": 100},
                topics=["api", "backend"],
                domains=["backend"],
                is_fork=False,
                stargazers_count=10,
                forks_count=2,
                open_issues_count=1,
                watchers_count=10,
            )
            repo2 = Repository(
                developer_id=dev.id,
                github_id=github_id + 2,
                name="app",
                full_name=f"{username}/app",
                description="Frontend dashboard",
                language="TypeScript",
                languages={"TypeScript": 3000, "CSS": 500},
                topics=["react", "frontend"],
                domains=["frontend"],
                is_fork=False,
                stargazers_count=5,
                forks_count=1,
                open_issues_count=0,
                watchers_count=5,
            )
            session.add_all([repo1, repo2])
            await session.flush()

            for idx in range(3):
                session.add(
                    GithubEvent(
                        developer_id=dev.id,
                        repository_id=(repo1.id if idx % 2 == 0 else repo2.id),
                        provider="github",
                        event_type="commit" if idx % 2 == 0 else "pull_request",
                        github_event_id=f"ev-{idx}",
                        resource_id="refs/heads/main",
                        occurred_at=profiles_datetime(idx),
                        payload={"n": idx},
                    )
                )
        return dev.id


async def test_profile_built_from_persisted_data(session_factory):
    await seed_developer(session_factory)
    async with session_factory() as session:
        profile = await profiles.get_developer_profile(session, "octocat")

    assert profile["username"] == "octocat"
    assert profile["bio"] == "Cat"

    assert profile["summary"]["total_repositories"] == 2
    assert profile["summary"]["total_events"] == 3
    languages = profile["summary"]["languages"]
    assert languages.get("Python") == 1
    assert languages.get("TypeScript") == 1

    domains = profile["summary"]["domains"]
    assert domains["backend"].repository_count == 1
    assert domains["frontend"].repository_count == 1

    repo_names = {r["full_name"] for r in profile["repositories"]}
    assert repo_names == {"octocat/api", "octocat/app"}

    assert len(profile["recent_activity"]) == 3
    types = {a["event_type"] for a in profile["recent_activity"]}
    assert types == {"commit", "pull_request"}


async def test_profile_activity_aggregations(session_factory):
    await seed_developer(session_factory)
    async with session_factory() as session:
        profile = await profiles.get_developer_profile(session, "octocat")

    summary = profile["summary"]

    assert summary["activity"] == {"commit": 2, "pull_request": 1}
    assert summary["events_by_domain"] == {"backend": 2, "frontend": 1}
    assert summary["events_per_month"] == [{"month": "2026-08", "events": 3}]

    by_name = {r["name"]: r for r in profile["repositories"]}
    assert by_name["api"]["event_count"] == 2
    assert by_name["app"]["event_count"] == 1


async def test_profile_includes_domain_signals(session_factory):
    await seed_developer(session_factory)
    async with session_factory() as session:
        profile = await profiles.get_developer_profile(session, "octocat")

    signals = profile["summary"]["domain_signals"]
    by_domain = {signal["domain"]: signal for signal in signals}

    assert "backend" in by_domain
    assert "frontend" in by_domain

    backend = by_domain["backend"]
    assert 0 < backend["score"] <= 1.0
    assert backend["confidence"] in {"high", "medium", "low"}
    assert backend["repository_count"] >= 1
    assert len(backend["evidence"]) >= 1
    assert any("language" in line for line in backend["evidence"])

    frontend = by_domain["frontend"]
    assert len(frontend["evidence"]) >= 1


async def test_profile_not_found(session_factory):
    async with session_factory() as session:
        with pytest.raises(DeveloperNotFoundError):
            await profiles.get_developer_profile(session, "nobody")


async def test_list_developers(session_factory):
    await seed_developer(session_factory, "alice")
    await seed_developer(session_factory, "bob")
    async with session_factory() as session:
        devs = await profiles.list_developers(session)
    assert len(devs) == 2
    usernames = {d["username"] for d in devs}
    assert usernames == {"alice", "bob"}
    by_name = {d["username"]: d for d in devs}
    assert by_name["alice"]["total_events"] == 3