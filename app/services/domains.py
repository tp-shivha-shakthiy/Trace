"""Deterministic, keyword-based technical domain inference.

This is the v0.3 *baseline* for developer domain inference. It classifies a
repository into coarse technical domains using:

* the repository's primary language / language breakdown
* GitHub topics
* keywords in the repository name and description

It is intentionally simple and fully deterministic. The ``DomainInference``
protocol is the extension point where a future ML-based classifier can plug
in without changing the ingestion pipeline. It is NOT a learned model.
"""

from __future__ import annotations

from dataclasses import dataclass
from re import IGNORECASE, compile
from typing import Protocol

# language -> coarse domains. Keys match GitHub's canonical language names.
LANGUAGE_DOMAINS: dict[str, set[str]] = {
    "Python": {"backend", "data"},
    "Go": {"backend", "devops"},
    "Rust": {"backend", "systems"},
    "Java": {"backend"},
    "Kotlin": {"mobile", "backend"},
    "Swift": {"mobile"},
    "Objective-C": {"mobile"},
    "C": {"systems", "backend"},
    "C++": {"systems", "gaming", "backend"},
    "C#": {"backend", "gaming", "mobile"},
    "JavaScript": {"frontend"},
    "TypeScript": {"frontend", "backend"},
    "HTML": {"frontend"},
    "CSS": {"frontend"},
    "Vue": {"frontend"},
    "Svelte": {"frontend"},
    "PHP": {"backend", "web"},
    "Ruby": {"backend", "web"},
    "Scala": {"backend", "data"},
    "R": {"data", "ml"},
    "Julia": {"data", "ml"},
    "Shell": {"devops"},
    "Dockerfile": {"devops"},
    "Makefile": {"devops"},
    "SQL": {"data", "backend"},
    "PLpgSQL": {"data", "backend"},
    "Jupyter Notebook": {"data", "ml"},
    "Lua": {"gaming"},
}

# keyword -> domain, matched against topics / name / description
DOMAIN_KEYWORDS: list[tuple[set[str], str]] = [
    (
        {
            "machine-learning", "deep-learning", "pytorch", "tensorflow",
            "keras", "llm", "nlp", "computer-vision", "generative-ai",
            "mlops",
        },
        "ml",
    ),
    (
        {
            "data", "etl", "pipeline", "analytics", "pandas", "spark",
            "database", "databases", "sql", "warehouse", "streaming",
        },
        "data",
    ),
    (
        {
            "docker", "kubernetes", "k8s", "terraform", "ci", "cd",
            "devops", "infrastructure", "aws", "gcp", "azure", "helm",
            "deployment", "cloud",
        },
        "devops",
    ),
    (
        {
            "frontend", "react", "vue", "svelte", "ui", "ux", "css",
            "tailwind", "design-system", "webapp", "dashboard",
        },
        "frontend",
    ),
    (
        {
            "backend", "api", "server", "rest", "graphql", "microservice",
            "microservices", "authentication", "service",
        },
        "backend",
    ),
    (
        {
            "security", "cryptography", "crypto", "auth", "oauth",
            "encryption", "vulnerability", "pentest",
        },
        "security",
    ),
    (
        {"mobile", "android", "ios", "flutter", "react-native"},
        "mobile",
    ),
    (
        {"game", "gaming", "unity", "unreal", "godot", "gameplay"},
        "gaming",
    ),
    (
        {"web", "website", "ssg", "blog", "portfolio"},
        "web",
    ),
    (
        {"testing", "qa", "quality", "pytest", "cypress", "unit-test"},
        "testing",
    ),
    (
        {
            "compiler", "kernel", "embedded", "systems", "network",
            "operating-system", "language",
        },
        "systems",
    ),
]

MAX_DOMAINS_PER_REPOSITORY = 3


class DomainInference(Protocol):
    """Extension point for repository -> domain classification."""

    def infer_repository_domains(
        self,
        *,
        languages: list[str],
        topics: list[str],
        name: str,
        description: str | None,
    ) -> list[str]: ...


def _language_domains(language: str) -> set[str]:
    exact = LANGUAGE_DOMAINS.get(language)
    if exact is not None:
        return exact
    folded = language.casefold()
    for key, domains in LANGUAGE_DOMAINS.items():
        if key.casefold() == folded:
            return domains
    if language.capitalize() in LANGUAGE_DOMAINS:
        return LANGUAGE_DOMAINS[language.capitalize()]
    return set()


class KeywordDomainInference:
    """Deterministic keyword/language baseline (see module docstring)."""

    def __init__(self) -> None:
        self._patterns = [
            (compile(rf"\b(?:{'|'.join(keys)})\b", IGNORECASE), domain)
            for keys, domain in DOMAIN_KEYWORDS
        ]

    def infer_repository_domains(
        self,
        *,
        languages: list[str],
        topics: list[str],
        name: str,
        description: str | None,
    ) -> list[str]:
        scores: dict[str, int] = {}
        for language in languages:
            if not language:
                continue
            for domain in _language_domains(language):
                scores[domain] = scores.get(domain, 0) + 1

        haystack = " ".join([name, description or "", *topics]).lower()
        for pattern, domain in self._patterns:
            if pattern.search(haystack):
                scores[domain] = scores.get(domain, 0) + 2

        ranked = sorted(scores, key=lambda d: (-scores[d], d))
        return ranked[:MAX_DOMAINS_PER_REPOSITORY]


@dataclass(frozen=True)
class DomainAggregate:
    """Aggregated domain evidence across a developer's repositories."""

    repository_count: int
    repository_names: list[str]


def aggregate_repository_domains(
    repo_domains: list[tuple[str, list[str]]],
) -> dict[str, DomainAggregate]:
    """Aggregate per-repository domain lists into a developer-level profile.

    ``repo_domains`` is a list of ``(repo_full_name, domain_list)`` pairs.
    """
    aggregated: dict[str, list[str]] = {}
    for full_name, domains in repo_domains:
        for domain in domains:
            aggregated.setdefault(domain, []).append(full_name)
    return {
        domain: DomainAggregate(
            repository_count=len(names), repository_names=names
        )
        for domain, names in sorted(
            aggregated.items(), key=lambda kv: (-len(kv[1]), kv[0])
        )
    }