"""GitHub OAuth endpoints.

``GET /auth/github``            - redirect to GitHub's OAuth consent screen
``GET /auth/github/callback``   - exchange code, connect the developer,
                                  store their token, enqueue an initial sync

The developer's access token is stored on their ``Developer`` row so their
subsequent ``POST /api/v1/sync`` jobs run authenticated (5000 req/hr).
Tokens are never returned to the browser.
"""

from __future__ import annotations

import re
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.services import oauth, sessions

router = APIRouter(tags=["auth"])

_STATE_COOKIE = "trace_oauth_state"


_DEVELOPER_ROUTE_PREFIX = "/developers/"

# GitHub login rules: 1-39 characters, ASCII letters/digits and single
# hyphens, never starting or ending with a hyphen.
_GITHUB_USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")


def _is_valid_github_username(value: str) -> bool:
    return _GITHUB_USERNAME_RE.fullmatch(value) is not None


def _safe_next_path(value: str | None) -> str:
    """Normalize the internal SPA route to land on after OAuth.

    Only literal application routes are accepted so the callback can never be
    coerced into an open redirect to an external site. A developer route is
    accepted only as exactly ``/developers/<valid GitHub username>``: nested
    paths, query strings, encoded characters or malformed usernames fall back
    to ``/me``, because the username becomes a sync target.
    """
    if value is None:
        return "/me"
    if value in ("/", "/me"):
        return value
    if value.startswith(_DEVELOPER_ROUTE_PREFIX) and _is_valid_github_username(
        value.removeprefix(_DEVELOPER_ROUTE_PREFIX)
    ):
        return value
    return "/me"


def _next_target_username(next_path: str, fallback: str) -> str:
    """The developer implied by the SPA route landed on after OAuth.

    Returns ``fallback`` (the connecting user) unless ``next_path`` is a
    developer route naming a valid GitHub username, so an arbitrary path can
    never become a sync target. GitHub logins are case-insensitive, so a
    route naming the connecting user in any case resolves to ``fallback``.
    """
    if not next_path.startswith(_DEVELOPER_ROUTE_PREFIX):
        return fallback
    candidate = next_path.removeprefix(_DEVELOPER_ROUTE_PREFIX)
    if not _is_valid_github_username(candidate):
        return fallback
    if candidate.casefold() == fallback.casefold():
        return fallback
    return candidate


def _landing_url(next_path: str, job_id: str) -> str:
    """SPA URL to send the browser to after a successful callback.

    The landing page polls ``job_id`` so the initial sync progress is visible
    instead of a profile that already looks synced.
    """
    url = f"/#{next_path}"
    if next_path == "/me" or next_path.startswith("/developers/"):
        url = f"{url}?job={job_id}"
    return url


@router.post("/auth/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Invalidate the current TRACE session and expire its browser cookie."""
    await sessions.delete_session(
        db, request.cookies.get(sessions.SESSION_COOKIE)
    )
    await db.commit()

    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(sessions.SESSION_COOKIE, path="/")
    return response


@router.get("/auth/github")
async def github_login(request: Request) -> RedirectResponse:
    """Redirect the browser to GitHub's OAuth consent screen.

    The optional ``?next=/developers/{username}`` query parameter (set by the
    SPA when a developer page triggers the connect flow) is carried inside the
    OAuth state and, after a successful callback, the browser is sent to that
    SPA route instead of the default ``/#/me``.
    """
    settings = request.app.state.settings
    next_path = _safe_next_path(request.query_params.get("next"))
    state = secrets.token_urlsafe(32)
    state = f"{state}|{next_path}" if next_path != "/me" else state
    redirect_uri = str(request.base_url) + "auth/github/callback"
    authorize_url = oauth.build_authorize_url(settings, redirect_uri, state)
    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie(_STATE_COOKIE, state, samesite="lax", httponly=True)
    return response


@router.get("/auth/github/callback")
async def github_callback(
    request: Request,
    code: str,
    state: str | None = None,
) -> JSONResponse:
    """Validate the callback, connect the developer, and sync them."""
    settings = request.app.state.settings
    expected = request.cookies.get(_STATE_COOKIE)
    if not expected or state != expected:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    next_path = "/me"
    if "|" in expected:
        _, _, raw = expected.partition("|")
        next_path = _safe_next_path(raw)

    client: httpx.AsyncClient = request.app.state.oauth_client
    token = await oauth.exchange_code(client, settings, code)
    github_user = await oauth.fetch_authenticated_user(client, settings, token)

    factory = request.app.state.session_factory
    settings = request.app.state.settings
    async with factory() as session:
        async with session.begin():
            developer = await oauth.connect_developer(session, github_user, token)
            session_token = await sessions.create_session(
                session, developer, max_age_days=settings.session_max_age_days
            )

    # The landing page (derived from ?next=) is synced first so the job the
    # browser polls is the one that populates that page. The connecting owner
    # also gets a token-backed sync so their own private profile stays fresh.
    target_username = _next_target_username(next_path, developer.username)
    poll_job_id = await request.app.state.ingestion_worker.create_and_enqueue(
        target_username,
        use_token=target_username == developer.username,
        owner_id=developer.id,
    )
    if target_username != developer.username:
        await request.app.state.ingestion_worker.create_and_enqueue(
            developer.username,
            use_token=True,
            owner_id=developer.id,
        )

    response = JSONResponse(
        {
            "username": developer.username,
            "status": "connected",
            "message": (
                f"GitHub account {developer.username} connected; "
                "an initial sync has been enqueued."
            ),
            "sync_job_id": poll_job_id,
        }
    )
    # A browser ends up on this URL after GitHub redirects it back; send it
    # into the SPA (hash route, default #/me or the developer page requested
    # via ?next=) so the fresh session is actually used. Plain API/curl
    # clients keep the JSON "connected" contract.
    if "text/html" in request.headers.get("accept", ""):
        response = RedirectResponse(
            url=_landing_url(next_path, poll_job_id), status_code=303
        )
    response.delete_cookie(_STATE_COOKIE)
    response.set_cookie(
        sessions.SESSION_COOKIE,
        session_token,
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    return response