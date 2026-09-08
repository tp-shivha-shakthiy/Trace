import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listDevelopers } from "../api";
import type { DeveloperListItem } from "../types";

export default function Home() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [developers, setDevelopers] = useState<DeveloperListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listDevelopers()
      .then(setDevelopers)
      .catch(() => setDevelopers([]))
      .finally(() => setLoading(false));
  }, []);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const name = username.trim();
    if (name) navigate(`/developers/${encodeURIComponent(name)}`);
  }

  return (
    <div className="home">
      <section className="hero">
        <h1>Developer domain intelligence</h1>
        <p className="lede">
          TRACE ingests GitHub activity, normalizes it into events, and
          produces an explainable <em>domain profile</em> — domains, evidence
          scores, and the reasons behind them.
        </p>
        <form className="search" onSubmit={submit}>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="GitHub username, e.g. octocat"
            aria-label="GitHub username"
          />
          <button type="submit">Trace</button>
        </form>
        <p className="muted">
          New username? Enter it above — TRACE will sync it from GitHub.
        </p>
      </section>

      <section className="card">
        <h2>Synced developers</h2>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : developers.length === 0 ? (
          <p className="muted">
            No developers synced yet. Search for one above.
          </p>
        ) : (
          <ul className="dev-list">
            {developers.map((dev) => (
              <li key={dev.username}>
                <Link to={`/developers/${dev.username}`} className="dev-row">
                  {dev.avatar_url ? (
                    <img
                      src={dev.avatar_url}
                      alt=""
                      className="avatar"
                      width={40}
                      height={40}
                    />
                  ) : (
                    <span className="avatar avatar-placeholder">
                      {dev.username.slice(0, 1).toUpperCase()}
                    </span>
                  )}
                  <span className="dev-name">
                    {dev.name || dev.username}
                    <small>@{dev.username}</small>
                  </span>
                  <span className="dev-stats">
                    {dev.total_events} events · {dev.public_repos} repos
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}