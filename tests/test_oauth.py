"""GitHub OAuth: authorize URL, token exchange, developer connection,
and per-developer token threading into ingestion."""

import httpx
import pytest
from app.config import Settings
from app.errors import OAuthExchangeFailedError, OAuthNotConfiguredError
from app.github import GitHubClient
from app.main import create_app
from app.models import Developer
from app.services import oauth
from app.services.ingestion import IngestionService
from sqlalchemy import select
from tests.conftest import async_test_client, make_github_handler

TOKEN_SETTINGS = Settings(
    github_oauth_client_id="client-1",
    github_oauth_client_secret="secret-1",
)


def _oauth_handler():
    """MockTransport handler for the GitHub OAuth token + /user endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(
                200, json={"access_token": "tok-123", "token_type": "bearer"}
            )
        if request.url.path == "/user":
            return httpx.Response(
                200,
                json={
                    "id": 77,
                    "login": "oauthuser",
                    "name": "O User",
                    "avatar_url": "https://example.invalid/a.png",
                    "followers": 4,
                    "following": 1,
                    "public_repos": 2,
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


async def test_build_authorize_url_includes_params():
    url = oauth.build_authorize_url(TOKEN_SETTINGS, "https://x/cb", "st8")
    assert "client_id=client-1" in url
    assert "redirect_uri=https%3A%2F%2Fx%2Fcb" in url
    assert "state=st8" in url


def test_build_authorize_url_requires_client_id():
    settings = Settings(github_oauth_client_id=None)
    with pytest.raises(OAuthNotConfiguredError):
        oauth.build_authorize_url(settings, "https://x/cb", "st8")


async def test_exchange_code_returns_token():
    client = httpx.AsyncClient(transport=httpx.MockTransport(_oauth_handler()))
    try:
        token = await oauth.exchange_code(client, TOKEN_SETTINGS, "code-1")
    finally:
        await client.aclose()
    assert token == "tok-123"


async def test_exchange_code_failure_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad_verification_code"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OAuthExchangeFailedError):
            await oauth.exchange_code(client, TOKEN_SETTINGS, "bad")
    finally:
        await client.aclose()


async def test_fetch_authenticated_user():
    client = httpx.AsyncClient(transport=httpx.MockTransport(_oauth_handler()))
    try:
        user = await oauth.fetch_authenticated_user(client, TOKEN_SETTINGS, "tok")
    finally:
        await client.aclose()
    assert user["login"] == "oauthuser"


async def test_connect_developer_persists_and_updates_token(session_factory):
    user = {"id": 77, "login": "oauthuser", "name": "O User"}
    async with session_factory() as session:
        async with session.begin():
            dev = await oauth.connect_developer(session, user, "first-token")
    assert dev.username == "oauthuser"

    async with session_factory() as session:
        stored = await session.scalar(
            select(Developer).where(Developer.username == "oauthuser")
        )
        assert stored is not None
        assert stored.github_token == "first-token"

    # Re-connecting refreshes the token, never duplicate rows.
    async with session_factory() as session:
        async with session.begin():
            await oauth.connect_developer(session, user, "second-token")
    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(Developer).where(Developer.username == "oauthuser")
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].github_token == "second-token"


async def test_oauth_callback_connects_and_enqueues_sync(session_factory):
    async def oauth_app():
        from app.main import create_app

        return create_app(
            settings=TOKEN_SETTINGS,
            session_factory=session_factory,
            github_client=GitHubClient(
                Settings(),
                client=httpx.AsyncClient(
                    transport=httpx.MockTransport(make_github_handler()),
                    base_url="https://api.github.com",
                ),
            ),
        )

    test_app = await oauth_app()
    test_app.state.oauth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_oauth_handler())
    )
    async with async_test_client(test_app) as client:
        response = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "s1"},
            cookies={"trace_oauth_state": "s1"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["username"] == "oauthuser"
        assert body["status"] == "connected"

    async with session_factory() as session:
        stored = await session.scalar(
            select(Developer).where(Developer.username == "oauthuser")
        )
        assert stored is not None
        assert stored.github_token == "tok-123"


async def test_oauth_callback_requires_valid_state(session_factory):
    from app.main import create_app

    test_app = create_app(
        settings=TOKEN_SETTINGS,
        session_factory=session_factory,
    )
    test_app.state.oauth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_oauth_handler())
    )
    async with async_test_client(test_app) as client:
        response = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "wrong"},
            cookies={"trace_oauth_state": "s1"},
        )
    assert response.status_code == 400


async def test_authorize_redirect_when_configured(app):
    from app.main import create_app

    test_app = create_app(
        settings=TOKEN_SETTINGS,
        session_factory=app.state.session_factory,
        github_client=app.state.ingestion_worker._github,
    )
    async with async_test_client(test_app) as client:
        response = await client.get("/auth/github", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    assert "client_id=client-1" in location


async def test_authorize_carries_next_route_in_state(app):
    from urllib.parse import unquote

    from app.main import create_app

    test_app = create_app(
        settings=TOKEN_SETTINGS,
        session_factory=app.state.session_factory,
        github_client=app.state.ingestion_worker._github,
    )
    async with async_test_client(test_app) as client:
        response = await client.get(
            "/auth/github?next=/developers/octocat", follow_redirects=False
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert "|/developers/octocat" in unquote(location)
        cookie = response.headers.get_list("set-cookie")[0]
        assert "|/developers/octocat" in cookie

        # A non-application next value is rejected at the authorize step.
        rejected = await client.get(
            "/auth/github?next=//evil.example", follow_redirects=False
        )
        assert rejected.status_code == 302
        assert "evil.example" not in unquote(rejected.headers["location"])


async def test_oauth_callback_redirects_to_requested_next_route(session_factory):
    app = await _oauth_callback_app(session_factory)
    async with async_test_client(app) as client:
        client.cookies.set("trace_oauth_state", "s1|/developers/octocat")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "s1|/developers/octocat"},
            headers={"accept": "text/html"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/#/developers/octocat"

    # Malicious / external next values fall back to the default /#/me.
    async with async_test_client(app) as client:
        client.cookies.set("trace_oauth_state", "s1|//evil.example")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "s1|//evil.example"},
            headers={"accept": "text/html"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/#/me"


async def test_sync_uses_stored_token_in_requests(session_factory):
    seen: list[str] = []
    base = make_github_handler()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        return base(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.com",
    )
    github = GitHubClient(Settings(), client=client)
    service = IngestionService(github, session_factory)

    result = await service.run("octocat", token="tok-abc")
    assert result.repositories_synced == 3
    assert seen and all(header == "Bearer tok-abc" for header in seen)


async def _oauth_callback_app(session_factory):
    """Build the app exactly as the real one, but with GitHub mocked."""
    app = create_app(
        settings=TOKEN_SETTINGS,
        session_factory=session_factory,
        github_client=GitHubClient(
            Settings(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(make_github_handler()),
                base_url="https://api.github.com",
            ),
        ),
    )
    app.state.oauth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_oauth_handler())
    )
    return app


async def test_oauth_callback_sets_usable_session_cookie(session_factory):
    """The whole browser chain: callback -> cookie -> authenticated /me."""
    app = await _oauth_callback_app(session_factory)
    async with async_test_client(app) as client:
        client.cookies.set("trace_oauth_state", "s1")
        callback = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "s1"},
        )
        assert callback.status_code == 200, callback.text
        # Session cookie must have reached the browser's cookie jar.
        assert "trace_session" in client.cookies

        me = await client.get("/api/v1/me")
        assert me.status_code == 200
        assert me.json()["username"] == "oauthuser"

        # The public profile now exists and the owner profile resolves.
        public = await client.get("/api/v1/developers/oauthuser")
        assert public.status_code == 200
        mine = await client.get("/api/v1/me/profile")
        assert mine.status_code == 200
        assert mine.json()["username"] == "oauthuser"


async def test_oauth_callback_redirects_browser_into_spa(session_factory):
    """Browsers (Accept: text/html) are sent to /#/me after login; the JSON
    contract is preserved for API clients (default Accept: */*)."""
    app = await _oauth_callback_app(session_factory)
    async with async_test_client(app) as client:
        client.cookies.set("trace_oauth_state", "s1")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "abc", "state": "s1"},
            headers={"accept": "text/html"},
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/#/me"
        assert "trace_session=" in response.headers.get("set-cookie", "")

        # API clients still receive the connected JSON, not a redirect.
        async with async_test_client(app) as api_client:
            api_client.cookies.set("trace_oauth_state", "s1")
            api_response = await api_client.get(
                "/auth/github/callback",
                params={"code": "abc", "state": "s1"},
            )
            assert api_response.status_code == 200
            assert api_response.json()["status"] == "connected"