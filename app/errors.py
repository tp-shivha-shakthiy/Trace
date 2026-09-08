"""Domain exceptions and FastAPI exception handlers."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class TraceError(Exception):
    """Base class for TRACE business errors."""


class DeveloperNotFoundError(TraceError):
    """Raised when a developer has no profile in the local database."""


class SyncJobNotFoundError(TraceError):
    """Raised when a sync job id is unknown."""


class GitHubError(TraceError):
    """Base class for GitHub API client errors."""


class GitHubNotFoundError(GitHubError):
    """Raised for GitHub 404 responses (unknown user/repository)."""


class GitHubRateLimitError(GitHubError):
    """Raised when GitHub rate limits the request."""


class GitHubApiError(GitHubError):
    """Raised for unexpected GitHub API failures (5xx, network, etc.)."""


def register_exception_handlers(app: FastAPI) -> None:
    """Attach JSON error handlers for TRACE exceptions."""

    @app.exception_handler(DeveloperNotFoundError)
    async def _developer_not_found(request: Request, exc: DeveloperNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SyncJobNotFoundError)
    async def _sync_job_not_found(request: Request, exc: SyncJobNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(GitHubNotFoundError)
    async def _github_not_found(request: Request, exc: GitHubNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": f"GitHub resource not found: {exc}"},
        )

    @app.exception_handler(GitHubRateLimitError)
    async def _github_rate_limit(request: Request, exc: GitHubRateLimitError):
        return JSONResponse(
            status_code=429,
            content={"detail": f"GitHub API rate limit exceeded: {exc}"},
        )

    @app.exception_handler(GitHubApiError)
    async def _github_api_error(request: Request, exc: GitHubApiError):
        return JSONResponse(
            status_code=502,
            content={"detail": f"GitHub API error: {exc}"},
        )