"""Tests for TRACE Intelligence V1 response schemas and the pure intelligence
service.

These are pure-function tests: no database, ownership scoping, or snapshot
deletion is exercised here. Database-backed ownership behaviour of profiles is
covered by ``test_auth.py`` and ``test_fetched_ownership.py``; there is not
yet a database-backed test asserting the ``intelligence`` field per owner.
"""

from datetime import UTC, datetime

import pytest
from app.schemas import (
    DeveloperProfileResponse,
)
from app.services.domains import (
    IntelligenceService,
    KeywordDomainInference,
    RepositoryDomainEvidence,
)
from pydantic import ValidationError


def _sample_profile_dict(intelligence=None) -> dict:
    return {
        "username": "octocat",
        "name": "Mona",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231",
        "html_url": "https://github.com/octocat",
        "bio": "Building things",
        "location": "San Francisco",
        "company": "GitHub",
        "public_repos": 2,
        "followers": 100,
        "following": 50,
        "is_owner": False,
        "is_fetched": False,
        "summary": {
            "total_repositories": 2,
            "total_events": 10,
            "languages": {"Python": 2},
            "domains": {},
            "domain_signals": [],
            "events_by_domain": {},
            "activity": {},
            "events_per_month": [],
            "last_activity_at": datetime.now(UTC),
        },
        "repositories": [],
        "recent_activity": [],
        "intelligence": intelligence or {"domains": []},
    }


def test_developer_profile_response_schema_validation():
    intelligence_data = {
        "domains": [
            {
                "name": "Backend",
                "strength": "strong",
                "score": 0.85,
                "repository_count": 2,
                "repositories": [
                    {
                        "full_name": "octocat/api-service",
                        "name": "api-service",
                        "evidence": [
                            {"type": "language", "value": "Python"},
                            {"type": "topic", "value": "fastapi"},
                        ],
                    }
                ],
            }
        ]
    }
    raw = _sample_profile_dict(intelligence=intelligence_data)
    profile = DeveloperProfileResponse.model_validate(raw)

    assert profile.username == "octocat"
    assert profile.intelligence is not None
    assert len(profile.intelligence.domains) == 1
    backend = profile.intelligence.domains[0]
    assert backend.name == "Backend"
    assert backend.strength == "strong"
    assert backend.score == 0.85
    assert backend.repository_count == 2
    assert len(backend.repositories) == 1
    assert backend.repositories[0].full_name == "octocat/api-service"
    assert backend.repositories[0].name == "api-service"
    assert backend.repositories[0].evidence[0].value == "Python"


def test_developer_profile_response_without_intelligence_defaults_to_none():
    raw = _sample_profile_dict()
    del raw["intelligence"]
    profile = DeveloperProfileResponse.model_validate(raw)
    assert profile.intelligence is None


def test_invalid_intelligence_schema_raises_validation_error():
    raw = _sample_profile_dict(
        intelligence={
            "domains": [
                {
                    "name": "Backend",
                    # Missing required fields like 'strength', 'score', etc.
                }
            ]
        }
    )
    with pytest.raises(ValidationError):
        DeveloperProfileResponse.model_validate(raw)


def test_intelligence_is_derived_only_from_the_given_repositories():
    """The service's output depends only on the repository list passed in.

    One non-empty list yields domains drawn from exactly those repositories;
    an independent empty list yields no domains. (Pure function: this does
    not test database ownership scoping.)
    """
    service = IntelligenceService(KeywordDomainInference())

    alice_repos = [
        RepositoryDomainEvidence(
            full_name="target/alice-copy-api",
            name="alice-copy-api",
            description="Alice fetched backend service",
            primary_language="Python",
            languages={"Python": 4000},
            topics=["api", "fastapi"],
            event_count=25,
        )
    ]
    bob_repos: list[RepositoryDomainEvidence] = []

    alice_intel = service.build_developer_intelligence(alice_repos)
    bob_intel = service.build_developer_intelligence(bob_repos)

    # Output reflects exactly the repositories that were passed in
    alice_domains = {d.name: d for d in alice_intel.domains}
    assert "Backend" in alice_domains
    assert alice_domains["Backend"].repository_count == 1
    assert alice_domains["Backend"].repositories[0].name == "alice-copy-api"

    # An empty repository list -> no intelligence
    assert len(bob_intel.domains) == 0


def test_intelligence_is_empty_once_repositories_are_removed_from_input():
    """Recomputing over an empty repository list yields no domains.

    (Pure function: this does not exercise the delete endpoint or any stored
    snapshot; intelligence is not persisted yet.)
    """
    service = IntelligenceService(KeywordDomainInference())

    repos = [
        RepositoryDomainEvidence(
            full_name="dev/analytics",
            name="analytics",
            description="ETL analytics pipeline",
            primary_language="Python",
            languages={"Python": 3000},
            topics=["data", "etl"],
            event_count=10,
        )
    ]

    before_delete = service.build_developer_intelligence(repos)
    assert any(d.name == "Data" for d in before_delete.domains)

    # Recompute with the repositories removed from the input
    empty_after_delete: list[RepositoryDomainEvidence] = []
    after_delete = service.build_developer_intelligence(empty_after_delete)
    assert len(after_delete.domains) == 0
