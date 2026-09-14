"""Ownership isolation for user-fetched developer snapshots."""

from datetime import UTC, datetime

from app.models import Developer, FetchedDeveloper, GithubEvent, Repository
from app.services import sessions
from tests.conftest import async_test_client


async def _seed_identity(session_factory, username: str, github_id: int):
    async with session_factory() as session:
        async with session.begin():
            developer = Developer(
                github_id=github_id,
                username=username,
                name=username.title(),
                html_url=f"https://github.com/{username}",
            )
            session.add(developer)
            await session.flush()
            token = await sessions.create_session(session, developer)
        return developer.id, token


async def _seed_fetched_copy(
    session_factory,
    *,
    owner_id: int,
    target_id: int,
    owner_username: str,
    target_username: str,
):
    async with session_factory() as session:
        async with session.begin():
            session.add(
                FetchedDeveloper(owner_id=owner_id, developer_id=target_id)
            )
            repository = Repository(
                developer_id=target_id,
                owner_id=owner_id,
                github_id=target_id + 1000,
                name=f"{target_username}-repo",
                full_name=f"{target_username}/{owner_username}-copy",
                description="Fetched copy",
                language="Python",
                languages={"Python": 100},
                topics=["api"],
                domains=["backend"],
                is_private=False,
            )
            session.add(repository)
            await session.flush()
            session.add(
                GithubEvent(
                    developer_id=target_id,
                    owner_id=owner_id,
                    repository_id=repository.id,
                    provider="github",
                    event_type="PushEvent",
                    github_event_id=f"{owner_username}-{target_username}-event",
                    occurred_at=datetime.now(UTC),
                    payload={},
                    is_private=False,
                )
            )


async def test_fetched_profiles_are_private_and_deletion_is_owner_scoped(
    app, session_factory
):
    target_id, target_token = await _seed_identity(session_factory, "person-b", 200)
    alice_id, alice_token = await _seed_identity(session_factory, "person-a", 201)
    bob_id, bob_token = await _seed_identity(session_factory, "person-c", 202)
    await _seed_fetched_copy(
        session_factory,
        owner_id=alice_id,
        target_id=target_id,
        owner_username="person-a",
        target_username="person-b",
    )
    await _seed_fetched_copy(
        session_factory,
        owner_id=bob_id,
        target_id=target_id,
        owner_username="person-c",
        target_username="person-b",
    )

    async with async_test_client(app) as client:
        alice_view = await client.get(
            "/api/v1/developers/person-b",
            cookies={sessions.SESSION_COOKIE: alice_token},
        )
        assert alice_view.status_code == 200
        assert alice_view.json()["is_fetched"] is True

        bob_view = await client.get(
            "/api/v1/developers/person-b",
            cookies={sessions.SESSION_COOKIE: bob_token},
        )
        assert bob_view.status_code == 200
        assert bob_view.json()["is_fetched"] is True

        anonymous_view = await client.get("/api/v1/developers/person-b")
        assert anonymous_view.status_code == 404

        deleted = await client.delete(
            "/api/v1/developers/person-b/fetched",
            cookies={sessions.SESSION_COOKIE: alice_token},
        )
        assert deleted.status_code == 204

        alice_after_delete = await client.get(
            "/api/v1/developers/person-b",
            cookies={sessions.SESSION_COOKIE: alice_token},
        )
        assert alice_after_delete.status_code == 404

        bob_after_delete = await client.get(
            "/api/v1/developers/person-b",
            cookies={sessions.SESSION_COOKIE: bob_token},
        )
        assert bob_after_delete.status_code == 200

        target_profile = await client.get(
            "/api/v1/me/profile",
            cookies={sessions.SESSION_COOKIE: target_token},
        )
        assert target_profile.status_code == 200
        assert target_profile.json()["username"] == "person-b"


async def test_demo_profile_is_public_but_non_demo_is_not(app, session_factory):
    async with session_factory() as session:
        async with session.begin():
            demo = Developer(
                github_id=300,
                username="trace-demo",
                name="TRACE Demo",
                is_demo=True,
            )
            session.add(demo)

    async with async_test_client(app) as client:
        demo_response = await client.get("/api/v1/developers/trace-demo")

    assert demo_response.status_code == 200
    assert demo_response.json()["is_fetched"] is False
