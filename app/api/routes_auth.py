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
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.services import oauth

router = APIRouter(tags=["auth"])

_STATE_COOKIE = "trace_oauth_state"


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
    async with factory() as session:
        async with session.begin():
            developer = await oauth.connect_developer(session, github_user, token)

    job_id = await request.app.state.ingestion_worker.create_and_enqueue(
        developer.username
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
    response.delete_cookie(_STATE_COOKIE)
    return response