import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  deleteFetchedProfile,
  formatDate,
  getMyProfile,
  getProfile,
  syncAndWait,
  waitForJob,
} from "../api";
import {
  DomainIntelligenceCard,
  DomainSignalCard,
  LanguagePills,
  MonthBars,
} from "../components";
import type { DeveloperProfile, RepositorySummary } from "../types";

type SyncState =
  | { phase: "idle" }
  | { phase: "syncing"; status: string }
  | { phase: "failed"; message: string };

export default function Developer({ self = false }: { self?: boolean }) {
  const { username = "" } = useParams();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<DeveloperProfile | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [connectRequired, setConnectRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sync, setSync] = useState<SyncState>({ phase: "idle" });
  const [deleting, setDeleting] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  const refresh = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    setConnectRequired(false);
    setSync({ phase: "idle" });
    try {
      setProfile(self ? await getMyProfile() : await getProfile(username));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        setProfile(null);
      } else if (err instanceof ApiError && err.status === 401 && self) {
        setConnectRequired(true);
        setProfile(null);
      }
    } finally {
      setLoading(false);
    }
  }, [self, username]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // When OAuth lands us here with ?job=<id>, the callback enqueued the sync
  // that populates this page; poll it so the initial sync is visible instead
  // of a profile that already looks synced.
  //
  // The job id is moved out of the URL into component state. Polling depends
  // only on that state, so stripping ``?job=`` from the URL (which changes
  // ``searchParams``) never cancels it. Each polling run owns an
  // AbortController that cleanup aborts, which both stops further requests
  // and discards stale updates; under StrictMode's mount -> cleanup -> mount
  // the first run is aborted before it can update state, leaving exactly one
  // effective poller.
  const [trackedJob, setTrackedJob] = useState<string | null>(() =>
    searchParams.get("job"),
  );
  const urlJob = searchParams.get("job");
  useEffect(() => {
    if (!urlJob) return;
    setTrackedJob(urlJob);
    const params = new URLSearchParams(searchParams);
    params.delete("job");
    setSearchParams(params, { replace: true });
  }, [urlJob, searchParams, setSearchParams]);

  // Latest refresh() without making it a polling dependency: a new refresh
  // identity (e.g. route change) must not restart an in-flight poll.
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!trackedJob) return;
    const controller = new AbortController();
    const { signal } = controller;
    setSync({ phase: "syncing", status: "queued" });
    (async () => {
      try {
        const job = await waitForJob(
          trackedJob,
          (status) => {
            if (!signal.aborted) setSync({ phase: "syncing", status });
          },
          signal,
        );
        if (signal.aborted) return;
        setTrackedJob(null);
        if (job.status === "failed") {
          setSync({
            phase: "failed",
            message: job.error_message || "Sync failed without an error message",
          });
        } else {
          setSync({ phase: "idle" });
          await refreshRef.current();
        }
      } catch (err) {
        if (signal.aborted) return;
        setTrackedJob(null);
        setSync({
          phase: "failed",
          message: err instanceof ApiError ? err.message : "Sync failed",
        });
      }
    })();
    return () => {
      controller.abort();
    };
  }, [trackedJob]);

  const syncUsername = profile?.username ?? username;

  const connectHref = self
    ? "/auth/github"
    : `/auth/github?next=/developers/${encodeURIComponent(syncUsername)}`;

  async function runSync() {
    setSync({ phase: "syncing", status: "queued" });
    try {
      const job = await syncAndWait(syncUsername, (status) =>
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
      if (err instanceof ApiError && err.status === 401) {
        setConnectRequired(true);
        return;
      }
      setSync({
        phase: "failed",
        message: err instanceof ApiError ? err.message : "Sync request failed",
      });
    }
  }

  async function removeFetchedProfile() {
    if (!profile || !window.confirm(`Delete your fetched data for @${profile.username}?`)) {
      return;
    }
    setDeleting(true);
    try {
      await deleteFetchedProfile(profile.username);
      navigate("/");
    } finally {
      setDeleting(false);
    }
  }

  if (loading) return <p className="muted">Loading {username}…</p>;

  return (
    <div className="developer">
      {notFound && (
        <section className="card">
          <h1>@{username || "developer"} is not synced yet</h1>
          <p>
            TRACE hasn't ingested this developer. Sync their public GitHub
            activity to build their domain profile.
          </p>
          <SyncButton state={sync} onSync={runSync} />
          {sync.phase === "failed" && (
            <p className="error">Sync failed: {sync.message}</p>
          )}
          <p className="muted">
            <Link to="/">← back to all developers</Link>
          </p>
        </section>
      )}

      {connectRequired && (
        <section className="card">
          <h1>Not connected</h1>
          <p>
            Sign in with GitHub to connect your account, then sync developers
            (your own profile includes private repositories).
          </p>
          <p>
            <a className="button" href={connectHref}>
              Connect GitHub
            </a>
          </p>
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
              {profile.is_owner && (
                <span className="pill owner-pill">your profile</span>
              )}
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
            {profile.is_fetched && (
              <button type="button" onClick={removeFetchedProfile} disabled={deleting}>
                {deleting ? "Deleting…" : "Delete fetched data"}
              </button>
            )}
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
              <b>
                {profile.intelligence
                  ? profile.intelligence.domains.length
                  : profile.summary.domain_signals.length}
              </b>{" "}
              domains inferred
            </span>
            <span>last activity {formatDate(profile.summary.last_activity_at)}</span>
          </section>

          <section className="signals">
            <h2>Developer intelligence</h2>
            {profile.intelligence && profile.intelligence.domains.length > 0 ? (
              <div className="signal-grid">
                {profile.intelligence.domains.map((domain) => (
                  <DomainIntelligenceCard
                    key={domain.name}
                    intelligence={domain}
                  />
                ))}
              </div>
            ) : profile.summary.domain_signals.length > 0 ? (
              <div className="signal-grid">
                {profile.summary.domain_signals.map((signal) => (
                  <DomainSignalCard key={signal.domain} signal={signal} />
                ))}
              </div>
            ) : (
              <p className="muted">
                No domain intelligence yet — TRACE has no language, topic, or
                keyword evidence for this developer.
              </p>
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
        {repo.is_private && <span className="pill private-pill">private</span>}
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