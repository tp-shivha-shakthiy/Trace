"""Normalization of raw GitHub API payloads into TRACE's unified event model.

Every GitHub object (user, repository, event) is converted into a
provider-agnostic internal representation here. Downstream code only ever
sees these normalized shapes, which keeps the ingestion pipeline decoupled
from the GitHub API schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string into a timezone-aware datetime (or None)."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@dataclass(frozen=True)
class NormalizedUser:
    github_id: int
    username: str
    name: str | None
    avatar_url: str | None
    html_url: str | None
    company: str | None
    location: str | None
    bio: str | None
    followers: int
    following: int
    public_repos: int


@dataclass(frozen=True)
class NormalizedRepo:
    github_id: int
    name: str
    full_name: str
    description: str | None
    html_url: str | None
    homepage: str | None
    default_branch: str | None
    language: str | None
    topics: list[str]
    languages: dict[str, int]
    is_fork: bool
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    watchers_count: int
    github_created_at: datetime | None
    github_updated_at: datetime | None
    pushed_at: datetime | None


@dataclass(frozen=True)
class NormalizedEvent:
    event_type: str
    github_event_id: str
    resource_id: str | None
    repository_full_name: str | None
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class DeveloperBundle:
    """Everything fetched from GitHub for one developer in one sync."""

    user: NormalizedUser
    repositories: list[NormalizedRepo] = field(default_factory=list)
    events: list[NormalizedEvent] = field(default_factory=list)


# GitHub event type -> TRACE unified event type. Events not listed here keep a
# slugified version of their GitHub type.
_EVENT_TYPE_MAP = {
    "PushEvent": "commit",
    "CreateEvent": "repository_created",
    "PullRequestEvent": "pull_request",
    "PullRequestReviewEvent": "pull_request_review",
    "PullRequestReviewCommentEvent": "pull_request_review_comment",
    "IssuesEvent": "issue",
    "IssueCommentEvent": "issue_comment",
    "ReleaseEvent": "release_created",
    "WatchEvent": "repo_watched",
    "ForkEvent": "repo_forked",
    "DeleteEvent": "branch_deleted",
    "MemberEvent": "collaborator_added",
}


def _slugify_event_type(event_type: str) -> str:
    result = []
    for char in event_type:
        if char.isalpha() or char.isdigit():
            if char.isupper() and result:
                result.append("_")
            result.append(char.lower())
    return "".join(result).strip("_")


def normalize_event_type(raw_type: str) -> str:
    """Map a GitHub event type to a TRACE unified event type."""
    return _EVENT_TYPE_MAP.get(raw_type, _slugify_event_type(raw_type))


def _resource_id(event_type: str, payload: dict[str, Any]) -> str | None:
    """Derive a stable resource identifier from an event payload."""
    if event_type == "PushEvent":
        return payload.get("ref")
    if event_type in ("PullRequestEvent", "PullRequestReviewEvent"):
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        return f"pr/{number}" if number is not None else None
    if event_type == "IssuesEvent":
        issue = payload.get("issue") or {}
        number = issue.get("number")
        return f"issue/{number}" if number is not None else None
    if event_type == "ReleaseEvent":
        release = payload.get("release") or {}
        return release.get("tag_name")
    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type")
        ref = payload.get("ref") or ""
        return f"{ref_type}/{ref}" if ref_type else None
    return None


def normalize_user(raw: dict[str, Any]) -> NormalizedUser:
    return NormalizedUser(
        github_id=int(raw.get("id", 0)),
        username=str(raw.get("login", "")),
        name=raw.get("name"),
        avatar_url=raw.get("avatar_url"),
        html_url=raw.get("html_url"),
        company=raw.get("company"),
        location=raw.get("location"),
        bio=raw.get("bio"),
        followers=int(raw.get("followers") or 0),
        following=int(raw.get("following") or 0),
        public_repos=int(raw.get("public_repos") or 0),
    )


def _repo_languages(raw: dict[str, Any]) -> dict[str, int]:
    languages = raw.get("languages")
    if isinstance(languages, dict):
        return {str(k): int(v) for k, v in languages.items()}
    return {}


def normalize_repo(raw: dict[str, Any]) -> NormalizedRepo:
    topics = raw.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    return NormalizedRepo(
        github_id=int(raw.get("id", 0)),
        name=str(raw.get("name", "")),
        full_name=str(raw.get("full_name", "")),
        description=raw.get("description"),
        html_url=raw.get("html_url"),
        homepage=raw.get("homepage"),
        default_branch=raw.get("default_branch"),
        language=raw.get("language"),
        topics=[str(t) for t in topics],
        languages=_repo_languages(raw),
        is_fork=bool(raw.get("fork", False)),
        stargazers_count=int(raw.get("stargazers_count") or 0),
        forks_count=int(raw.get("forks_count") or 0),
        open_issues_count=int(raw.get("open_issues_count") or 0),
        watchers_count=int(raw.get("watchers_count") or 0),
        github_created_at=parse_iso(raw.get("created_at")),
        github_updated_at=parse_iso(raw.get("updated_at")),
        pushed_at=parse_iso(raw.get("pushed_at")),
    )


def normalize_event(raw: dict[str, Any]) -> NormalizedEvent:
    raw_type = str(raw.get("type") or "Unknown")
    event_type = normalize_event_type(raw_type)
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    repo = raw.get("repo") or {}
    full_name = repo.get("name") if isinstance(repo, dict) else None
    occurred_at = parse_iso(raw.get("created_at")) or datetime.now(UTC)
    return NormalizedEvent(
        event_type=event_type,
        github_event_id=str(raw.get("id") or ""),
        resource_id=_resource_id(raw_type, payload),
        repository_full_name=str(full_name) if full_name else None,
        occurred_at=occurred_at,
        payload=payload,
    )