"""GitHub OAuth flow: authorize URL, token exchange, and user lookup.

The authenticated user's access token is stored on their ``Developer`` row so
subsequent syncs run with that token (5000 req/hr instead of the anonymous
60 req/hr). Tokens are *never* returned by the API.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import OAuthExchangeFailedError, OAuthNotConfiguredError
from app.models import Developer


def build_authorize_url(
    settings: Settings, redirect_uri: str, state: str
) -> str:
    """Return the GitHub OAuth authorize URL for a browser redirect."""
    if not settings.github_oauth_client_id:
        raise OAuthNotConfiguredError(
            "GitHub OAuth is not configured (GITHUB_OAUTH_CLIENT_ID missing)"
        )
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "",
    }
    return "https://github.com/login/oauth/authorize?" + urlencode(params)


async def exchange_code(
    client: httpx.AsyncClient, settings: Settings, code: str
) -> str:
    """Exchange an authorization code for an access token."""
    if not settings.github_oauth_client_secret:
        raise OAuthNotConfiguredError(
            "GitHub OAuth is not configured "
            "(GITHUB_OAUTH_CLIENT_SECRET missing)"
        )
    response = await client.post(
        settings.github_oauth_token_url,
        data={
            "client_id": settings.github_oauth_client_id,
            "client_secret": settings.github_oauth_client_secret,
            "code": code,
        },
        headers={"Accept": "application/json"},
    )
    payload = response.json()
    if response.status_code != 200 or "access_token" not in payload:
        description = payload.get("error_description") or payload.get("error")
        raise OAuthExchangeFailedError(
            f"GitHub OAuth token exchange failed: "
            f"{description or response.status_code}"
        )
    return payload["access_token"]


async def fetch_authenticated_user(
    client: httpx.AsyncClient, settings: Settings, token: str
) -> dict:
    """Fetch the authenticated user's GitHub profile (``GET /user``)."""
    response = await client.get(
        settings.github_api_url.rstrip("/") + "/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    if response.status_code != 200:
        raise OAuthExchangeFailedError(
            f"GitHub user fetch failed: returned {response.status_code}"
        )
    return response.json()


async def connect_developer(
    session: AsyncSession, github_user: dict, token: str
) -> Developer:
    """Upsert a developer from their GitHub profile, storing the token."""
    values = {
        "github_id": github_user.get("id"),
        "username": github_user["login"],
        "name": github_user.get("name"),
        "avatar_url": github_user.get("avatar_url"),
        "html_url": github_user.get("html_url"),
        "company": github_user.get("company"),
        "location": github_user.get("location"),
        "bio": github_user.get("bio"),
        "followers": github_user.get("followers", 0),
        "following": github_user.get("following", 0),
        "public_repos": github_user.get("public_repos", 0),
    }
    set_ = {**values, "github_token": token}
    set_ = {key: value for key, value in set_.items() if key != "username"}
    stmt = (
        pg_insert(Developer)
        .values(**values, github_token=token)
        .on_conflict_do_update(
            index_elements=[Developer.username],
            set_=set_,
        )
        .returning(Developer.id)
    )
    developer_id = (await session.execute(stmt)).scalar_one()
    developer = await session.get(Developer, developer_id)
    assert developer is not None
    return developer