# TRACE

[![CI](https://github.com/tp-shivha-shakthiy/Trace/actions/workflows/ci.yml/badge.svg)](https://github.com/tp-shivha-shakthiy/Trace/actions/workflows/ci.yml)

A developer intelligence platform. TRACE ingests raw developer activity from
GitHub, normalizes it into deterministic events, persists it asynchronously
into PostgreSQL, and serves an aggregated developer profile — including a
coarse technical-domain profile — through a FastAPI backend.

**TRACE is at v0.3.** This milestone delivers a real, runnable, end-to-end
backend foundation:

```
GitHub API → activity ingestion → asynchronous processing → PostgreSQL → developer profile API
```

It does **not** yet implement the full product vision (temporal knowledge
graph, ML skill/domain classifier, recommendations, webhooks, React frontend
and OAuth are future work). See [Limitations & future work](#current-limitations--future-work).

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
| Infrastructure   | Docker Compose (optional local dev)            |

## Project structure

```
trace/
  app/
    api/            FastAPI routers (health, sync, developers)
    services/       github_activity, ingestion, jobs, profiles, domains
    config.py       env-var configuration (pydantic-settings)
    database.py     async engine + session factory + Base
    deps.py         FastAPI dependencies
    errors.py       exceptions + exception handlers
    github.py       async GitHub REST client (rate-limit / 404 handling)
    main.py         app factory + uvicorn entry point
    models.py       SQLAlchemy ORM models
    normalizers.py  GitHub → unified event normalization
    schemas.py      Pydantic request/response models
  docs/             architecture and design documents
  prototype/        earlier (prototype) exploratory code
  tests/            automated test suite (runs against real PostgreSQL)
  Dockerfile
  docker-compose.yml
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
pytest -v
```

Override the test DB with `TRACE_TEST_DATABASE_URL` if needed:

```bash
TRACE_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/other_db pytest -v
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
  count) and **domains** (aggregated per-repository domains), last activity.
- `repositories` — per-repo metadata, languages, topics, and inferred domains.
- `recent_activity` — the latest normalized events.

Domain inference is **deliberately a deterministic baseline**
(`app/services/domains.py::KeywordDomainInference`) that maps a repository to
coarse domains like `backend`, `frontend`, `data`, `ml`, `devops`, `mobile`,
etc. from its languages, topics, and name/description keywords. It is *not*
an ML model. The `DomainInference` protocol is the clean extension point where
a future ML classifier can be plugged in without changing the ingestion
pipeline. The ingestion pipeline only calls the protocol, so the baseline is
swappable.

## API endpoints

| Method | Path                        | Description                                    |
|--------|-----------------------------|------------------------------------------------|
| GET    | `/health`                   | Liveness + DB readiness                        |
| GET    | `/`                         | App info / docs link                           |
| GET    | `/auth/github`              | OAuth login: redirect to GitHub consent screen |
| GET    | `/auth/github/callback`     | OAuth callback: connect account + auto-sync   |
| POST   | `/api/v1/sync`              | Enqueue async GitHub ingestion (202)           |
| GET    | `/api/v1/sync/{job_id}`     | Query ingestion job status/counts              |
| GET    | `/api/v1/developers`        | List ingested developers                       |
| GET    | `/api/v1/developers/{username}` | Aggregated developer profile from PostgreSQL   |

The developer profile (`GET /api/v1/developers/{username}`) aggregates
persisted data into:

- `summary.total_repositories` / `total_events` / `languages`
- `summary.domains` — repositories per technical domain (baseline classifier)
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

**Limitations (v0.3):**
- The background worker is **in-process**; queued jobs are lost on process
  restart. That is acceptable for local development — a durable broker
  (Celery/Redis, SQS, etc.) is future work.
- Schema management uses `create_all`, not Alembic migrations.
- No GitHub **webhooks** (pull-based sync only) and no GitHub **OAuth**.
- Rate limits are handled gracefully but there is no OAuth token refresh.
- Domain inference is keyword/baseline based, not learned.
- No metrics/tracing, no recommendation engine, no frontend.

**Future work (beyond v0.3):**
- Temporal skill scoring and a knowledge graph (repository metadata → skill
  evidence → temporal score).
- Learned/ML domain classifier behind the `DomainInference` protocol.
- Webhooks + OAuth, durable job broker, Alembic migrations, structured
  logging/metrics, and a React dashboard.
