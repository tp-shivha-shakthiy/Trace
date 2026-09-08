import type { Confidence, DomainSignal } from "./types";

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`badge badge-${confidence}`}>{confidence}</span>;
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