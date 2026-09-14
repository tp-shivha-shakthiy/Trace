"""FastAPI dependencies backed by ``app.state`` (set in the app factory)."""

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import AuthRequiredError
from app.models import Developer
from app.services import sessions
from app.services.jobs import IngestionJobWorker


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` from the app's session factory."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_worker(request: Request) -> IngestionJobWorker:
    """Return the app's background ingestion worker."""
    return request.app.state.ingestion_worker


async def get_current_developer(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Developer:
    """Resolve the authenticated TRACE user from the session cookie.

    This is the single reusable authentication dependency: it answers
    "who is the currently authenticated developer" and maps that identity to
    the ``Developer`` record. Authorization decisions (owner-only data, etc.)
    are made from the returned identity, never from client-supplied ids.
    """
    token = request.cookies.get(sessions.SESSION_COOKIE)
    developer = await sessions.resolve_developer(db, token) if token else None
    if developer is None:
        raise AuthRequiredError()
    return developer


async def get_optional_current_developer(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Developer | None:
    """Like :func:`get_current_developer` but anonymous (None) when there is
    no valid session. Used by endpoints that behave differently for owners."""
    token = request.cookies.get(sessions.SESSION_COOKIE)
    if not token:
        return None
    return await sessions.resolve_developer(db, token)