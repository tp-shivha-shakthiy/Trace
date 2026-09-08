"""Core ingestion pipeline: fetch -> normalize -> persist (idempotent).

The pipeline is deliberately separated from the API layer so it can be
triggered from anywhere (background worker, tests, manual scripts):

1. ``GitHubActivityService`` fetches and normalizes a developer bundle.
2. The developer row is upserted (key: ``username``).
3. Repositories are upserted (key: ``github_id``), refreshing metadata and
   attaching the deterministic domain inference result.
4. Events are inserted with ``ON CONFLICT DO NOTHING`` (key:
   ``(developer_id, provider, github_event_id)``), so re-ingesting the same
   activity never duplicates rows.

All statements run inside a single transaction, so a sync is atomic.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.github import GitHubClient
from app.models import Developer, GithubEvent, Repository
from app.normalizers import DeveloperBundle, NormalizedEvent, NormalizedRepo
from app.services.domains import DomainInference, KeywordDomainInference
from app.services.github_activity import GitHubActivityService

_REPO_UPDATE_KEYS = frozenset(
    {
        "name",
        "full_name",
        "description",
        "html_url",
        "homepage",
        "default_branch",
        "language",
        "languages",
        "topics",
        "domains",
        "is_fork",
        "stargazers_count",
        "forks_count",
        "open_issues_count",
        "watchers_count",
        "github_created_at",
        "github_updated_at",
        "pushed_at",
    }
)


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of one developer sync."""

    developer_id: int
    username: str
    repositories_synced: int
    events_fetched: int
    events_persisted: int
    events_duplicates: int


def _repo_domains(repo: NormalizedRepo, inference: DomainInference) -> list[str]:
    languages = list(repo.languages.keys()) if repo.languages else []
    if not languages and repo.language:
        languages = [repo.language]
    return inference.infer_repository_domains(
        languages=languages,
        topics=repo.topics,
        name=repo.name,
        description=repo.description,
    )


def _repo_values(repo: NormalizedRepo, developer_id: int, domains: list[str]) -> dict:
    return {
        "developer_id": developer_id,
        "github_id": repo.github_id,
        "name": repo.name,
        "full_name": repo.full_name,
        "description": repo.description,
        "html_url": repo.html_url,
        "homepage": repo.homepage,
        "default_branch": repo.default_branch,
        "language": repo.language,
        "languages": repo.languages or {},
        "topics": repo.topics,
        "domains": domains,
        "is_fork": repo.is_fork,
        "stargazers_count": repo.stargazers_count,
        "forks_count": repo.forks_count,
        "open_issues_count": repo.open_issues_count,
        "watchers_count": repo.watchers_count,
        "github_created_at": repo.github_created_at,
        "github_updated_at": repo.github_updated_at,
        "pushed_at": repo.pushed_at,
    }


def _event_values(
    event: NormalizedEvent,
    developer_id: int,
    repository_ids: dict[str, int],
) -> dict:
    return {
        "developer_id": developer_id,
        "repository_id": (
            repository_ids.get(event.repository_full_name)
            if event.repository_full_name
            else None
        ),
        "provider": "github",
        "event_type": event.event_type,
        "github_event_id": event.github_event_id,
        "resource_id": event.resource_id,
        "occurred_at": event.occurred_at,
        "payload": event.payload,
    }


class IngestionService:
    """Runs the idempotent developer sync pipeline against PostgreSQL."""

    def __init__(
        self,
        github: GitHubClient,
        session_factory: async_sessionmaker[AsyncSession],
        domain_inference: DomainInference | None = None,
        language_repos_limit: int = 10,
    ) -> None:
        self._activity = GitHubActivityService(
            github, language_repos_limit=language_repos_limit
        )
        self._session_factory = session_factory
        self._domains = domain_inference or KeywordDomainInference()

    async def run(
        self, username: str, *, token: str | None = None
    ) -> IngestionResult:
        bundle = await self._activity.fetch_developer(username, token=token)
        async with self._session_factory() as session:
            async with session.begin():
                developer_id = await self._upsert_developer(session, bundle)
                repository_ids = await self._upsert_repositories(
                    session, bundle.repositories, developer_id
                )
                persisted, total = await self._insert_events(
                    session, bundle.events, developer_id, repository_ids
                )
        return IngestionResult(
            developer_id=developer_id,
            username=bundle.user.username,
            repositories_synced=len(bundle.repositories),
            events_fetched=total,
            events_persisted=persisted,
            events_duplicates=total - persisted,
        )

    async def _upsert_developer(
        self, session: AsyncSession, bundle: DeveloperBundle
    ) -> int:
        user = bundle.user
        values = {
            "github_id": user.github_id,
            "username": user.username,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "html_url": user.html_url,
            "company": user.company,
            "location": user.location,
            "bio": user.bio,
            "followers": user.followers,
            "following": user.following,
            "public_repos": user.public_repos,
        }
        stmt = (
            pg_insert(Developer)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Developer.username],
                set_={k: v for k, v in values.items() if k != "username"},
            )
            .returning(Developer.id)
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _upsert_repositories(
        self,
        session: AsyncSession,
        repos: list[NormalizedRepo],
        developer_id: int,
    ) -> dict[str, int]:
        """Upsert repo rows, returning a ``full_name -> repository_id`` map."""
        rows = [
            _repo_values(repo, developer_id, _repo_domains(repo, self._domains))
            for repo in repos
        ]
        if not rows:
            return {}
        stmt = (
            pg_insert(Repository)
            .values(rows)
            .on_conflict_do_update(
                index_elements=[Repository.github_id],
                set_={
                    key: getattr(pg_insert(Repository).excluded, key)
                    for key in _REPO_UPDATE_KEYS
                },
            )
            .returning(Repository.full_name, Repository.id)
        )
        result = await session.execute(stmt)
        return {full_name: repo_id for full_name, repo_id in result.all()}

    async def _insert_events(
        self,
        session: AsyncSession,
        events: list[NormalizedEvent],
        developer_id: int,
        repository_ids: dict[str, int],
    ) -> tuple[int, int]:
        """Insert events, skipping conflicts. Returns (persisted, total)."""
        total = len(events)
        if not events:
            return 0, 0
        rows = [_event_values(e, developer_id, repository_ids) for e in events]
        stmt = (
            pg_insert(GithubEvent)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_github_event_identity")
            .returning(GithubEvent.id)
        )
        result = await session.execute(stmt)
        persisted = len(result.all())
        return persisted, total