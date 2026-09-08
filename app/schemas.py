"""Pydantic request/response schemas for the public API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str


class SyncRequest(BaseModel):
    username: str = Field(min_length=1, max_length=39)


class SyncCreatedResponse(BaseModel):
    job_id: str
    developer_username: str
    status: str


class SyncJobResponse(BaseModel):
    id: str
    developer_username: str
    developer_id: int | None
    status: str
    error_message: str | None
    events_fetched: int
    events_persisted: int
    events_duplicates: int
    repositories_synced: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DomainAggregateResponse(BaseModel):
    repository_count: int
    repository_names: list[str]


class DomainSignalResponse(BaseModel):
    domain: str
    score: float
    confidence: str
    evidence: list[str]
    repository_count: int


class EventMonthResponse(BaseModel):
    month: str
    events: int


class DeveloperSummaryResponse(BaseModel):
    total_repositories: int
    total_events: int
    languages: dict[str, int]
    domains: dict[str, DomainAggregateResponse]
    domain_signals: list[DomainSignalResponse]
    events_by_domain: dict[str, int]
    activity: dict[str, int]
    events_per_month: list[EventMonthResponse]
    last_activity_at: datetime | None


class RepositorySummaryResponse(BaseModel):
    full_name: str
    name: str
    html_url: str | None
    description: str | None
    language: str | None
    languages: list[str]
    topics: list[str]
    domains: list[str]
    stargazers_count: int
    forks_count: int
    pushed_at: datetime | None
    event_count: int


class RecentActivityResponse(BaseModel):
    event_type: str
    resource_id: str | None
    repository: str | None
    occurred_at: datetime


class DeveloperProfileResponse(BaseModel):
    username: str
    name: str | None
    avatar_url: str | None
    html_url: str | None
    bio: str | None
    location: str | None
    company: str | None
    public_repos: int
    followers: int
    following: int
    summary: DeveloperSummaryResponse
    repositories: list[RepositorySummaryResponse]
    recent_activity: list[RecentActivityResponse]


class DeveloperListItemResponse(BaseModel):
    username: str
    name: str | None
    avatar_url: str | None
    html_url: str | None
    public_repos: int
    total_events: int
    last_synced_at: datetime | None