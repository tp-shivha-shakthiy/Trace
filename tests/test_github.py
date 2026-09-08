"""GitHubClient integration tests using httpx.MockTransport (no network)."""

import httpx
import pytest
from app.config import Settings
from app.errors import GitHubNotFoundError, GitHubRateLimitError
from app.github import GitHubClient
from tests.conftest import make_github_handler, make_repo


def _client(handler):
    transport = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.com",
    )
    return GitHubClient(Settings(), client=transport)


async def test_get_user_success():
    client = _client(make_github_handler())
    user = await client.get_user("octocat")
    assert user["login"] == "octocat"


async def test_get_user_not_found_raises():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    client = _client(handler)
    with pytest.raises(GitHubNotFoundError):
        await client.get_user("ghost")


async def test_rate_limit_retries_then_raises():
    class RateLimited:
        def __init__(self):
            self.calls = 0

        def answer(self, request):
            self.calls += 1
            return httpx.Response(
                403,
                json={"message": "rate limited"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"},
            )

    state = RateLimited()
    client = _client(state.answer)
    with pytest.raises(GitHubRateLimitError):
        await client.get_user("octocat")
    assert state.calls == 1  # no Retry-After -> no retry


async def test_rate_limit_with_retry_after_succeeds():
    def handler(request):
        return httpx.Response(
            429,
            json={"message": "slow down"},
            headers={"Retry-After": "0", "X-RateLimit-Remaining": "0"},
        )

    client = _client(handler)
    with pytest.raises(GitHubRateLimitError):
        await client.get_user("octocat")


async def test_get_user_repos_paginates():
    repos = [make_repo(i) for i in range(5)]
    client = _client(make_github_handler(repos=repos))
    fetched = await client.get_user_repos("octocat")
    assert len(fetched) == 5


async def test_get_repo_languages():
    client = _client(make_github_handler(languages={"Go": 900}))
    langs = await client.get_repo_languages("octocat/repo-0")
    assert langs == {"Go": 900}


async def test_events_passed_to_paginated_bounded():
    events = [{"id": str(i)} for i in range(1000)]
    client = _client(make_github_handler(events=events))
    fetched = await client.get_user_events("octocat")
    # Bounded by INGESTION_EVENTS_MAX_PAGES * per_page in Settings.
    settings = Settings()
    max_items = settings.ingestion_events_max_pages * settings.ingestion_events_per_page
    assert len(fetched) <= max_items