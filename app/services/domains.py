"""Deterministic, transparent technical-domain inference for TRACE Intelligence V1.

This is the TRACE intelligence layer: it converts persisted GitHub
evidence into per-domain signals that answer "which domains does this
developer work in, how strong is the evidence, and why?".

Signals (only fields that TRACE actually persists across ``repositories`` and
``github_events`` are used):

* **language**    - the repository's language breakdown (byte share, or the
                    primary language when only one is known)
* **topics**      - repository GitHub topics
* **keywords**    - repository name and description keyword matches against
                    curated domain keyword sets
* **activity**    - event volume on a repository is used only to *amplify*
                    an existing signal and to report "sustained activity";
                    activity alone never creates a domain

Scoring & Deduplication:
* Language evidence: share of bytes * 1.0 (max 1.0 per repo).
* Topic evidence: 0.50 per matched topic.
* Name keyword: 0.25 per matched name keyword.
* Description keyword: 0.20 per matched description keyword.
* Deduplication: signal terms matching as topics are not double counted in name or
  description; keyword contribution per repo is capped at 0.80.
* Activity amplification: 0.20 * min(1.0, events / 50) for signaled domains.
* Max intensity per repo per domain: 1.50.

Aggregation & Minimum-Evidence Rule:
* Total developer domain score: min(1.0, round(raw / 3.0, 2)).
* Minimum-evidence rule: single weak keywords (e.g. repo name containing 'data' alone)
  are filtered out. A domain requires confirmed language evidence, explicit topic
  evidence, or multiple distinct keywords with raw intensity >= 0.40.
* Strength levels: emerging, moderate, strong (no unverified employment claims).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from re import IGNORECASE, compile
from typing import Protocol

# Canonical display names for supported domains
DOMAIN_DISPLAY_NAMES: dict[str, str] = {
    "backend": "Backend",
    "frontend": "Frontend",
    "devops": "DevOps",
    "data": "Data",
    "ml": "ML",
    "mobile": "Mobile",
    "security": "Security",
    "systems": "Systems",
    "gaming": "Gaming",
    "web": "Web",
    "testing": "Testing",
}

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
            "microservices", "authentication", "service", "fastapi",
            "django", "flask", "postgresql", "postgres",
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

# --- Scoring weights & limits (V1 deterministic evidence model) ---
_WEIGHT_LANGUAGE = 1.0           # max per-domain intensity from 100% byte share
_WEIGHT_TOPIC = 0.50             # per distinct matched topic
_WEIGHT_NAME_KEYWORD = 0.25      # per distinct repository name keyword match
_WEIGHT_DESCRIPTION_KEYWORD = 0.20  # per distinct description keyword match
_KEYWORD_CONTRIBUTION_CAP = 0.80 # max non-language intensity per repo per domain
_ACTIVITY_WORK = 0.20            # max per-domain intensity from event activity
_ACTIVITY_EVENT_SCALE = 50       # events needed for full activity contribution
_REPO_CONTRIBUTION_CAP = 1.50    # max intensity a single repo yields per domain
_SCORE_SCALE = 3.0               # raw intensity -> score (score = min(1, raw/3))
_CONFIDENCE_RAW_HIGH = 2.4       # raw threshold for legacy "high" confidence tier
_MIN_INTENSITY = 1e-9            # threshold below which intensity is ignored
_MAX_EVIDENCE_LINES = 4          # summary lines shown per domain in legacy format


# --- Data Structures ---

@dataclass(frozen=True)
class EvidenceSignal:
    """A single atomic piece of evidence derived from repository metadata."""

    type: str  # "language", "topic", "keyword"
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "value": self.value}


@dataclass(frozen=True)
class RepositoryEvidence:
    """The evidence collected from one repository for one domain.

    ``full_name`` (``owner/name``) is the repository identity; ``name`` is
    kept only for display, since different owners can share a repo name.
    """

    full_name: str
    name: str
    evidence: list[EvidenceSignal]

    def to_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "name": self.name,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass(frozen=True)
class DomainIntelligence:
    """Developer-level intelligence for a technical domain."""

    name: str  # e.g. "Backend"
    strength: str  # "strong", "moderate", "emerging"
    score: float
    repository_count: int
    repositories: list[RepositoryEvidence]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strength": self.strength,
            "score": self.score,
            "repository_count": self.repository_count,
            "repositories": [r.to_dict() for r in self.repositories],
        }


@dataclass(frozen=True)
class DeveloperIntelligence:
    """Aggregated technical intelligence for a developer."""

    domains: list[DomainIntelligence] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"domains": [d.to_dict() for d in self.domains]}


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
    """Per-domain inference outcome for a developer (backward-compatible view).

    ``score`` is an evidence score bounded in [0, 1]. ``confidence`` is one of
    ``high`` / ``medium`` / ``low``. ``evidence`` lists human-readable summary lines.
    """

    domain: str
    score: float
    confidence: str
    evidence: list[str]
    repository_count: int


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

    def infer_developer_intelligence(
        self,
        *,
        repositories: Iterable[RepositoryDomainEvidence] = (),
    ) -> DeveloperIntelligence: ...


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
    signals: dict[str, list[EvidenceSignal]]
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

    def infer_developer_intelligence(
        self,
        *,
        repositories: Iterable[RepositoryDomainEvidence] = (),
    ) -> DeveloperIntelligence:
        raw: dict[str, float] = {}
        # domain -> repository full_name (identity) -> evidence signals
        repos_by_domain: dict[str, dict[str, list[EvidenceSignal]]] = {}
        # repository full_name -> display name
        display_names: dict[str, str] = {}
        has_language_by_domain: dict[str, bool] = {}
        has_topic_by_domain: dict[str, bool] = {}
        keywords_by_domain: dict[str, set[str]] = {}

        for repo in repositories:
            classified = self._score_repository(repo)
            if not classified.domains:
                continue
            for domain, intensity in classified.domains.items():
                if intensity <= _MIN_INTENSITY:
                    continue
                raw[domain] = raw.get(domain, 0.0) + intensity
                signals = classified.signals.get(domain, [])
                if signals:
                    repos_by_domain.setdefault(domain, {})[repo.full_name] = signals
                    display_names[repo.full_name] = repo.name
                    for s in signals:
                        if s.type == "language":
                            has_language_by_domain[domain] = True
                        elif s.type == "topic":
                            has_topic_by_domain[domain] = True
                        elif s.type == "keyword":
                            keywords_by_domain.setdefault(domain, set()).add(s.value)

        domain_intelligences: list[DomainIntelligence] = []
        for domain, intensity in raw.items():
            if intensity <= _MIN_INTENSITY:
                continue
            has_lang = has_language_by_domain.get(domain, False)
            has_top = has_topic_by_domain.get(domain, False)
            kw_count = len(keywords_by_domain.get(domain, set()))

            # Enforce minimum-evidence rule
            if not self._passes_minimum_evidence(
                has_language=has_lang,
                has_topic=has_top,
                keyword_count=kw_count,
                raw_intensity=intensity,
            ):
                continue

            repo_dict = repos_by_domain.get(domain, {})
            repo_count = len(repo_dict)
            if repo_count == 0:
                continue

            score = min(1.0, round(intensity / _SCORE_SCALE, 2))
            strength = self._strength_for(score=score, repository_count=repo_count)
            display_name = DOMAIN_DISPLAY_NAMES.get(domain, domain.title())

            repo_evidences: list[RepositoryEvidence] = []
            for full_name in sorted(repo_dict.keys()):
                repo_signals = repo_dict[full_name]
                unique_signals = {
                    (s.type, s.value): s for s in repo_signals
                }.values()
                type_order = {"language": 0, "topic": 1, "keyword": 2}
                sorted_signals = sorted(
                    unique_signals,
                    key=lambda s: (type_order.get(s.type, 99), s.value),
                )
                repo_evidences.append(
                    RepositoryEvidence(
                        full_name=full_name,
                        name=display_names[full_name],
                        evidence=sorted_signals,
                    )
                )

            domain_intelligences.append(
                DomainIntelligence(
                    name=display_name,
                    strength=strength,
                    score=score,
                    repository_count=repo_count,
                    repositories=repo_evidences,
                )
            )

        domain_intelligences.sort(
            key=lambda d: (-d.score, -d.repository_count, d.name)
        )
        return DeveloperIntelligence(domains=domain_intelligences)

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
                raw[domain] = raw.get(domain, 0.0) + intensity
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
        domains: dict[str, float] = {}
        languages_by_domain: dict[str, list[str]] = {}
        keywords_by_domain: dict[str, list[str]] = {}
        signals_by_domain: dict[str, list[EvidenceSignal]] = {}

        # 1. Language evidence (byte-share weighted, deterministic)
        shares = _language_shares(repo)
        for language, share in shares.items():
            if share <= 0:
                continue
            for domain in _language_domains(language):
                if not domain:
                    continue
                lang_weight = share * _WEIGHT_LANGUAGE
                domains[domain] = domains.get(domain, 0.0) + lang_weight
                languages_by_domain.setdefault(domain, []).append(language)
                signals_by_domain.setdefault(domain, []).append(
                    EvidenceSignal(type="language", value=language)
                )

        # 2. Topic evidence & keyword deduplication
        # Track seen normalized terms per domain in this repository to prevent
        # double-counting
        seen_terms: dict[str, set[str]] = {}
        keyword_weights: dict[str, float] = {}

        # Check explicit topics first
        for topic in repo.topics:
            topic_norm = topic.strip().lower()
            if not topic_norm:
                continue
            for pattern, domain in self._patterns:
                if pattern.search(topic_norm):
                    matched = self._matched_keywords(domain, topic_norm)
                    for term in matched:
                        if term not in seen_terms.setdefault(domain, set()):
                            seen_terms[domain].add(term)
                            keyword_weights[domain] = (
                                keyword_weights.get(domain, 0.0) + _WEIGHT_TOPIC
                            )
                            signals_by_domain.setdefault(domain, []).append(
                                EvidenceSignal(type="topic", value=topic)
                            )
                            keywords_by_domain.setdefault(domain, []).append(term)

        # 3. Repository Name keywords
        repo_name_lower = repo.name.lower()
        for pattern, domain in self._patterns:
            if pattern.search(repo_name_lower):
                matched = self._matched_keywords(domain, repo_name_lower)
                for term in matched:
                    if term not in seen_terms.setdefault(domain, set()):
                        seen_terms[domain].add(term)
                        keyword_weights[domain] = (
                            keyword_weights.get(domain, 0.0) + _WEIGHT_NAME_KEYWORD
                        )
                        signals_by_domain.setdefault(domain, []).append(
                            EvidenceSignal(type="keyword", value=term)
                        )
                        keywords_by_domain.setdefault(domain, []).append(term)

        # 4. Description keywords
        if repo.description:
            desc_lower = repo.description.lower()
            for pattern, domain in self._patterns:
                if pattern.search(desc_lower):
                    matched = self._matched_keywords(domain, desc_lower)
                    for term in matched:
                        if term not in seen_terms.setdefault(domain, set()):
                            seen_terms[domain].add(term)
                            keyword_weights[domain] = (
                                keyword_weights.get(domain, 0.0)
                                + _WEIGHT_DESCRIPTION_KEYWORD
                            )
                            signals_by_domain.setdefault(domain, []).append(
                                EvidenceSignal(type="keyword", value=term)
                            )
                            keywords_by_domain.setdefault(domain, []).append(term)

        # Combine language and capped keyword evidence
        all_domains = set(domains.keys()) | set(keyword_weights.keys())
        final_domains: dict[str, float] = {}

        for domain in all_domains:
            lang_contrib = domains.get(domain, 0.0)
            kw_contrib = min(
                _KEYWORD_CONTRIBUTION_CAP, keyword_weights.get(domain, 0.0)
            )
            base_intensity = lang_contrib + kw_contrib

            # Activity only amplifies existing evidence
            if base_intensity > 0 and repo.event_count > 0:
                activity = _ACTIVITY_WORK * min(
                    1.0, repo.event_count / _ACTIVITY_EVENT_SCALE
                )
                total = min(_REPO_CONTRIBUTION_CAP, base_intensity + activity)
            else:
                total = min(_REPO_CONTRIBUTION_CAP, base_intensity)

            final_domains[domain] = total

        return _RepoDomainEvidence(
            domains=final_domains,
            languages=languages_by_domain,
            keywords=keywords_by_domain,
            signals=signals_by_domain,
            has_activity=repo.event_count > 0,
        )

    def _passes_minimum_evidence(
        self,
        *,
        has_language: bool,
        has_topic: bool,
        keyword_count: int,
        raw_intensity: float,
    ) -> bool:
        """Enforce the minimum-evidence rule for TRACE Intelligence V1.

        A domain is only considered meaningful if it has:
        1. Confirmed language evidence in the domain, OR
        2. Explicit repository topic tag evidence in the domain, OR
        3. Multiple distinct keyword matches (>= 2) AND sufficient aggregate
           intensity (>= 0.40).

        A single weak keyword (e.g. repo name containing 'data' alone) yields
        raw intensity < 0.40 and keyword_count < 2, so it is filtered out.
        """
        if has_language or has_topic:
            return True
        if keyword_count >= 2 and raw_intensity >= 0.40:
            return True
        return False

    def _strength_for(self, *, score: float, repository_count: int) -> str:
        """Map evidence score to human-readable strength levels.

        Returns 'strong', 'moderate', or 'emerging'.
        """
        if score >= 0.70 and (repository_count >= 2 or score >= 0.85):
            return "strong"
        if score >= 0.40:
            return "moderate"
        return "emerging"

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


class IntelligenceService:
    """Service orchestrating TRACE Intelligence V1."""

    def __init__(self, inference: DomainInference | None = None) -> None:
        self._inference = inference or KeywordDomainInference()

    def build_developer_intelligence(
        self, repositories: Iterable[RepositoryDomainEvidence]
    ) -> DeveloperIntelligence:
        return self._inference.infer_developer_intelligence(repositories=repositories)


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