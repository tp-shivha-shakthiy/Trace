"""SQLAlchemy ORM models for TRACE's PostgreSQL persistence layer.

Tables:

* ``developers``      - developer/user accounts synced from GitHub
* ``repositories``    - repositories owned by a developer
* ``github_events``   - normalized, immutable GitHub activity events
* ``sync_jobs``       - background ingestion jobs (async processing status)
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Developer(Base, TimestampMixin):
    __tablename__ = "developers"
    __table_args__ = (
        UniqueConstraint("username", name="uq_developers_username"),
        UniqueConstraint("github_id", name="uq_developers_github_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(39), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    following: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    public_repos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # OAuth access token for this developer (used for their syncs only).
    # Never exposed by the API.
    github_token: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("github_id", name="uq_repositories_github_id"),
        UniqueConstraint("full_name", name="uq_repositories_full_name"),
        Index("ix_repositories_developer_id", "developer_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer_id: Mapped[int] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE"), nullable=False
    )
    github_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    language: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Language byte counts, e.g. {"Python": 1287, "HTML": 300}
    languages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # GitHub topics, e.g. ["api", "python"]
    topics: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Inferred coarse technical domains, e.g. ["backend", "devops"]
    domains: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_fork: Mapped[bool] = mapped_column(nullable=False, default=False)
    stargazers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    forks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_issues_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    watchers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    github_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    github_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pushed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GithubEvent(Base):
    __tablename__ = "github_events"
    __table_args__ = (
        # Idempotency key: the same GitHub event must never be stored twice
        # for the same developer, regardless of how many times it is ingested.
        UniqueConstraint(
            "developer_id",
            "provider",
            "github_event_id",
            name="uq_github_event_identity",
        ),
        Index("ix_github_events_developer_occurred", "developer_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    developer_id: Mapped[int] = mapped_column(
        ForeignKey("developers.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), default="github", nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    github_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_jobs_developer_username", "developer_username"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    developer_username: Mapped[str] = mapped_column(String(39), nullable=False)
    developer_id: Mapped[int | None] = mapped_column(
        ForeignKey("developers.id", ondelete="SET NULL"), nullable=True
    )
    # queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    events_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    events_persisted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    events_duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repositories_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )