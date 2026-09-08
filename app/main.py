"""FastAPI application factory and entry point.

Run with::

    uvicorn app.main:app --reload

The lifespan starts/stops the background ingestion worker so that
``POST /api/v1/sync`` jobs are processed asynchronously.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import _loop  # noqa: F401  (configures the asyncio policy on Windows)
from app.api import routes_developers, routes_health, routes_sync
from app.config import Settings, get_settings
from app.database import build_engine, build_session_factory
from app.errors import register_exception_handlers
from app.github import GitHubClient
from app.services.domains import DomainInference
from app.services.jobs import IngestionJobWorker


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker | None = None,
    github_client: GitHubClient | None = None,
    domain_inference: DomainInference | None = None,
) -> FastAPI:
    """Build a fully wired TRACE application.

    Defaults build an engine from ``settings.database_url`` and a live
    ``GitHubClient``. Tests pass their own ``session_factory`` and a mocked
    ``GitHubClient`` to stay fully offline.
    """
    settings = settings or get_settings()

    owns_engine = session_factory is None
    engine: AsyncEngine | None = None
    if owns_engine:
        engine = build_engine(settings.database_url)
        session_factory = build_session_factory(engine)

    github = github_client or GitHubClient(settings)
    worker = IngestionJobWorker(
        session_factory,
        github,
        domain_inference=domain_inference,
        concurrency=settings.sync_worker_concurrency,
        language_repos_limit=settings.ingestion_language_repos_limit,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()
            if owns_engine:
                await engine.dispose()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.session_factory = session_factory
    app.state.ingestion_worker = worker

    register_exception_handlers(app)

    app.include_router(routes_health.router)
    app.include_router(routes_developers.router)
    app.include_router(routes_developers.router, prefix=settings.api_v1_prefix)
    app.include_router(routes_sync.router, prefix=settings.api_v1_prefix)

    @app.get("/")
    async def root() -> dict:
        return {
            "app": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


app = create_app()