"""Developer profile assembly from persisted PostgreSQL data.

Profiles are always built from local database state (never by calling GitHub
at request time), which is what makes the profile endpoint the end-to-end
demonstration of the ingestion pipeline.

Visibility model
----------------

TRACE enforces the public/private boundary here, at the data-access layer:

* ``get_developer_profile`` builds the **public** profile for a developer —
  it only ever reads public repositories and public activity, so it can be
  served to any other user (or an anonymous visitor) without leaking private
  repositories, private activity, or intelligence derived exclusively from
  private data (language/domain signals are recomputed over the visible
  subset only).
* ``get_my_profile`` builds the **full** (owner) profile for the *authenticated
  developer* passed in by the caller — it includes private repositories and
  private activity. It is only reachable via the authenticated ``/me``
  endpoints, never through a client-supplied developer id.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import DeveloperNotFoundError
from app.models import Developer, GithubEvent, Repository
from app.services.domains import (
    DomainAggregate,
    KeywordDomainInference,
    RepositoryDomainEvidence,
    aggregate_repository_domains,
)

RECENT_EVENTS_LIMIT = 10
TOP_REPOSITORIES_LIMIT = 20
TOP_LANGUAGES_LIMIT = 10
ACTIVITY_MONTHS_LIMIT = 12

# Deterministic, stateless inference; recomputed on every profile read from
# the persisted evidence so results always reflect the latest database state.
_DEVELOPER_INFERENCE = KeywordDomainInference()


def _repo_language_list(repo: Repository) -> list[str]:
    if repo.languages:
        return [lang for lang in repo.languages if isinstance(lang, str)]
    if repo.language:
        return [repo.language]
    return []


def _aggregate_languages(repos: list[Repository]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for repo in repos:
        for language in _repo_language_list(repo):
            counts[language] = counts.get(language, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {language: count for language, count in top[:TOP_LANGUAGES_LIMIT]}


def _aggregate_domains(repos: list[Repository]) -> dict[str, DomainAggregate]:
    pairs = [
        (repo.full_name, repo.domains or [])
        for repo in repos
        if repo.domains
    ]
    return aggregate_repository_domains(pairs)


def _public_event_filter():
    """Filter that keeps only events which are safe to expose publicly.

    An event is public when it is not flagged private itself and it does not
    belong to a private repository (the two flags are set together at
    ingestion, but checking both protects against legacy/partial data).
    """
    return (GithubEvent.is_private.is_(False)) & or_(
        Repository.id.is_(None),
        Repository.is_private.is_(False),
    )


async def get_developer_profile(session: AsyncSession, username: str) -> dict:
    """Build the public developer profile (visible to any other user).

    Private repositories, private activity, and any intelligence derived
    exclusively from private data are excluded at the query level.
    """
    developer = await session.scalar(
        select(Developer).where(Developer.username == username)
    )
    if developer is None:
        raise DeveloperNotFoundError(username)
    return await _assemble_profile(
        session, developer, include_private=False, is_owner=False
    )


async def get_my_profile(
    session: AsyncSession, developer: Developer
) -> dict:
    """Build the full owner profile for the *authenticated* developer.

    The caller is the dependency-injected current developer, so ownership is
    the identity itself — no client-supplied id or username is trusted.
    """
    return await _assemble_profile(
        session, developer, include_private=True, is_owner=True
    )


async def _assemble_profile(
    session: AsyncSession,
    developer: Developer,
    *,
    include_private: bool,
    is_owner: bool,
) -> dict:
    """Assemble a profile from either the full or public data subset."""
    repo_query = select(Repository).where(Repository.developer_id == developer.id)
    if not include_private:
        repo_query = repo_query.where(Repository.is_private.is_(False))
    repo_query = repo_query.order_by(
        Repository.stargazers_count.desc(),
        Repository.name.asc(),
    )
    repos = list((await session.scalars(repo_query)).all())

    repo_by_id = {repo.id: repo for repo in repos}

    recent_query = select(GithubEvent).where(
        GithubEvent.developer_id == developer.id
    )
    count_query = select(
        GithubEvent.repository_id,
        GithubEvent.event_type,
        func.count().label("count"),
    ).where(GithubEvent.developer_id == developer.id)
    month_expr = func.to_char(
        func.date_trunc("month", GithubEvent.occurred_at), "YYYY-MM"
    )
    month_query = select(
        month_expr.label("month"),
        func.count().label("count"),
    ).where(GithubEvent.developer_id == developer.id)

    if not include_private:
        recent_query = recent_query.outerjoin(
            Repository, GithubEvent.repository_id == Repository.id
        ).where(_public_event_filter())
        count_query = count_query.outerjoin(
            Repository, GithubEvent.repository_id == Repository.id
        ).where(_public_event_filter())
        month_query = month_query.outerjoin(
            Repository, GithubEvent.repository_id == Repository.id
        ).where(_public_event_filter())

    recent_events = list(
        (
            await session.scalars(
                recent_query.order_by(GithubEvent.occurred_at.desc()).limit(
                    RECENT_EVENTS_LIMIT
                )
            )
        ).all()
    )

    # Per-repo / per-type event counts from a single grouped query.
    event_rows = list(
        (
            await session.execute(
                count_query.group_by(
                    GithubEvent.repository_id, GithubEvent.event_type
                )
            )
        ).all()
    )

    total_events = sum(row.count for row in event_rows)
    events_by_type: dict[str, int] = {}
    events_by_repo: dict[int, int] = {}
    events_by_domain: dict[str, int] = {}
    for row in event_rows:
        events_by_type[row.event_type] = (
            events_by_type.get(row.event_type, 0) + row.count
        )
        events_by_repo[row.repository_id] = (
            events_by_repo.get(row.repository_id, 0) + row.count
        )
        repo = repo_by_id.get(row.repository_id)
        if repo and repo.domains:
            for domain in repo.domains:
                events_by_domain[domain] = (
                    events_by_domain.get(domain, 0) + row.count
                )

    # Monthly event totals (last 12 months, ascending).
    month_rows = list(
        (
            await session.execute(
                month_query.group_by(month_expr)
                .order_by(month_expr.desc())
                .limit(ACTIVITY_MONTHS_LIMIT)
            )
        ).all()
    )

    last_activity_at = recent_events[0].occurred_at if recent_events else None

    domain_signals = _DEVELOPER_INFERENCE.infer_developer_domains(
        repositories=[
            RepositoryDomainEvidence(
                full_name=repo.full_name,
                name=repo.name,
                description=repo.description,
                primary_language=repo.language,
                languages=repo.languages or {},
                topics=repo.topics or [],
                event_count=events_by_repo.get(repo.id, 0),
            )
            for repo in repos
        ]
    )

    return {
        "username": developer.username,
        "name": developer.name,
        "avatar_url": developer.avatar_url,
        "html_url": developer.html_url,
        "bio": developer.bio,
        "location": developer.location,
        "company": developer.company,
        "public_repos": developer.public_repos,
        "followers": developer.followers,
        "following": developer.following,
        "is_owner": is_owner,
        "summary": {
            "total_repositories": len(repo_by_id),
            "total_events": total_events,
            "languages": _aggregate_languages(repos),
            "domains": _aggregate_domains(repos),
            "domain_signals": [
                {
                    "domain": signal.domain,
                    "score": signal.score,
                    "confidence": signal.confidence,
                    "evidence": signal.evidence,
                    "repository_count": signal.repository_count,
                }
                for signal in domain_signals
            ],
            "events_by_domain": events_by_domain,
            "activity": events_by_type,
            "events_per_month": [
                {"month": row.month, "events": row.count}
                for row in reversed(month_rows)
            ],
            "last_activity_at": last_activity_at,
        },
        "repositories": [
            {
                "full_name": repo.full_name,
                "name": repo.name,
                "html_url": repo.html_url,
                "description": repo.description,
                "language": repo.language,
                "languages": [lang for lang in _repo_language_list(repo)],
                "topics": repo.topics or [],
                "domains": repo.domains or [],
                "is_private": repo.is_private,
                "stargazers_count": repo.stargazers_count,
                "forks_count": repo.forks_count,
                "pushed_at": repo.pushed_at,
                "event_count": events_by_repo.get(repo.id, 0),
            }
            for repo in repos[:TOP_REPOSITORIES_LIMIT]
        ],
        "recent_activity": [
            {
                "event_type": event.event_type,
                "resource_id": event.resource_id,
                "repository": (
                    repo_by_id[event.repository_id].full_name
                    if event.repository_id in repo_by_id
                    else None
                ),
                "occurred_at": event.occurred_at,
            }
            for event in recent_events
        ],
    }


async def list_developers(session: AsyncSession) -> list[dict]:
    """Return brief public profiles for every ingested developer.

    Event counts reflect publicly visible activity only.
    """
    developers = list((await session.scalars(select(Developer))).all())
    result: list[dict] = []
    for developer in developers:
        total_events = (
            await session.scalar(
                select(func.count())
                .select_from(GithubEvent)
                .outerjoin(Repository, GithubEvent.repository_id == Repository.id)
                .where(
                    GithubEvent.developer_id == developer.id,
                    _public_event_filter(),
                )
            )
        ) or 0
        last_sync = await session.scalar(
            select(func.max(GithubEvent.received_at))
            .select_from(GithubEvent)
            .outerjoin(Repository, GithubEvent.repository_id == Repository.id)
            .where(
                GithubEvent.developer_id == developer.id,
                _public_event_filter(),
            )
        )
        result.append(
            {
                "username": developer.username,
                "name": developer.name,
                "avatar_url": developer.avatar_url,
                "html_url": developer.html_url,
                "public_repos": developer.public_repos,
                "total_events": total_events,
                "last_synced_at": last_sync,
            }
        )
    return result