"""High-level GitHub activity fetching, assembling a normalized bundle."""

from __future__ import annotations

import asyncio

from app.github import GitHubClient
from app.normalizers import (
    DeveloperBundle,
    NormalizedEvent,
    NormalizedRepo,
    NormalizedUser,
    normalize_event,
    normalize_repo,
    normalize_user,
)


class GitHubActivityService:
    """Fetches and normalizes all GitHub data for one developer sync."""

    def __init__(
        self,
        github: GitHubClient,
        language_repos_limit: int = 10,
    ) -> None:
        self._github = github
        self._language_repos_limit = language_repos_limit

    async def fetch_developer(self, username: str) -> DeveloperBundle:
        """Fetch user, repositories (with language breakdown) and events."""
        user_raw = await self._github.get_user(username)
        repos_raw = await self._github.get_user_repos(username)
        events_raw = await self._github.get_user_events(username)

        languages_by_repo = await self._fetch_languages(repos_raw)
        user: NormalizedUser = normalize_user(user_raw)
        repositories = [
            self._attach_languages(normalize_repo(raw), languages_by_repo)
            for raw in repos_raw
        ]
        events: list[NormalizedEvent] = [
            normalize_event(event) for event in events_raw
        ]

        return DeveloperBundle(user=user, repositories=repositories, events=events)

    async def _fetch_languages(
        self, repos_raw: list[dict]
    ) -> dict[str, dict[str, int]]:
        """Fetch per-repo language breakdowns for the top-referenced repos.

        The ``/users/{user}/repos`` payload only includes each repo's primary
        ``language``; per-language byte counts require one extra call per repo.
        We bound the sync by enriching only the ``language_repos_limit`` most
        recently pushed repositories. Failures are best-effort.
        """
        candidate = sorted(
            repos_raw,
            key=lambda r: (r.get("pushed_at") or r.get("updated_at") or ""),
            reverse=True,
        )[: self._language_repos_limit]

        full_names = [r.get("full_name") for r in candidate if r.get("full_name")]
        results = await asyncio.gather(
            *(self._github.get_repo_languages(name) for name in full_names),
            return_exceptions=True,
        )
        return {
            name: (result if isinstance(result, dict) else {})
            for name, result in zip(full_names, results, strict=True)
        }

    def _attach_languages(
        self, repo: NormalizedRepo, languages_by_repo: dict[str, dict[str, int]]
    ) -> NormalizedRepo:
        languages = languages_by_repo.get(repo.full_name)
        if not languages:
            return repo
        sorted_languages = dict(
            sorted(languages.items(), key=lambda kv: kv[1], reverse=True)
        )
        return NormalizedRepo(
            github_id=repo.github_id,
            name=repo.name,
            full_name=repo.full_name,
            description=repo.description,
            html_url=repo.html_url,
            homepage=repo.homepage,
            default_branch=repo.default_branch,
            language=repo.language,
            topics=repo.topics,
            languages=sorted_languages,
            is_fork=repo.is_fork,
            stargazers_count=repo.stargazers_count,
            forks_count=repo.forks_count,
            open_issues_count=repo.open_issues_count,
            watchers_count=repo.watchers_count,
            github_created_at=repo.github_created_at,
            github_updated_at=repo.github_updated_at,
            pushed_at=repo.pushed_at,
        )