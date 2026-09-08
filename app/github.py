"""Async GitHub REST API client with pagination and error mapping.

The client talks to ``{GITHUB_API_URL}`` (default ``https://api.github.com``)
and is used by the ingestion pipeline. Authentication is optional; set
``GITHUB_TOKEN`` to raise the unauthenticated rate limit (60 req/hr) to 5000.

Tests inject an ``httpx.AsyncClient`` backed by ``httpx.MockTransport`` so
the API integration behaviour is exercised without live network calls.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.errors import GitHubApiError, GitHubNotFoundError, GitHubRateLimitError


class GitHubClient:
    """Thin async wrapper around the GitHub REST API."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "trace/0.3",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._client = client or httpx.AsyncClient(
            base_url=settings.github_api_url.rstrip("/"),
            headers=headers,
            timeout=settings.github_timeout_seconds,
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Perform a request, mapping HTTP errors to typed exceptions.

        ``token`` overrides authentication for a single request (used when a
        developer connects via OAuth); it never mutates client-wide headers.
        """
        if token:
            kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
        attempts = 0
        while True:
            attempts += 1
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                if attempts > self._settings.github_retries:
                    raise GitHubApiError(f"network error for {path}: {exc}") from exc
                await asyncio.sleep(0.5 * attempts)
                continue

            if response.status_code == 404:
                raise GitHubNotFoundError(path)
            if response.status_code in (403, 429):
                # GitHub signals retry willingness via Retry-After (seconds).
                retry_after = response.headers.get("Retry-After")
                if retry_after and attempts <= self._settings.github_retries:
                    await asyncio.sleep(float(retry_after))
                    continue
                remaining = response.headers.get("X-RateLimit-Remaining")
                reset = response.headers.get("X-RateLimit-Reset")
                raise GitHubRateLimitError(
                    f"{path} (retry-after={retry_after}, remaining={remaining}, "
                    f"reset={reset})"
                )
            if response.status_code >= 500:
                if attempts > self._settings.github_retries:
                    raise GitHubApiError(f"{path} returned {response.status_code}")
                await asyncio.sleep(0.5 * attempts)
                continue

            response.raise_for_status()
            return response.json()

    async def _paginated(
        self,
        path: str,
        params: dict[str, Any],
        max_pages: int,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            page_params = {**params, "page": page}
            result = await self._request(
                "GET", path, params=page_params, token=token
            )
            if not isinstance(result, list):
                raise GitHubApiError(f"{path} did not return a list")
            items.extend(result)
            if len(result) < page_params["per_page"]:
                break
        return items

    async def get_user(
        self, username: str, *, token: str | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", f"/users/{username}", token=token)

    async def get_user_repos(
        self, username: str, *, token: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._paginated(
            f"/users/{username}/repos",
            params={"per_page": self._settings.ingestion_repos_per_page},
            max_pages=self._settings.ingestion_repos_max_pages,
            token=token,
        )

    async def get_repo_languages(
        self, full_name: str, *, token: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "GET", f"/repos/{full_name}/languages", token=token
        )

    async def get_user_events(
        self, username: str, *, token: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._paginated(
            f"/users/{username}/events",
            params={"per_page": self._settings.ingestion_events_per_page},
            max_pages=self._settings.ingestion_events_max_pages,
            token=token,
        )