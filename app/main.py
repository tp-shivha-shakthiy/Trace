"""FastAPI application factory and entry point.

Run with::

    uvicorn app.main:app --reload

The lifespan starts/stops the background ingestion worker so that
``POST /api/v1/sync`` jobs are processed asynchronously.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import _loop  # noqa: F401  (configures the asyncio policy on Windows)
from app.api import routes_auth, routes_developers, routes_health, routes_sync
from app.config import Settings, get_settings
from app.database import build_engine, build_session_factory
from app.errors import register_exception_handlers
from app.github import GitHubClient
from app.schema import ensure_database_schema
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
        if owns_engine and engine is not None:
            await ensure_database_schema(engine)
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()
            await _app.state.oauth_client.aclose()
            if owns_engine:
                await engine.dispose()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.ingestion_worker = worker
    app.state.oauth_client = httpx.AsyncClient(
        timeout=settings.github_timeout_seconds
    )

    register_exception_handlers(app)

    app.include_router(routes_health.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_developers.router)
    app.include_router(routes_developers.router, prefix=settings.api_v1_prefix)
    app.include_router(routes_sync.router, prefix=settings.api_v1_prefix)

    # When the SPA has been built (frontend/dist exists) it is served at "/".
    # Router registration above happens first, so /api, /auth, /health,
    # /docs and /openapi.json keep precedence; the SPA mount only owns the
    # root and its static assets. The SPA uses hash-based routing, so no
    # server-side fallback is required for client-side routes.
    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if settings.serve_spa and dist_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=dist_dir, html=True),
            name="spa",
        )
    else:
        logging.getLogger(__name__).warning(
            "frontend/dist not found (serve_spa=%s) - serving API JSON at /",
            settings.serve_spa,
        )

        @app.get("/")
        async def root() -> dict:
            return {
                "app": settings.app_name,
                "version": settings.app_version,
                "docs": "/docs",
            }

    return app


app = create_app()