"""GitHub OAuth endpoints.

``GET /auth/github``            - redirect to GitHub's OAuth consent screen
``GET /auth/github/callback``   - exchange code, connect the developer,
                                  store their token, enqueue an initial sync

The developer's access token is stored on their ``Developer`` row so their
subsequent ``POST /api/v1/sync`` jobs run authenticated (5000 req/hr).
Tokens are never returned to the browser.
"""

from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.services import oauth, sessions

router = APIRouter(tags=["auth"])

_STATE_COOKIE = "trace_oauth_state"


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
    """Redirect the browser to GitHub's OAuth consent screen."""
    settings = request.app.state.settings
    state = secrets.token_urlsafe(32)
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

    # Only this (now authenticated) owner may sync themselves with the token,
    # which is what makes their private repositories ingestible.
    job_id = await request.app.state.ingestion_worker.create_and_enqueue(
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
            "sync_job_id": job_id,
        }
    )
    # A browser ends up on this URL after GitHub redirects it back; send it
    # into the SPA (hash route #/me) so the fresh session is actually used.
    # Plain API/curl clients keep the JSON "connected" contract.
    if "text/html" in request.headers.get("accept", ""):
        response = RedirectResponse(url="/#/me", status_code=303)
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