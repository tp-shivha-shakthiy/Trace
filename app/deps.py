"""FastAPI dependencies backed by ``app.state`` (set in the app factory)."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.jobs import IngestionJobWorker


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` from the app's session factory."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_worker(request: Request) -> IngestionJobWorker:
    """Return the app's background ingestion worker."""
    return request.app.state.ingestion_worker