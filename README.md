# TRACE

A developer intelligence platform. TRACE ingests raw developer activity from
GitHub, normalizes it into deterministic events, persists it asynchronously
into PostgreSQL, and serves an aggregated developer profile — including a
coarse technical-domain profile — through a FastAPI backend.

**TRACE is at v0.3.** This milestone delivers a real, runnable, end-to-end
application:

```
GitHub API → activity ingestion → asynchronous processing → PostgreSQL → developer profile API → React SPA
```

It includes a React single-page frontend, GitHub OAuth sign-in with
server-side sessions, and explainable deterministic domain inference
(TRACE Intelligence V1).

It does **not** yet implement the full product vision (temporal knowledge
graph, ML skill/domain classifier, recommendations and webhooks are future
work). See [Limitations & future work](#current-limitations--future-work).

---

## What TRACE does

1. You trigger ingestion for a GitHub username.
2. A background worker fetches the user's repositories, language breakdowns,
   and recent activity events from the GitHub REST API.
3. The data is normalized into a provider-agnostic internal format.
4. It is persisted **idempotently** into PostgreSQL — re-running ingestion for
   the same developer never creates duplicate rows.
5. Repositories are classified into coarse technical domains using a
   deterministic baseline (language + topics + name/description keywords).
6. A developer profile endpoint answers queries like *"what does TRACE know
   about this developer?"* by reading the persisted data.

## Architecture

The backend follows a layered, dependency-consistent structure:

```
                 ┌──────────────────────────────┐
   POST /api/v1/sync ──► create SyncJob row      │
                 │              │                │
                 │              └─► enqueue job id│
                 └──────────────────────────────┘
                                   │ asyncio.Queue
                                   ▼
              ┌──────────────────────────────────────┐
              │  background worker (in-process)       │
              │  GitHubClient ──► GitHubActivitySvc   │
              │        │            │                 │
              │        ▼            ▼                 │
              │   normalizers (user/repo/event)       │
              │        │                              │
              │        ▼                              │
              │   IngestionService (idempotent upsert)│
              │        │                              │
              │        ▼                              │
              │   PostgreSQL (PostgreSQL: source of   │
              │   truth)  sync_jobs, developers,      │
              │   repositories, github_events         │
              └──────────────────────────────────────┘
                                   │
                                   ▼
              GET /api/v1/developers/{username}  ──► ProfileService
```

Layers:

- **API / Application** — FastAPI routers in `app/api/`, Pydantic schemas in
  `app/schemas.py`, dependencies in `app/deps.py`.
- **Service layer** — business logic in `app/services/` (`github_activity`,
  `ingestion`, `jobs`, `profiles`, `domains`).
- **Ingestion** — `app/github.py` (GitHub REST client), `app/normalizers.py`,
  `app/services/ingestion.py`.
- **Background processing** — `app/services/jobs.py`. An in-process
  `asyncio` task pool on a bounded `asyncio.Queue`. **No Celery / Redis** in
  v0.3 — this keeps the system trivially runnable locally while still enabling
  true async ingestion.
- **Persistence** — SQLAlchemy 2.0 (async) + psycopg3 over PostgreSQL.

### Router → Service → Repository style

Routers validate input and serialize responses; services hold business logic;
database access is isolated in the service layer using SQLAlchemy sessions. A
dedicated repository layer is intentionally small in v0.3 rather than adding
conceptual overhead.

## Technology stack

| Concern          | Technology                                    |
|------------------|-----------------------------------------------|
| Language         | Python 3.13                                    |
| API framework    | FastAPI, Pydantic v2                           |
| Database         | PostgreSQL 16, SQLAlchemy 2 (async), psycopg3  |
| Async processing | Python `asyncio` in-process task pool          |
| HTTP client      | httpx (with MockTransport for tests)           |
| Tests            | pytest, pytest-asyncio                         |
| Linting          | ruff                                           |
| Frontend         | React 19, Vite 8, TypeScript 7                 |
| Infrastructure   | Docker Compose (optional local dev)            |

## Frontend (TRACE SPA)

The repository includes a single-page application built with **React 19 + Vite
8 + TypeScript** in `frontend/`. It is served by the FastAPI backend at `/`
when `frontend/dist` exists (the default on Render and in the Docker image).
The SPA uses **hash-based routing** (React Router `HashRouter`), so no server-
side fallback is required.

### Running the frontend locally

```bash
cd frontend
npm ci
npm run dev          # Vite dev server on http://localhost:5173
```

The Vite dev server proxies `/api`, `/auth`, and `/health` to the local
FastAPI backend (default `http://localhost:8000`). To test the full integration,
start the backend in another terminal:

```bash
# Terminal 1
python serve.py
# Terminal 2
cd frontend && npm run dev
```

Then open `http://localhost:5173`. The dev server hot-reloads TypeScript/JSX
changes. The production build is created with `npm run build` and placed in
`frontend/dist/`.

### Production serving

When the FastAPI app starts, it checks for `frontend/dist/`. If the directory
exists and `SERVE_SPA` is not explicitly `false`, the built assets are mounted
at `/` via `StaticFiles(html=True)`. This means:

- `GET /` → `index.html` (the SPA)
- `GET /assets/...` → hashed JS/CSS bundles
- `GET /api/...` → FastAPI routers (registered before the SPA mount, so they
  take precedence)
- `GET /health`, `GET /docs`, `GET /openapi.json` → FastAPI built-ins (also
  registered before the mount)
- All other paths → the SPA's hash router handles them client-side

This works for both the Docker image and Render (the `buildCommand` in
`render.yaml` runs `npm ci && npm run build` in the `frontend/` directory
before installing Python deps).

### Frontend structure

```
frontend/
  src/
    api.ts           # fetch helpers + TypeScript API types
    types.ts         # mirrors app/schemas.py response shapes
    components.tsx   # DomainSignalCard, ScoreBar, badges, charts
    pages/
      Home.tsx       # search + list of synced developers
      Developer.tsx  # profile with signals, stats, repos, activity
    styles.css       # dark theme, no CSS framework
  vite.config.ts     # dev proxy to http://localhost:8000
  tsconfig.json
```

## Project structure

```
trace/
  app/
    api/            FastAPI routers (health, auth, sync, developers, me)
    services/       github_activity, ingestion, jobs, profiles, domains,
                    oauth, sessions
    _loop.py        cross-platform asyncio event-loop policy (Windows)
    config.py       env-var configuration (pydantic-settings)
    database.py     async engine + session factory + Base
    deps.py         FastAPI dependencies
    errors.py       exceptions + exception handlers
    github.py       async GitHub REST client (rate-limit / 404 handling)
    main.py         app factory + uvicorn entry point
    models.py       SQLAlchemy ORM models
    normalizers.py  GitHub → unified event normalization
    schema.py       schema bootstrap (create_all + additive column upgrades)
    schemas.py      Pydantic request/response models
  frontend/         React 19 + Vite + TypeScript SPA
  docs/             architecture and design documents
  tests/            automated test suite (runs against real PostgreSQL)
  .github/workflows/ci.yml   CI: frontend build, ruff, pytest
  Dockerfile                 multi-stage build (frontend + Python runtime)
  docker-compose.yml         local PostgreSQL + backend
  render.yaml                Render Blueprint (infrastructure as code)
  serve.py                   launcher (applies event-loop policy, honors $PORT)
  trace_schema.py            `python -m trace_schema` table creation helper
  requirements.txt / requirements-dev.txt
```

## Configuration (environment variables)

Copy `.env.example` to `.env` and adjust as needed. All values are read from
environment variables or a local `.env`.

| Variable                      | Default                                          | Purpose                              |
|-------------------------------|--------------------------------------------------|--------------------------------------|
| `DATABASE_URL`                | `postgresql+psycopg://trace:trace@localhost:5432/trace` | Async SQLAlchemy URL       |
| `GITHUB_TOKEN`                | *(empty)*                                        | Optional GitHub PAT (higher rate limit) |
| `GITHUB_API_URL`              | `https://api.github.com`                         | GitHub API base URL                  |
| `GITHUB_TIMEOUT_SECONDS`      | `15`                                             | HTTP timeout for GitHub calls        |
| `INGESTION_EVENTS_PER_PAGE`   | `30`                                             | Events fetched per request           |
| `INGESTION_EVENTS_MAX_PAGES`  | `3`                                              | Max event pages per sync             |
| `INGESTION_REPOS_PER_PAGE`    | `100`                                            | Repos fetched per request            |
| `INGESTION_REPOS_MAX_PAGES`   | `2`                                              | Max repo pages per sync              |
| `INGESTION_LANGUAGE_REPOS_LIMIT` | `10`                                          | Repos to enrich with language breakdown |
| `SYNC_WORKER_CONCURRENCY`     | `2`                                              | Background worker task count         |

Production/local credentials should be supplied via environment variables or
the container environment; secrets are never committed to the repository.

## Running the application

### Local full-stack dev (one command)

```bash
npm run dev
```

`predev` starts PostgreSQL (`docker compose up -d postgres`), then Vite (frontend
on `http://localhost:5173`) and the FastAPI backend (on `http://localhost:8000`)
run concurrently. The developer sync scripts require PostgreSQL to be reachable.

### With Docker (recommended)

```bash
docker compose up --build
```

This starts PostgreSQL and the FastAPI backend. The API is on
`http://localhost:8000`, docs at `http://localhost:8000/docs`.

### Without Docker (local)

1. Ensure PostgreSQL is running and create the `trace` database/user (the
   compose file does this for you):
   ```sql
   CREATE USER trace WITH PASSWORD 'trace';
   CREATE DATABASE trace OWNER trace;
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set `DATABASE_URL`.
4. Apply the schema and start the server:
   ```bash
   python -m trace_schema        # creates tables (see below)
   python serve.py               # starts uvicorn on 0.0.0.0:8000
   ```
   Alternatively `uvicorn app.main:app --port 8000` works directly on Linux.
   On Windows use `python serve.py`: uvicorn creates its event loop *before*
   importing the app, so the launcher applies the `SelectorEventLoop` policy
   first, which the async PostgreSQL drivers require.

> **Table creation:** tables are created automatically at application startup
> (`Base.metadata.create_all`). A small `trace_schema` helper
> (`python -m trace_schema`) is also provided to create them explicitly against
> `DATABASE_URL`. This is intentionally simpler than Alembic migrations for
> this milestone.

## Deploying on Render

`render.yaml` at the repo root is a Render Blueprint (infrastructure as code)
that provisions the PostgreSQL database and the backend web service. To deploy
on Render's free tier:

1. Create/browse to your [Render dashboard](https://dashboard.render.com).
2. **New + → New Blueprint**, connect your GitHub account if prompted.
3. Pick the **Trace** repository. Render creates the `trace-db` PostgreSQL
   database and the `trace` web service, injecting the database connection
   string into `DATABASE_URL` automatically.
4. Click **Apply**. After the first build completes (a few minutes), the app
   is live at `https://trace.onrender.com`; `GET /health` confirms the database
   connection.
5. Optional: add a GitHub Personal Access Token as the `GITHUB_TOKEN`
   environment variable in the Render dashboard to raise the GitHub API rate
   limit above the anonymous 60 requests/hour.

Notes:

- The launcher honors `$PORT`/`$HOST` (Render's defaults), and plain
  `postgres://` database URLs (as provided by Render) are normalized to the
  `postgresql+psycopg://` driver automatically.
- Free Render services hibernate after ~15 minutes of inactivity; the first
  request after a wake-up is slower.
- `autoDeploy: true` redeploys on every push to `main`.

## Running the tests

Tests run against a **real PostgreSQL** database (they exercise real
constraints and upserts) while using `httpx.MockTransport` so **no requests
reach GitHub**.

```bash
# One-time: create the test database
CREATE DATABASE trace_test OWNER trace;

pip install -r requirements-dev.txt
python -m pytest -v
```

> Use `python -m pytest` rather than the bare `pytest` command: the `app`
> package is a top-level source directory (not pip-installed), and `python -m`
> puts the repository root on `sys.path` so the test suite can import it.

Override the test DB with `TRACE_TEST_DATABASE_URL` if needed:

```bash
TRACE_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/other_db python -m pytest -v
```

Lint with:

```bash
ruff check app tests
```

## GitHub ingestion flow

1. `POST /api/v1/sync {"username": "octocat"}` → creates a `queued`
   `sync_jobs` row and enqueues its id to the in-process worker queue.
2. A background worker picks up the job and calls `IngestionService.run()`.
3. `GitHubClient` fetches the user, their repositories, per-repo language
   breakdowns, and recent events.
4. `normalizers.py` converts each raw GitHub object into a normalized,
   provider-agnostic representation.
5. `IngestionService` upserts the developer and repositories, computes domain
   labels for each repository, and inserts events.
6. `GET /api/v1/sync/{job_id}` returns job status and counts; the job ends in
   `succeeded` or `failed`.
7. `GET /api/v1/developers/{username}` returns the aggregated profile built
   from the persisted data.

## Database structure (high level)

```
developers:      id (PK), github_id (UQ), username (UQ), profile fields,
                 follower/following/public_repo counts, created/updated_at
repositories:    id (PK), developer_id (FK→developers), github_id (UQ),
                 full_name (UQ), language, languages (JSONB), topics (JSONB),
                 domains (JSONB), star/fork/issue counts, timestamps
github_events:   id (PK), developer_id (FK→developers),
                 repository_id (FK→repositories, nullable), provider,
                 event_type, github_event_id, resource_id, occurred_at,
                 payload (JSONB), received_at
sync_jobs:       id (UUID PK), developer_username, status, counts,
                 error_message, timestamps
```

| Table | Purpose |
|-------|---------|
| `developers` | A developer/user synced from GitHub. |
| `repositories` | Repositories owned by a developer, with language, topics and inferred domains. |
| `github_events` | Normalized immutable activity events. |
| `sync_jobs` | Background ingestion job lifecycle + counters. |

## Idempotency strategy

Re-ingesting the same GitHub activity must never duplicate records, which the
README distinguishes explicitly because it is a core claim. TRACE achieves
this with:

1. **Unique constraints**:
   - `developers.username` (unique)
   - `repositories.github_id` (unique)
   - `github_events (developer_id, provider, github_event_id)` (composite unique
     key `uq_github_event_identity`)
2. **Upsert semantics** on insert:
   - Developers and repositories use `INSERT ... ON CONFLICT DO UPDATE`
     (`pg_insert().on_conflict_do_update`), so re-syncing refreshes metadata
     rather than inserting a duplicate.
   - Events use `INSERT ... ON CONFLICT DO NOTHING` keyed on the composite
     event identity, so a re-delivered event is simply skipped. Because the
     GitHub event id is stable across deliveries, this never creates a
     duplicate row.
3. **Single transaction**: each sync runs in one transaction, so a run is
   atomic — a failure rolls back cleanly.

A sync job records `events_fetched`, `events_persisted`, and
`events_duplicates` so a re-run that skips everything is observable and
testable.

## Developer profile / domain inference foundation

`GET /api/v1/developers/{username}` returns a profile assembled entirely from
PostgreSQL (never by calling GitHub at request time). It includes:

- `summary` — total repositories/events, aggregated **languages** (by repo
  count) and **domains** (aggregated per-repository domains), plus the
  explainable **`domain_signals`** inference result (see below), last
  activity, per-domain event volume and a 12-month activity trend.
- `repositories` — per-repo metadata, languages, topics, and inferred domains.
- `recent_activity` — the latest normalized events.

### Domain inference (TRACE Intelligence V1)

TRACE performs **deterministic and explainable domain inference**
(`app/services/domains.py::KeywordDomainInference`). All results are
recomputed from persisted repositories and event counts; nothing is fetched
from GitHub at read time and intelligence is not yet stored.

**One per-repository scorer, three outputs.** Every output below is built on
the same per-repository scorer (`_score_repository`), so the weights and caps
apply to all of them. The previous v0.4 weights (0.5 per keyword group, 0.3
activity, 2.0 per-repository cap) are **no longer used anywhere**.

| Output | Produced by | Minimum-evidence rule |
|---|---|---|
| `intelligence.domains` | `infer_developer_intelligence` (primary, shown in the UI) | yes |
| `summary.domain_signals` | `infer_developer_domains` (legacy shape) | no |
| `summary.domains`, `repositories[].domains` | `infer_repository_domains`, stored at ingestion time | no |

**Per-repository, per-domain intensity:**

- **Language:** byte share of each language × `1.0` (at most `1.0` per
  repository). When only the primary language is known it counts as a full
  share. At ingestion time (`infer_repository_domains`) every known language
  is weighted equally, because byte counts are not passed to that call.
- **Topics:** `0.50` per distinct domain keyword matched in a topic.
- **Repository name:** `0.25` per distinct domain keyword.
- **Description:** `0.20` per distinct domain keyword.
- **Deduplication:** a keyword already counted from a topic is not counted
  again from the name or description of the same repository.
- **Keyword cap:** topic + name + description evidence is capped at `0.80`
  per repository per domain.
- **Activity:** `0.20 × min(1, events / 50)` is added only when the domain
  already has evidence in that repository; activity alone never creates a
  domain.
- **Repository cap:** total intensity is capped at `1.50` per repository per
  domain.

**Developer level:** repository intensities are summed per domain and
normalized as `score = min(1.0, raw / 3.0)` (rounded to 2 decimals in
`intelligence`, 3 in `domain_signals`).

- **Minimum-evidence rule** (`intelligence` only): a domain is kept only with
  language evidence, topic evidence, or at least 2 distinct keywords with raw
  intensity ≥ `0.40`. A lone name keyword (e.g. a repo called `my-data`) does
  not create a domain.
- **Strength** (`intelligence`): `strong` when score ≥ `0.70` and
  (≥ 2 repositories or score ≥ `0.85`); `moderate` when score ≥ `0.40`;
  otherwise `emerging`.
- **Confidence** (`domain_signals`): `high` requires ≥ 2 repositories, both
  language and keyword evidence, activity, and raw ≥ `2.4`; `medium` requires
  language **and** keyword evidence or ≥ 2 repositories; otherwise `low`.
- **Repository identity:** evidence is grouped by `full_name` (`owner/name`);
  `name` is display-only, so same-named repositories from different owners
  stay separate.
- **`score` is an *evidence score*, not a skill or proficiency
  measurement**, and strength levels make no seniority claims.
- Identical evidence always yields identical output.

Example `intelligence.domains[]` entry:

```json
{
  "name": "Backend",
  "strength": "strong",
  "score": 0.82,
  "repository_count": 2,
  "repositories": [
    {
      "full_name": "dev/auth-api",
      "name": "auth-api",
      "evidence": [
        {"type": "language", "value": "Python"},
        {"type": "topic", "value": "fastapi"}
      ]
    }
  ]
}
```

See [`docs/intelligence_v1.md`](docs/intelligence_v1.md) for the full
specification.

## API endpoints

| Method | Path                        | Description                                    |
|--------|-----------------------------|------------------------------------------------|
| GET    | `/health`                   | Liveness + DB readiness                        |
| GET    | `/`                         | SPA (or app info JSON if `frontend/dist` is absent) |
| GET    | `/auth/github`              | OAuth login: redirect to GitHub consent screen |
| GET    | `/auth/github/callback`     | OAuth callback: connect account + auto-sync   |
| POST   | `/auth/logout`              | Invalidate the session and clear its cookie    |
| POST   | `/api/v1/sync`              | Enqueue async GitHub ingestion (202)           |
| GET    | `/api/v1/sync/{job_id}`     | Query ingestion job status/counts              |
| GET    | `/api/v1/developers`        | List ingested developers                       |
| GET    | `/api/v1/developers/{username}` | Aggregated developer profile from PostgreSQL   |
| DELETE | `/api/v1/developers/{username}/fetched` | Remove a developer you fetched (signed in) |
| GET    | `/api/v1/me`                | Signed-in user's identity                      |
| GET    | `/api/v1/me/profile`        | Signed-in user's full profile                  |

The developer profile (`GET /api/v1/developers/{username}`) aggregates
persisted data into:

- `summary.total_repositories` / `total_events` / `languages`
- `summary.domains` — repositories per technical domain (baseline classifier)
- `summary.domain_signals` — legacy scored domain inference
  (`domain`, `score`, `confidence`, `evidence`, `repository_count`)
- `intelligence.domains` — TRACE Intelligence V1 domains with strength and
  per-repository evidence (see *Domain inference* above)
- `summary.events_by_domain` — activity volume per domain
- `summary.activity` — event counts per activity type (push, pull_request, …)
- `summary.events_per_month` — 12-month activity trend
- `repositories` — per-repo stats incl. `event_count` and `pushed_at`
- `recent_activity` — latest events with repo and timestamp

### GitHub OAuth (optional)

Register an OAuth app at https://github.com/settings/developers with a redirect
URI of `<your app URL>/auth/github/callback`, then set
`GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET`. Once a developer
visits `GET /auth/github` and approves access, their token is stored on their
developer record and every subsequent sync for them runs authenticated
(5000 req/hr instead of the anonymous 60 req/hr). Tokens are never returned by
the API; the "success/callback" exchange is exercised in the test suite with a
mocked GitHub HTTP client.

Interactive docs: `GET /docs` (Swagger UI).

## Current limitations / future work

**Limitations:**
- The background worker is **in-process**; queued jobs are lost on process
  restart. That is acceptable for local development — a durable broker
  (Celery/Redis, SQS, etc.) is future work.
- Schema management uses `create_all` plus idempotent `ADD COLUMN IF NOT
  EXISTS` upgrades (`app/schema.py`), not Alembic migrations.
- No GitHub **webhooks** (pull-based sync only).
- Rate limits are handled gracefully but there is no OAuth token refresh.
- Domain inference is **deterministic and evidence-based**, not learned. It
  uses only repository metadata, language breakdowns, topics, and event
  activity — it does **not** use dependency/package manifests, README content,
  commit diffs, or third-party starred/contributed repositories, so sparse
  repos are under-signaled rather than overstated. Scores are evidence
  signals, **not verified expertise**.
- No metrics/tracing, no recommendation engine.

**Future work:**
- **Temporal skill evolution** — how a developer's domains and evidence
  change over time (recency-weighted scoring, domain trend lines) is future
  work; today's inference is a static snapshot of the persisted evidence.
- Learned/ML domain classifier behind the `DomainInference` protocol (ML-based
  inference is **not** implemented yet).
- Durable job broker, Alembic migrations, structured logging/metrics.
