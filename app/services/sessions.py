"""Opaque application sessions linking a browser to a TRACE ``Developer``.

Sessions are created when a user completes GitHub OAuth (see
``app/api/routes_auth.py``). The raw token is handed to the browser as an
HttpOnly cookie while only its SHA-256 digest is persisted, so a database
leak never exposes a usable session token directly.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession, Developer

SESSION_COOKIE = "trace_session"


def digest_token(token: str) -> str:
    """Return the SHA-256 hex digest used to look sessions up in the DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(
    session: AsyncSession,
    developer: Developer,
    *,
    max_age_days: int = 30,
) -> str:
    """Persist a new session for ``developer`` and return the raw token."""
    token = secrets.token_urlsafe(43)
    session.add(
        AuthSession(
            developer_id=developer.id,
            token_digest=digest_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=max_age_days),
        )
    )
    return token


async def resolve_developer(
    session: AsyncSession, token: str
) -> Developer | None:
    """Return the developer who owns a live session token, or None."""
    if not token:
        return None
    now = datetime.now(UTC)
    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.token_digest == digest_token(token),
            AuthSession.expires_at > now,
        )
    )
    if auth_session is None:
        return None
    return await session.get(Developer, auth_session.developer_id)


async def delete_session(session: AsyncSession, token: str | None) -> None:
    """Invalidate only the session represented by ``token``."""
    if not token:
        return
    await session.execute(
        delete(AuthSession).where(AuthSession.token_digest == digest_token(token))
    )