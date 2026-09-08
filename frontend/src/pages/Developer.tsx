import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  formatDate,
  getProfile,
  syncAndWait,
} from "../api";
import {
  DomainSignalCard,
  LanguagePills,
  MonthBars,
} from "../components";
import type { DeveloperProfile, RepositorySummary } from "../types";

type SyncState =
  | { phase: "idle" }
  | { phase: "syncing"; status: string }
  | { phase: "failed"; message: string };

export default function Developer() {
  const { username = "" } = useParams();
  const [profile, setProfile] = useState<DeveloperProfile | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sync, setSync] = useState<SyncState>({ phase: "idle" });

  const refresh = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    setSync({ phase: "idle" });
    try {
      setProfile(await getProfile(username));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        setProfile(null);
      }
    } finally {
      setLoading(false);
    }
  }, [username]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function runSync() {
    setSync({ phase: "syncing", status: "queued" });
    try {
      const job = await syncAndWait(username, (status) =>
        setSync({ phase: "syncing", status }),
      );
      if (job.status === "failed") {
        setSync({
          phase: "failed",
          message: job.error_message || "Sync failed without an error message",
        });
      } else {
        setSync({ phase: "idle" });
        await refresh();
      }
    } catch (err) {
      setSync({
        phase: "failed",
        message: err instanceof ApiError ? err.message : "Sync request failed",
      });
    }
  }

  if (loading) return <p className="muted">Loading {username}…</p>;

  return (
    <div className="developer">
      {notFound && (
        <section className="card">
          <h1>@{username} is not synced yet</h1>
          <p>
            TRACE hasn't ingested this developer. Sync their public GitHub
            activity to build their domain profile.
          </p>
          <SyncButton state={sync} onSync={runSync} />
          <p className="muted">
            <Link to="/">← back to all developers</Link>
          </p>
        </section>
      )}

      {profile && (
        <>
          <section className="profile-head">
            {profile.avatar_url ? (
              <img src={profile.avatar_url} alt="" className="avatar avatar-lg" />
            ) : null}
            <div className="profile-id">
              <h1>{profile.name || profile.username}</h1>
              <a
                className="gh-link"
                href={profile.html_url ?? undefined}
                target="_blank"
                rel="noreferrer"
              >
                @{profile.username}
              </a>
              {profile.bio && <p className="bio">{profile.bio}</p>}
              <p className="meta">
                {[profile.company, profile.location]
                  .filter(Boolean)
                  .join(" · ") || "\u00a0"}
              </p>
            </div>
            <div className="profile-stats">
              <span>
                <b>{profile.public_repos}</b> repos
              </span>
              <span>
                <b>{profile.followers}</b> followers
              </span>
              <span>
                <b>{profile.following}</b> following
              </span>
            </div>
            <SyncButton state={sync} onSync={runSync} />
          </section>

          {sync.phase === "failed" && (
            <p className="error">Sync failed: {sync.message}</p>
          )}

          <section className="summary-strip">
            <span>
              <b>{profile.summary.total_repositories}</b> repositories
            </span>
            <span>
              <b>{profile.summary.total_events}</b> events
            </span>
            <span>
              <b>{profile.summary.domain_signals.length}</b> domains inferred
            </span>
            <span>last activity {formatDate(profile.summary.last_activity_at)}</span>
          </section>

          <section className="signals">
            <h2>Domain signals</h2>
            {profile.summary.domain_signals.length === 0 ? (
              <p className="muted">
                No domain signals yet — TRACE has no language, topic, or
                keyword evidence for this developer.
              </p>
            ) : (
              <div className="signal-grid">
                {profile.summary.domain_signals.map((signal) => (
                  <DomainSignalCard key={signal.domain} signal={signal} />
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <h2>Languages</h2>
            <LanguagePills languages={profile.summary.languages} />
          </section>

          <section className="two-col">
            <div className="card">
              <h2>Activity (12 months)</h2>
              <MonthBars months={profile.summary.events_per_month} />
              <h3 className="sub">By event type</h3>
              <KvList kv={profile.summary.activity} />
            </div>
            <div className="card">
              <h2>Activity by domain</h2>
              <KvList kv={profile.summary.events_by_domain} />
              <h3 className="sub">Repository domains</h3>
              <ul className="pill-list">
                {Object.entries(profile.summary.domains).map(
                  ([domain, agg]) => (
                    <li key={domain} className="pill">
                      {domain}
                      <span className="pill-count">{agg.repository_count}</span>
                    </li>
                  ),
                )}
              </ul>
            </div>
          </section>

          <section className="card">
            <h2>Repositories</h2>
            {profile.repositories.length === 0 ? (
              <p className="muted">No repositories ingested.</p>
            ) : (
              <table className="repo-table">
                <thead>
                  <tr>
                    <th>Repository</th>
                    <th>Language</th>
                    <th>Domains</th>
                    <th>Events</th>
                    <th>Stars</th>
                    <th>Pushed</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.repositories.map((repo) => (
                    <RepoRow key={repo.full_name} repo={repo} />
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <h2>Recent activity</h2>
            {profile.recent_activity.length === 0 ? (
              <p className="muted">No events recorded.</p>
            ) : (
              <ul className="event-list">
                {profile.recent_activity.map((event, i) => (
                  <li key={`${event.occurred_at}-${i}`}>
                    <span className="event-type">{event.event_type}</span>
                    <span className="event-target">
                      {event.repository ?? event.resource_id ?? "—"}
                    </span>
                    <span className="muted">
                      {new Date(event.occurred_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function RepoRow({ repo }: { repo: RepositorySummary }) {
  return (
    <tr>
      <td>
        <a href={repo.html_url ?? undefined} target="_blank" rel="noreferrer">
          {repo.full_name}
        </a>
        {repo.description && (
          <span className="repo-desc">{repo.description}</span>
        )}
      </td>
      <td>{repo.language || "–"}</td>
      <td>
        {repo.domains.length > 0 ? repo.domains.join(", ") : "–"}
      </td>
      <td>{repo.event_count}</td>
      <td>{repo.stargazers_count}</td>
      <td>{formatDate(repo.pushed_at)}</td>
    </tr>
  );
}

function SyncButton({
  state,
  onSync,
}: {
  state: SyncState;
  onSync: () => void;
}) {
  if (state.phase === "syncing") {
    return (
      <span className="sync-status">
        Syncing from GitHub… <span className="pill">{state.status}</span>
      </span>
    );
  }
  return (
    <button className="sync" onClick={onSync} disabled={state.phase !== "idle"}>
      Sync from GitHub
    </button>
  );
}

function KvList({ kv }: { kv: Record<string, number> }) {
  const entries = Object.entries(kv).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <p className="muted">None recorded</p>;
  return (
    <ul className="kv-list">
      {entries.map(([key, value]) => (
        <li key={key}>
          <span>{key}</span>
          <span className="pill-count">{value}</span>
        </li>
      ))}
    </ul>
  );
}