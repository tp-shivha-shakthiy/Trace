"""Tests for the deterministic domain inference baseline."""

from app.services.domains import (
    KeywordDomainInference,
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