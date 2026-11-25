"""Tests for the deterministic domain inference baseline."""

from app.services.domains import (
    KeywordDomainInference,
    RepositoryDomainEvidence,
    _language_domains,
    aggregate_repository_domains,
)


def test_language_domains_exact_match():
    assert "backend" in _language_domains("Python")
    assert "frontend" in _language_domains("JavaScript")
    assert "mobile" in _language_domains("Swift")
    assert _language_domains("NeverLanguageHere") == set()


def test_language_domains_case_insensitive():
    assert "backend" in _language_domains("python")
    assert "mobile" in _language_domains("SWIFT")


def test_infer_backend_from_python():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=["Python"], topics=[], name="demo", description=None
    )
    assert "backend" in domains


def test_infer_frontend_from_topics():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=[], topics=["frontend", "react"], name="app", description=None
    )
    assert "frontend" in domains


def test_infer_ml_from_keywords_in_description():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=[], topics=[], name="research",
        description="A pytorch model for nlp tasks with deep-learning."
    )
    assert "ml" in domains


def test_infer_devops_from_topics_and_name():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=[], topics=["kubernetes", "terraform", "deployment"],
        name="infra", description=None
    )
    assert "devops" in domains


def test_infer_multiple_domains():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=["Python", "Go"],
        topics=["api", "docker"],
        name="pipeline",
        description="A data pipeline service with database integration."
    )
    assert "backend" in domains
    assert "data" in domains


def test_max_domains_cap():
    inf = KeywordDomainInference()
    domains = inf.infer_repository_domains(
        languages=["Python", "JavaScript", "Go", "Rust"],
        topics=[
            "api", "docker", "security", "machine-learning",
            "frontend", "mobile", "game", "testing", "compiler",
        ],
        name="mega",
        description="A full-stack security testing game platform with "
                    "kernel embedded systems."
    )
    assert len(domains) <= 3


def test_aggregate_repository_domains():
    repos = [
        ("owner/a", ["backend"]),
        ("owner/b", ["backend", "devops"]),
        ("owner/c", ["data"]),
    ]
    agg = aggregate_repository_domains(repos)
    assert agg["backend"].repository_count == 2
    assert agg["devops"].repository_count == 1
    assert "owner/a" in agg["backend"].repository_names
    assert "owner/b" in agg["backend"].repository_names


def test_aggregate_empty():
    assert aggregate_repository_domains([]) == {}


# ---------------------------------------------------------------------------
# Developer-level inference (v0.4 domain signals)
# ---------------------------------------------------------------------------

INFERENCE = KeywordDomainInference()


def evidence(
    full_name,
    *,
    languages=None,
    primary_language=None,
    topics=None,
    description=None,
    event_count=0,
):
    return RepositoryDomainEvidence(
        full_name=full_name,
        name=full_name.split("/")[-1],
        description=description,
        primary_language=primary_language,
        languages=languages or {},
        topics=topics or [],
        event_count=event_count,
    )


def _by_domain(results):
    return {result.domain: result for result in results}


def test_strong_backend_evidence_is_high_confidence():
    repos = [
        evidence(
            "dev/auth-api",
            languages={"Python": 4000},
            topics=["api", "backend"],
            description="REST authentication microservice",
            event_count=120,
        ),
        evidence(
            "dev/billing",
            languages={"Go": 2000},
            topics=["microservice"],
            description="Billing microservice API",
            event_count=60,
        ),
    ]
    results = _by_domain(INFERENCE.infer_developer_domains(repositories=repos))

    backend = results["backend"]
    assert backend.confidence == "high"
    assert backend.repository_count == 2
    assert 0 < backend.score <= 1.0
    assert len(backend.evidence) >= 2
    assert any("language" in line for line in backend.evidence)
    assert any("activity" in line for line in backend.evidence)


def test_strong_frontend_evidence_is_high_confidence():
    repos = [
        evidence(
            "dev/dashboard",
            languages={"TypeScript": 5000, "CSS": 1000},
            topics=["react", "frontend"],
            description="customer analytics dashboard",
            event_count=90,
        ),
        evidence(
            "dev/web-app",
            languages={"JavaScript": 3000},
            topics=["ui"],
            description="responsive frontend app",
            event_count=40,
        ),
    ]
    results = _by_domain(INFERENCE.infer_developer_domains(repositories=repos))

    frontend = results["frontend"]
    assert frontend is not None
    assert frontend.confidence == "high"
    assert frontend.repository_count == 2
    assert any("keyword" in line for line in frontend.evidence)


def test_mixed_domain_repositories():
    repos = [
        evidence(
            "dev/api",
            languages={"Python": 5000},
            topics=["backend", "api"],
            description="backend service API",
            event_count=30,
        ),
        evidence(
            "dev/web",
            languages={"TypeScript": 4000},
            topics=["react", "frontend"],
            description="frontend react app",
            event_count=30,
        ),
    ]
    results = _by_domain(INFERENCE.infer_developer_domains(repositories=repos))

    assert "backend" in results
    assert "frontend" in results


def test_sparse_repository_metadata_stays_low_confidence():
    results = _by_domain(
        INFERENCE.infer_developer_domains(
            repositories=[
                evidence(
                    "dev/lonely",
                    languages={"Python": 1500},
                    topics=[],
                    description=None,
                    event_count=0,
                )
            ]
        )
    )

    backend = results.get("backend")
    assert backend is not None
    assert backend.confidence == "low"
    assert backend.score <= 0.5
    assert backend.repository_count == 1


def test_no_evidence_produces_no_domains():
    results = INFERENCE.infer_developer_domains(
        repositories=[
            evidence(
                "dev/scratch",
                languages={},
                primary_language=None,
                topics=[],
                description=None,
                event_count=8,
            )
        ]
    )
    assert results == []


def test_multiple_independent_signals_raise_confidence():
    plain = _by_domain(
        INFERENCE.infer_developer_domains(
            repositories=[evidence("dev/usertools", languages={"Python": 1000})]
        )
    )
    described = _by_domain(
        INFERENCE.infer_developer_domains(
            repositories=[
                evidence(
                    "dev/api",
                    languages={"Python": 1000},
                    topics=["api", "backend"],
                    description=None,
                    event_count=15,
                )
            ]
        )
    )

    assert plain["backend"].confidence == "low"
    assert described["backend"].confidence == "medium"
    assert described["backend"].score >= plain["backend"].score


def test_weak_single_signal_never_high_confidence():
    results = _by_domain(
        INFERENCE.infer_developer_domains(
            repositories=[
                evidence(
                    "dev/research",
                    languages={},
                    primary_language=None,
                    topics=["machine-learning"],
                    description=None,
                    event_count=0,
                )
            ]
        )
    )

    ml = results["ml"]
    assert ml.confidence == "low"
    assert ml.score < 0.5
    assert ml.repository_count == 1


def test_inference_is_deterministic():
    repos = [
        evidence(
            "dev/api",
            languages={"Python": 4000},
            topics=["api", "backend"],
            description="REST service",
            event_count=50,
        ),
        evidence(
            "dev/web",
            languages={"TypeScript": 2000},
            topics=["react"],
            description="dashboard",
            event_count=10,
        ),
    ]
    first = INFERENCE.infer_developer_domains(repositories=repos)
    second = INFERENCE.infer_developer_domains(repositories=repos)
    assert first == second


def test_all_scores_are_bounded_and_nonnegative():
    repos = [
        evidence(
            "dev/a",
            languages={"Python": 1, "Go": 1, "JavaScript": 1, "Rust": 1},
            topics=["api", "docker", "frontend", "game", "mobile",
                    "security", "machine-learning", "testing", "compiler"],
            description="everything",
            event_count=200,
        ),
        evidence("dev/b", languages={"R": 5000}, topics=["data"], event_count=40),
    ]
    results = INFERENCE.infer_developer_domains(repositories=repos)
    assert results
    for result in results:
        assert 0 < result.score <= 1.0
        assert result.confidence in {"high", "medium", "low"}
        assert result.repository_count >= 1
        assert result.evidence


# ---------------------------------------------------------------------------
# TRACE Intelligence V1 Tests
# ---------------------------------------------------------------------------


def test_known_language_produces_expected_evidence():
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "org/backend-service",
                languages={"Python": 3000},
                topics=[],
                description=None,
            )
        ]
    )
    by_name = {d.name: d for d in intel.domains}
    assert "Backend" in by_name
    backend = by_name["Backend"]
    assert backend.repository_count == 1
    repo = backend.repositories[0]
    assert repo.name == "backend-service"
    sig_types = {e.type: e.value for e in repo.evidence}
    assert sig_types.get("language") == "Python"


def test_known_topic_produces_expected_evidence():
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "org/cloud-infra",
                languages={},
                topics=["terraform", "kubernetes"],
                description=None,
            )
        ]
    )
    by_name = {d.name: d for d in intel.domains}
    assert "DevOps" in by_name
    devops = by_name["DevOps"]
    repo = devops.repositories[0]
    topics = [e.value for e in repo.evidence if e.type == "topic"]
    assert "terraform" in topics or "kubernetes" in topics


def test_name_and_description_keyword_signals():
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "org/api-gateway",
                languages={},
                topics=[],
                description="High throughput microservice with postgresql support",
            )
        ]
    )
    by_name = {d.name: d for d in intel.domains}
    assert "Backend" in by_name
    backend = by_name["Backend"]
    repo = backend.repositories[0]
    kw_values = [e.value for e in repo.evidence if e.type == "keyword"]
    assert any(k in kw_values for k in ["api", "microservice", "postgresql"])


def test_unknown_repository_produces_no_false_domain():
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "org/unknown-thing",
                languages={"NonExistentLang123": 1000},
                topics=["unrelatedtopic99"],
                description="Random description without domain terms",
            )
        ]
    )
    assert len(intel.domains) == 0


def test_duplicate_signals_are_deduplicated():
    # "fastapi" in name, description, and topics
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "org/fastapi-project",
                languages={},
                topics=["fastapi"],
                description="A fastapi backend project",
            )
        ]
    )
    by_name = {d.name: d for d in intel.domains}
    backend = by_name.get("Backend")
    assert backend is not None
    repo = backend.repositories[0]
    # "fastapi" should be captured as topic, and not duplicated into keyword
    fastapi_signals = [e for e in repo.evidence if e.value.lower() == "fastapi"]
    assert len(fastapi_signals) == 1
    assert fastapi_signals[0].type == "topic"


def test_scoring_and_thresholds_are_deterministic():
    repos = [
        evidence(
            "dev/auth",
            languages={"Python": 5000},
            topics=["api", "backend", "fastapi"],
            description="FastAPI authentication service",
            event_count=80,
        ),
        evidence(
            "dev/gateway",
            languages={"Go": 3000},
            topics=["api", "microservice"],
            description="API gateway service",
            event_count=40,
        ),
    ]
    res1 = INFERENCE.infer_developer_intelligence(repositories=repos)
    res2 = INFERENCE.infer_developer_intelligence(repositories=repos)
    assert res1 == res2

    by_name = {d.name: d for d in res1.domains}
    backend = by_name["Backend"]
    assert backend.strength == "strong"
    assert backend.score >= 0.70
    assert backend.repository_count == 2


def test_minimum_evidence_rule_rejects_single_weak_keyword():
    # Only repo name contains "data", with no language, topics, or second keyword
    intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "dev/my-data",
                languages={},
                topics=[],
                description=None,
                event_count=0,
            )
        ]
    )
    by_name = {d.name: d for d in intel.domains}
    assert "Data" not in by_name


def test_minimum_evidence_rule_accepts_topics_and_languages():
    # Topic data alone should pass
    topic_intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "dev/experiment",
                languages={},
                topics=["data"],
                description=None,
            )
        ]
    )
    assert "Data" in {d.name for d in topic_intel.domains}

    # Language alone should pass
    lang_intel = INFERENCE.infer_developer_intelligence(
        repositories=[
            evidence(
                "dev/queries",
                languages={"SQL": 1000},
                topics=[],
                description=None,
            )
        ]
    )
    assert "Data" in {d.name for d in lang_intel.domains}


def test_developer_aggregation_multiple_repositories():
    repos = [
        evidence("org/api", languages={"Python": 2000}, topics=["api"]),
        evidence("org/worker", languages={"Python": 2000}, topics=["backend"]),
    ]
    intel = INFERENCE.infer_developer_intelligence(repositories=repos)
    by_name = {d.name: d for d in intel.domains}
    backend = by_name["Backend"]
    assert backend.repository_count == 2
    repo_names = {r.name for r in backend.repositories}
    assert repo_names == {"api", "worker"}


def test_repositories_can_contribute_to_multiple_domains():
    repos = [
        evidence(
            "org/fullstack-app",
            languages={"Python": 2000, "TypeScript": 2000},
            topics=["react", "fastapi"],
            description="React frontend with FastAPI backend",
        )
    ]
    intel = INFERENCE.infer_developer_intelligence(repositories=repos)
    by_name = {d.name: d for d in intel.domains}
    assert "Backend" in by_name
    assert "Frontend" in by_name


def test_weak_evidence_does_not_create_strong_classification():
    repos = [
        evidence(
            "org/tiny",
            languages={},
            topics=["vue"],
            description=None,
            event_count=0,
        )
    ]
    intel = INFERENCE.infer_developer_intelligence(repositories=repos)
    by_name = {d.name: d for d in intel.domains}
    frontend = by_name["Frontend"]
    assert frontend.strength == "emerging"
    assert frontend.strength != "strong"


def test_evidence_is_traceable_to_repositories():
    repos = [
        evidence(
            "org/trace-app",
            languages={"Python": 4000},
            topics=["fastapi"],
            description="REST backend service",
        )
    ]
    intel = INFERENCE.infer_developer_intelligence(repositories=repos)
    backend = next(d for d in intel.domains if d.name == "Backend")
    repo = backend.repositories[0]
    assert repo.name == "trace-app"
    assert repo.full_name == "org/trace-app"
    types = {e.type for e in repo.evidence}
    assert "language" in types
    assert "topic" in types


def test_same_named_repositories_are_grouped_by_full_name():
    """Regression: evidence was grouped by short ``name``, so ``alice/api`` and
    ``bob/api`` collapsed into one repository and one owner's signals were
    silently overwritten by the other's."""
    repos = [
        evidence("alice/api", languages={"Python": 3000}, topics=["fastapi"]),
        evidence("bob/api", languages={"Go": 3000}, topics=["graphql"]),
    ]
    intel = INFERENCE.infer_developer_intelligence(repositories=repos)
    backend = next(d for d in intel.domains if d.name == "Backend")

    assert backend.repository_count == 2
    by_full_name = {r.full_name: r for r in backend.repositories}
    assert set(by_full_name) == {"alice/api", "bob/api"}
    # The short name is preserved for display on both entries.
    assert {r.name for r in backend.repositories} == {"api"}
    # Each repository keeps its own evidence rather than the other owner's.
    alice_values = {(e.type, e.value) for e in by_full_name["alice/api"].evidence}
    bob_values = {(e.type, e.value) for e in by_full_name["bob/api"].evidence}
    assert ("language", "Python") in alice_values
    assert ("topic", "fastapi") in alice_values
    assert ("language", "Go") in bob_values
    assert ("topic", "graphql") in bob_values
    assert ("language", "Go") not in alice_values
    assert ("language", "Python") not in bob_values
    # Serialized form carries the identity too.
    serialized = backend.to_dict()["repositories"]
    assert {r["full_name"] for r in serialized} == {"alice/api", "bob/api"}
