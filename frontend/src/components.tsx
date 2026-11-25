import type {
  Confidence,
  DomainIntelligence,
  DomainSignal,
  DomainStrength,
  EvidenceSignal,
  RepositoryEvidence,
} from "./types";

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`badge badge-${confidence}`}>{confidence}</span>;
}

export function StrengthBadge({ strength }: { strength: DomainStrength }) {
  return <span className={`badge badge-${strength}`}>{strength}</span>;
}

export function ScoreBar({ score }: { score: number }) {
  const percent = Math.round(Math.min(1, score) * 100);
  return (
    <div className="score">
      <div className="score-value">{percent}</div>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${percent}%` }} />
      </div>
      <div className="score-label">/100</div>
    </div>
  );
}

/**
 * Deduplicate evidence across repositories by ``(type, normalized value)``.
 *
 * Values are normalized (trimmed, case-folded) only to build the identity
 * key; the first-seen original spelling is kept for display. Signals of
 * different types are never merged, even when their values match (e.g. a
 * ``language: Python`` and a ``topic: python`` remain two pieces of evidence).
 */
export function uniqueEvidence(
  repositories: RepositoryEvidence[],
): EvidenceSignal[] {
  const seen = new Map<string, EvidenceSignal>();
  for (const repo of repositories) {
    for (const signal of repo.evidence) {
      const key = `${signal.type}\u0000${signal.value.trim().toLowerCase()}`;
      if (!seen.has(key)) seen.set(key, signal);
    }
  }
  return Array.from(seen.values());
}

/** Short repo names for display, falling back to ``owner/name`` whenever two
 * contributing repositories share the same short name. */
function repositoryLabels(repositories: RepositoryEvidence[]): string[] {
  const counts = new Map<string, number>();
  for (const repo of repositories) {
    counts.set(repo.name, (counts.get(repo.name) ?? 0) + 1);
  }
  return repositories.map((repo) =>
    (counts.get(repo.name) ?? 0) > 1 ? repo.full_name : repo.name,
  );
}

export function DomainIntelligenceCard({
  intelligence,
}: {
  intelligence: DomainIntelligence;
}) {
  const allSignals = uniqueEvidence(intelligence.repositories);

  return (
    <article className="card signal-card">
      <div className="signal-head">
        <h3 className="signal-domain">{intelligence.name}</h3>
        <StrengthBadge strength={intelligence.strength} />
      </div>
      <ScoreBar score={intelligence.score} />
      <p className="signal-repos">
        <b>
          {intelligence.repository_count === 1
            ? "1 repository"
            : `${intelligence.repository_count} repositories`}
        </b>
        {intelligence.repositories.length > 0 && (
          <span className="muted">
            {" "}({repositoryLabels(intelligence.repositories).join(", ")})
          </span>
        )}
      </p>
      {allSignals.length > 0 && (
        <div>
          <div className="sub" style={{ margin: "0.4rem 0 0.2rem" }}>
            Evidence:
          </div>
          <ul className="signal-evidence">
            {allSignals.map((signal) => (
              <li key={`${signal.type}:${signal.value}`}>
                <span className="muted">{signal.type}:</span> {signal.value}
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

export function DomainSignalCard({ signal }: { signal: DomainSignal }) {
  return (
    <article className="card signal-card">
      <div className="signal-head">
        <h3 className="signal-domain">{signal.domain}</h3>
        <ConfidenceBadge confidence={signal.confidence} />
      </div>
      <ScoreBar score={signal.score} />
      <p className="signal-repos">
        {signal.repository_count === 1
          ? "1 supporting repository"
          : `${signal.repository_count} supporting repositories`}
      </p>
      <ul className="signal-evidence">
        {signal.evidence.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </article>
  );
}

export function LanguagePills({ languages }: { languages: Record<string, number> }) {
  const items = Object.entries(languages).sort((a, b) => b[1] - a[1]);
  if (items.length === 0) return <p className="muted">No language data</p>;
  return (
    <ul className="pills">
      {items.map(([language, count]) => (
        <li key={language} className="pill">
          {language}
          <span className="pill-count">{count}</span>
        </li>
      ))}
    </ul>
  );
}

export function MonthBars({
  months,
}: {
  months: Array<{ month: string; events: number }>;
}) {
  const max = Math.max(1, ...months.map((m) => m.events));
  return (
    <div className="month-bars">
      {months.map((m) => (
        <div key={m.month} className="month-cell">
          <div
            className="month-bar"
            style={{ height: `${Math.round((m.events / max) * 100)}%` }}
            title={`${m.month}: ${m.events} events`}
          />
          <span className="month-label">{m.month.slice(2)}</span>
        </div>
      ))}
    </div>
  );
}