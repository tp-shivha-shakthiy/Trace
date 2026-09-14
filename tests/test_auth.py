"""Application authentication and the public/private authorization boundary.

The rules under test:

* ``GET /api/v1/me`` and ``GET /api/v1/me/profile`` require a valid session
  cookie (issued only on successful GitHub OAuth).
* The owner's own profile may include private repositories/activity and the
  intelligence derived from them.
* Any *other* developer's profile — whether read anonymously or while logged
  in as a different user — must contain only public data and public-derived
  signals, even when the owner has private data in the database.
* Stored OAuth tokens, session tokens, and raw private data never appear in
  any response.
* A sync triggered by the account owner may use the stored OAuth token;
  a sync for the same account triggered by anyone else must not.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.models import Developer, GithubEvent, Repository, SyncJob
from app.services import sessions
from tests.conftest import async_test_client


def _at(idx: int) -> datetime:
    return datetime(2026, 8, 1, 10, 0, tzinfo=UTC) + timedelta(days=idx)


def _github_id(username: str) -> int:
    return sum(ord(c) for c in username) + 1000


def _make_developer(username: str, github_id: int, **overrides) -> Developer:
    values = dict(
        github_id=github_id,
        username=username,
        name="Mona",
        avatar_url="https://x/a",
        html_url=f"https://github.com/{username}",
        bio="Cat",
        followers=10,
        following=5,
        public_repos=1,
        github_token="stored-oauth-token",
    )
    values.update(overrides)
    return Developer(**values)


async def _seed_owner(session_factory, username: str):
    """Insert an owner with one public and one private repo (with events).

    The private repo carries unique signal evidence (Prolog language, a
    bespoke private domain) so we can assert it never leaks publicly.
    Returns ``(developer, session_token)``.
    """
    github_id = _github_id(username)
    async with session_factory() as session:
        async with session.begin():
            dev = _make_developer(username, github_id)
            session.add(dev)
            await session.flush()

            public_repo = Repository(
                developer_id=dev.id,
                github_id=github_id + 1,
                name="public",
                full_name=f"{username}/public",
                description="Backend API",
                language="Python",
                languages={"Python": 5000, "HTML": 100},
                topics=["api", "backend"],
                domains=["backend"],
                is_fork=False,
                is_private=False,
                stargazers_count=10,
                forks_count=2,
                open_issues_count=1,
                watchers_count=10,
            )
            private_repo = Repository(
                developer_id=dev.id,
                github_id=github_id + 2,
                name="secret",
                full_name=f"{username}/secret",
                description="Private ML platform",
                language="Prolog",
                languages={"Prolog": 9999},
                topics=["machine-learning"],
                domains=["privatedomain"],
                is_fork=False,
                is_private=True,
                stargazers_count=0,
                forks_count=0,
                open_issues_count=0,
                watchers_count=0,
            )
            session.add_all([public_repo, private_repo])
            await session.flush()

            session.add_all(
                [
                    GithubEvent(
                        developer_id=dev.id,
                        repository_id=public_repo.id,
                        provider="github",
                        event_type="commit",
                        github_event_id=f"{username}-ev-0",
                        resource_id="refs/heads/main",
                        occurred_at=_at(0),
                        payload={},
                        is_private=False,
                    ),
                    GithubEvent(
                        developer_id=dev.id,
                        repository_id=private_repo.id,
                        provider="github",
                        event_type="commit",
                        github_event_id=f"{username}-ev-1",
                        resource_id="refs/heads/main",
                        occurred_at=_at(1),
                        payload={},
                        is_private=True,
                    ),
                ]
            )

            token = await sessions.create_session(session, dev, max_age_days=30)
        return dev, token


async def test_my_profile_includes_private_data(session_factory):
    from app.services import profiles

    dev, _ = await _seed_owner(session_factory, "alice")
    async with session_factory() as session:
        profile = await profiles.get_my_profile(session, dev)

    repo_names = {r["full_name"] for r in profile["repositories"]}
    assert repo_names == {"alice/public", "alice/secret"}
    assert profile["summary"]["total_repositories"] == 2
    assert profile["summary"]["total_events"] == 2
    assert {r["name"] for r in profile["repositories"] if r["is_private"]} == {
        "secret"
    }
    # Repo-level domain evidence from the private repo is visible to the owner.
    assert "privatedomain" in profile["summary"]["domains"]
    # The private repo's unique topic is the only source of an "ml" signal.
    assert any(s["domain"] == "ml" for s in profile["summary"]["domain_signals"])
    assert profile["summary"]["languages"].get("Prolog") == 1


async def test_other_users_public_profile_excludes_private_data(session_factory):
    from app.services import profiles

    await _seed_owner(session_factory, "alice")
    await _seed_owner(session_factory, "bob")
    async with session_factory() as session:
        profile = await profiles.get_developer_profile(session, "alice")

    repo_names = {r["full_name"] for r in profile["repositories"]}
    assert repo_names == {"alice/public"}
    assert profile["summary"]["total_repositories"] == 1

    # Private events are excluded both from recent activity and aggregates.
    assert profile["summary"]["total_events"] == 1
    assert profile["summary"]["activity"] == {"commit": 1}
    assert len(profile["recent_activity"]) == 1

    # No private-derived intelligence: the private repo's unique language,
    # its bespoke domain, and the "ml" signal it was the sole source of must
    # not appear in a public profile.
    assert profile["summary"]["languages"].get("Prolog", 0) == 0
    assert "privatedomain" not in profile["summary"]["domains"]
    assert not any(s["domain"] == "ml" for s in profile["summary"]["domain_signals"])
    assert profile["is_owner"] is False


async def test_me_requires_session(app, session_factory):
    _, token = await _seed_owner(session_factory, "alice")
    async with async_test_client(app) as client:
        anon = await client.get("/api/v1/me")
        assert anon.status_code == 401

        authed = await client.get(
            "/api/v1/me", cookies={sessions.SESSION_COOKIE: token}
        )
        assert authed.status_code == 200
        body = authed.json()
        assert body["username"] == "alice"
        # Identity response must never expose the stored OAuth token.
        assert "github_token" not in body
        assert "token" not in body


async def test_logout_invalidates_only_current_session_and_clears_cookie(
    app, session_factory,
):
    _, alice_token = await _seed_owner(session_factory, "alice")
    _, bob_token = await _seed_owner(session_factory, "bob")

    async with async_test_client(app) as client:
        before = await client.get(
            "/api/v1/me", cookies={sessions.SESSION_COOKIE: alice_token}
        )
        assert before.status_code == 200
        assert before.json()["username"] == "alice"

        logged_out = await client.post(
            "/auth/logout", cookies={sessions.SESSION_COOKIE: alice_token}
        )
        assert logged_out.status_code == 200
        assert logged_out.json() == {"status": "logged_out"}
        set_cookie = logged_out.headers["set-cookie"]
        assert "trace_session=" in set_cookie
        assert "Max-Age=0" in set_cookie

        old_session = await client.get(
            "/api/v1/me", cookies={sessions.SESSION_COOKIE: alice_token}
        )
        assert old_session.status_code == 401
        assert (
            await client.get(
                "/api/v1/me/profile",
                cookies={sessions.SESSION_COOKIE: alice_token},
            )
        ).status_code == 401

        other_session = await client.get(
            "/api/v1/me", cookies={sessions.SESSION_COOKIE: bob_token}
        )
        assert other_session.status_code == 200
        assert other_session.json()["username"] == "bob"


async def test_logout_without_session_is_successful(app):
    async with async_test_client(app) as client:
        response = await client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}


async def test_me_profile_endpoint_public_profile_split(app, session_factory):
    _, token = await _seed_owner(session_factory, "alice")
    await _seed_owner(session_factory, "bob")

    async with async_test_client(app) as client:
        # Owner view: private repo visible.
        mine = await client.get(
            "/api/v1/me/profile", cookies={sessions.SESSION_COOKIE: token}
        )
        assert mine.status_code == 200
        mine_body = mine.json()
        assert {r["full_name"] for r in mine_body["repositories"]} == {
            "alice/public",
            "alice/secret",
        }
        assert mine_body["is_owner"] is True

        # Anonymous public view: private repo absent.
        public = await client.get("/api/v1/developers/alice")
        assert public.status_code == 200
        public_body = public.json()
        assert {r["full_name"] for r in public_body["repositories"]} == {
            "alice/public"
        }
        assert public_body["is_owner"] is False


async def test_authenticated_bob_still_cannot_read_alice_private_data(
    app, session_factory,
):
    await _seed_owner(session_factory, "alice")
    _, bob_token = await _seed_owner(session_factory, "bob")

    async with async_test_client(app) as client:
        # A second authenticated user (bob) pulling alice gets the *public*
        # profile, not the owner/full one — being authenticated is not
        # authorization to someone else's private data.
        response = await client.get(
            "/api/v1/developers/alice",
            cookies={sessions.SESSION_COOKIE: bob_token},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_owner"] is False
        assert {r["full_name"] for r in body["repositories"]} == {
            "alice/public"
        }
        assert body["summary"]["total_events"] == 1


async def test_stored_oauth_token_never_appears_in_responses(
    app, session_factory,
):
    await _seed_owner(session_factory, "alice")
    _, bob_token = await _seed_owner(session_factory, "bob")

    def _assert_no_secrets(text: str):
        assert "stored-oauth-token" not in text

    async with async_test_client(app) as client:
        for path in ("/api/v1/developers", "/api/v1/developers/alice"):
            response = await client.get(path)
            assert response.status_code == 200
            _assert_no_secrets(response.text)

        mine = await client.get(
            "/api/v1/me/profile", cookies={sessions.SESSION_COOKIE: bob_token}
        )
        assert mine.status_code == 200
        # /me/profile is inherently owner-scoped: bob gets bob, never alice.
        assert mine.json()["username"] == "bob"
        assert mine.json()["is_owner"] is True
        _assert_no_secrets(mine.text)


async def test_sync_authorization_controls_token_use(app, session_factory):
    """Only the account owner's sync may use the stored OAuth token."""
    _, token = await _seed_owner(session_factory, "alice")
    _, bob_token = await _seed_owner(session_factory, "bob")

    async def _job(job_id: str) -> SyncJob:
        async with session_factory() as session:
            job = await session.get(SyncJob, job_id)
            assert job is not None
            return job

    async with async_test_client(app) as client:
        owner = await client.post(
            "/api/v1/sync",
            json={"username": "alice"},
            cookies={sessions.SESSION_COOKIE: token},
        )
        assert owner.status_code == 202

        other = await client.post(
            "/api/v1/sync",
            json={"username": "alice"},
            cookies={sessions.SESSION_COOKIE: bob_token},
        )
        assert other.status_code == 202

        anon = await client.post("/api/v1/sync", json={"username": "alice"})
        assert anon.status_code == 202

    owner_job = await _job(owner.json()["job_id"])
    other_job = await _job(other.json()["job_id"])
    anon_job = await _job(anon.json()["job_id"])

    assert owner_job.developer_username == "alice"
    assert owner_job.use_token is True
    assert other_job.developer_username == "alice"
    assert other_job.use_token is False
    assert anon_job.developer_username == "alice"
    assert anon_job.use_token is False


async def test_expired_session_is_rejected(app, session_factory):
    async with session_factory() as session:
        async with session.begin():
            dev = _make_developer(
                "dave", _github_id("dave"), github_token=None
            )
            session.add(dev)
            await session.flush()
        expired = await _expired_token(session, dev)

    async with async_test_client(app) as client:
        response = await client.get(
            "/api/v1/me", cookies={sessions.SESSION_COOKIE: expired}
        )
    assert response.status_code == 401


async def _expired_token(session, dev: Developer) -> str:
    from app.models import AuthSession

    token = secrets.token_urlsafe(43)
    session.add(
        AuthSession(
            developer_id=dev.id,
            token_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await session.commit()
    return token