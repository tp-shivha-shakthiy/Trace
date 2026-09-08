"""Deterministic, transparent technical-domain inference for TRACE v0.4.

This is the first TRACE *intelligence layer*: it converts persisted GitHub
evidence into per-domain signals that answer "which domains does this
developer work in, how strong is the evidence, and why?".

Signals (only fields that TRACE actually persists across ``repositories`` and
``github_events`` are used):

* **language**      - the repository's language breakdown (byte share, or the
                      primary language when only one is known)
* **keywords**      - topics / name / description matches against curated
                      domain keyword sets
* **activity**      - event volume on a repository is used only to *amplify*
                      an existing signal and to report "sustained activity";
                      activity alone never creates a domain

Evidence we do *not* have yet (so we do not use them): dependency/package
manifests, README content, commit diffs, starred/contributed-third-party
repos. See README "Current limitations".

Scoring (per repository, per domain an intensity in [0, 2.0]):

    intensity = language_evidence + keyword_evidence + activity_evidence
    language_evidence : share of bytes * 1.0   (max 1.0 per repo)
    keyword_evidence  : 0.5 per matched keyword-group (one group per domain
                        per repo, so this is at most 0.5 per repo)
    activity_evidence : 0.3 * min(1, events / 50)   (only for signaled domains)

Across a developer the *raw* intensity is summed per domain and normalized:

    score = min(1.0, raw / 3.0)

``SCORE_SCALE = 3.0`` is roughly the combined evidence of one-to-two clearly
relevant repositories, so a score of 1.0 is the bounded ceiling. A score is an
**evidence score / estimated relevance** — it is *not* a proficiency or skill
measurement.

Confidence (high / medium / low) is policy-driven and deliberately decoupled
from score magnitude so a strong-looking score from one weak signal can never
produce high confidence:

* ``high``   - two or more supporting repositories, both language and keyword
               evidence present, sustained activity, raw >= 2.4
* ``medium`` - either language *and* keyword evidence (one sufficiently
               described repo) or evidence across two or more repository rows
* ``low``    - anything else (e.g. a lone keyword, or a lonely language-only
               repository)

Every result carries explicit, string-valued ``evidence`` reasons that are
derived directly from the persisted data.

The ``DomainInference`` protocol remains the abstraction boundary: the
ingestion pipeline calls ``infer_repository_domains`` and the profile layer
calls ``infer_developer_domains``, so a future ML classifier can replace
``KeywordDomainInference`` without touching either caller.
"""

from __future__ import annotations

from collections.abc import Iterable
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

# --- Developer-level scoring constants (see module docstring) ---------------
_LANGUAGE_WORK = 1.0           # max per-domain intensity from language share
_KEYWORD_WORK = 0.5            # per matched keyword-group weight
_ACTIVITY_WORK = 0.3           # max per-domain intensity from event activity
_ACTIVITY_EVENT_SCALE = 50     # events needed for full activity contribution
_REPO_CONTRIBUTION_CAP = 2.0   # max intensity a single repo yields per domain
_SCORE_SCALE = 3.0             # raw intensity -> score (score = min(1, raw/3))
_CONFIDENCE_RAW_HIGH = 2.4     # raw threshold for the "high" tier
_MIN_INTENSITY = 1e-9          # anything below is treated as no evidence
_MAX_EVIDENCE_LINES = 4        # evidence reasons shown per domain


class DomainInference(Protocol):
    """Extension point for repository/developer -> domain classification."""

    def infer_repository_domains(
        self,
        *,
        languages: list[str],
        topics: list[str],
        name: str,
        description: str | None,
    ) -> list[str]: ...

    def infer_developer_domains(
        self,
        *,
        repositories: Iterable[RepositoryDomainEvidence] = (),
    ) -> list[DeveloperDomainResult]: ...


@dataclass(frozen=True)
class RepositoryDomainEvidence:
    """The persisted evidence TRACE uses to classify one repository."""

    full_name: str
    name: str
    description: str | None
    primary_language: str | None
    languages: dict[str, int]
    topics: list[str]
    event_count: int


@dataclass(frozen=True)
class DeveloperDomainResult:
    """Per-domain inference outcome for a developer.

    ``score`` is an **evidence score** (estimated relevance), bounded in
    [0, 1], never a proficiency claim. ``confidence`` is one of
    ``high`` / ``medium`` / ``low`` and reflects how *independent* and
    *broad* the evidence is. ``evidence`` lists the explicit reasons.
    """

    domain: str
    score: float
    confidence: str
    evidence: list[str]
    repository_count: int


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


@dataclass
class _RepoDomainEvidence:
    """Internal per-repository classification used by the inference."""

    domains: dict[str, float]
    languages: dict[str, list[str]]
    keywords: dict[str, list[str]]
    has_activity: bool


class KeywordDomainInference:
    """Deterministic, transparent domain inference (see module docstring)."""

    def __init__(self) -> None:
        self._patterns = [
            (compile(rf"\b(?:{'|'.join(keys)})\b", IGNORECASE), domain)
            for keys, domain in DOMAIN_KEYWORDS
        ]
        # Sorted per-domain keyword lists for extracting *which* keyword
        # matched (keeps evidence strings deterministic).
        self._keyword_words: dict[str, list[str]] = {
            domain: sorted(keys) for keys, domain in DOMAIN_KEYWORDS
        }

    def infer_repository_domains(
        self,
        *,
        languages: list[str],
        topics: list[str],
        name: str,
        description: str | None,
    ) -> list[str]:
        known = [lang for lang in languages if lang]
        evidence = RepositoryDomainEvidence(
            full_name=name or "unknown",
            name=name or "",
            description=description,
            primary_language=known[0] if known else None,
            languages=(
                {lang: 1 for lang in known} if known else {}
            ),
            topics=topics,
            event_count=0,
        )
        classified = self._score_repository(evidence)
        ranked = sorted(
            classified.domains, key=lambda d: (-classified.domains[d], d)
        )
        return ranked[:MAX_DOMAINS_PER_REPOSITORY]

    def infer_developer_domains(
        self,
        *,
        repositories: Iterable[RepositoryDomainEvidence] = (),
    ) -> list[DeveloperDomainResult]:
        raw: dict[str, float] = {}
        repos_by_domain: dict[str, set[str]] = {}
        languages_by_domain: dict[str, set[str]] = {}
        keywords_by_domain: dict[str, set[str]] = {}
        activity_by_domain: set[str] = set()
        events_by_domain: dict[str, int] = {}

        for repo in repositories:
            classified = self._score_repository(repo)
            if not classified.domains:
                continue
            for domain, intensity in classified.domains.items():
                raw[domain] = raw.get(domain, 0) + intensity
                repos_by_domain.setdefault(domain, set()).add(repo.full_name)
                languages_by_domain.setdefault(domain, set()).update(
                    classified.languages.get(domain, [])
                )
                keywords_by_domain.setdefault(domain, set()).update(
                    classified.keywords.get(domain, [])
                )
                if classified.has_activity:
                    activity_by_domain.add(domain)
                    events_by_domain[domain] = (
                        events_by_domain.get(domain, 0) + repo.event_count
                    )

        results: list[DeveloperDomainResult] = []
        for domain, intensity in raw.items():
            if intensity <= _MIN_INTENSITY:
                continue
            repos = sorted(repos_by_domain[domain])
            score = min(1.0, intensity / _SCORE_SCALE)
            confidence = self._confidence_for(
                raw=intensity,
                repository_count=len(repos),
                has_language=bool(languages_by_domain.get(domain)),
                has_keyword=bool(keywords_by_domain.get(domain)),
                has_activity=domain in activity_by_domain,
            )
            results.append(
                DeveloperDomainResult(
                    domain=domain,
                    score=round(score, 3),
                    confidence=confidence,
                    evidence=self._evidence_for(
                        domain,
                        languages=languages_by_domain.get(domain, set()),
                        keywords=keywords_by_domain.get(domain, set()),
                        repos=repos,
                        events=events_by_domain.get(domain, 0),
                        has_activity=domain in activity_by_domain,
                    ),
                    repository_count=len(repos),
                )
            )

        results.sort(key=lambda r: (-r.score, -r.repository_count, r.domain))
        return results

    # -- internals -----------------------------------------------------------

    def _score_repository(
        self, repo: RepositoryDomainEvidence
    ) -> _RepoDomainEvidence:
        result = _RepoDomainEvidence({}, {}, {}, repo.event_count > 0)

        # language evidence (byte-share weighted, deterministic)
        shares = _language_shares(repo)
        for language, share in shares.items():
            for domain in _language_domains(language):
                if not domain:
                    continue
                result.domains[domain] = (
                    result.domains.get(domain, 0) + share * _LANGUAGE_WORK
                )
                result.languages.setdefault(domain, []).append(language)

        # keyword evidence (topics / name / description)
        haystack = " ".join(
            [repo.name, repo.description or "", *repo.topics]
        ).lower()
        for pattern, domain in self._patterns:
            if not pattern.search(haystack):
                continue
            matched = self._matched_keywords(domain, haystack)
            # Every domain group can match at most once per repository, so
            # this stays at exactly _KEYWORD_WORK and never reaches the cap.
            result.keywords.setdefault(domain, []).extend(matched)
            result.domains[domain] = (
                result.domains.get(domain, 0) + _KEYWORD_WORK
            )

        # activity evidence only amplifies existing signals.
        if result.domains and repo.event_count > 0:
            activity = _ACTIVITY_WORK * min(
                1.0, repo.event_count / _ACTIVITY_EVENT_SCALE
            )
            for domain in result.domains:
                amplified = result.domains[domain] + activity
                result.domains[domain] = min(
                    _REPO_CONTRIBUTION_CAP, amplified
                )
        return result

    def _matched_keywords(self, domain: str, haystack: str) -> list[str]:
        words = []
        for keyword in self._keyword_words[domain]:
            if compile(rf"\b{keyword}\b", IGNORECASE).search(haystack):
                words.append(keyword)
        return words

    def _confidence_for(
        self,
        *,
        raw: float,
        repository_count: int,
        has_language: bool,
        has_keyword: bool,
        has_activity: bool,
    ) -> str:
        if (
            repository_count >= 2
            and has_language
            and has_keyword
            and has_activity
            and raw >= _CONFIDENCE_RAW_HIGH
        ):
            return "high"
        if (has_language and has_keyword) or repository_count >= 2:
            return "medium"
        return "low"

    def _evidence_for(
        self,
        domain: str,
        *,
        languages: set[str],
        keywords: set[str],
        repos: list[str],
        events: int,
        has_activity: bool,
    ) -> list[str]:
        lines: list[str] = []
        repo_sample = ", ".join(repos[:_MAX_EVIDENCE_LINES])
        if languages:
            lines.append(
                f"{domain} signaled by language evidence "
                f"({', '.join(sorted(languages)[:4])}) in {repo_sample}"
            )
        if keywords:
            lines.append(
                f"{domain} keywords detected "
                f"({', '.join(sorted(keywords)[:4])}) in {repo_sample}"
            )
        if has_activity and events > 0:
            unit = "event" if events == 1 else "events"
            lines.append(
                f"sustained activity: {events} {unit} across "
                f"{len(repos)} {domain}-related repositories"
            )
        return lines[:_MAX_EVIDENCE_LINES]


def _language_shares(repo: RepositoryDomainEvidence) -> dict[str, float]:
    """Map known languages to their byte share of the repository (0..1).

    Falls back to the primary language (full share) when only one language is
    known. Always sorted by (-share, name) so the result is deterministic.
    """
    shares: dict[str, float] = {}
    if repo.languages:
        total = sum(repo.languages.values())
        if total > 0:
            for lang in sorted(
                repo.languages, key=lambda lng: (-repo.languages[lng], lng)
            ):
                count = repo.languages[lang]
                if count > 0:
                    shares[lang] = count / total
    elif repo.primary_language:
        shares[repo.primary_language] = 1.0
    return shares


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