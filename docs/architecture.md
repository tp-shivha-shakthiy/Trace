# TRACE Architecture

## Implementation Status (v0.3)

> **v0.3 implements:** a real, runnable FastAPI backend with an end-to-end
> GitHub → ingestion → async processing → PostgreSQL → developer profile flow.
> See `README.md` for how to run it.

The *implemented* portion of the design below currently covers:

| Layer / component                 | Status in v0.3 |
|-----------------------------------|----------------|
| API / Application (FastAPI)       | ✅ implemented  |
| Ingestion (GitHub REST backfill)  | ✅ implemented  |
| Normalization to unified events   | ✅ implemented  |
| Idempotent event store (Postgres) | ✅ implemented  |
| Async background ingestion        | ✅ implemented (in-process `asyncio` task pool — **not** Celery/Redis) |
| Domain intelligence (deterministic) | ✅ implemented (`KeywordDomainInference`: weighted evidence scores + confidence policy + explicit `evidence` reasons, not ML) |
| Profile API from persisted data   | ✅ implemented  |
| Docker Compose / local dev        | ✅ implemented  |
| GitHub OAuth + webhooks           | ⏳ future       |
| Celery/Redis event processing     | ⏳ future (design retained below) |
| Temporal skill scoring            | ⏳ future       |
| Knowledge graph + recommendations | ⏳ future       |
| ML domain classifier              | ⏳ future (extension point: `DomainInference` protocol) |
| React frontend                    | ⏳ future       |

The sections below describe the **target** architecture (the product vision).
Anything marked as in the "Event Processing Layer" (e.g. Celery/Redis, DLQ)
is aspirational and not yet present in the codebase.

## Overview

TRACE is a developer intelligence platform. The central architectural principle:

> Raw developer activity is ingested once, normalized into immutable events, asynchronously processed into structured evidence, transformed into a temporal knowledge graph, and then queried by reasoning engines to produce explainable developer intelligence.

## Layers

TRACE has eight logical layers:

1. **Presentation Layer** — React + TypeScript + D3.js + React Query
2. **API / Application Layer** — FastAPI, routers, services, repositories
3. **Ingestion Layer** — GitHub adapters (OAuth, API backfill, webhooks)
4. **Event Processing Layer** — Celery workers, Redis queues, idempotency, retries, DLQ
5. **Intelligence Layer** — Skill scorer, domain classifier, graph reasoner, recommendation engine
6. **Knowledge Graph Layer** — Temporal developer knowledge graph with static + derived edges
7. **Persistence Layer** — PostgreSQL as source of truth
8. **Infrastructure / Observability** — Docker Compose, structured logging, metrics, tracing

## High-Level Data Flow

```
External Activity (GitHub)
       |
       v
  Ingestion (Webhook / Initial Sync)
       |
       v
  Unified Event (idempotent store in PostgreSQL)
       |
       v
  Redis / Celery Task Queue
       |
       v
  Workers (Feature Extraction, Scoring, Classification, Graph Update)
       |
       v
  Intelligence Layer (Skill Scoring, Domain Classification, Graph Reasoning)
       |
       v
  Knowledge Graph (Skills, Domains, Edges, Gaps)
       |
       v
  Recommendations (Explainable insights)
       |
       v
  Frontend (React Dashboard)
```

## API Layer

### Authentication

```
GET  /auth/github
GET  /auth/github/callback
POST /auth/logout
GET  /auth/me
```

### Developer Intelligence

```
GET /api/v1/me
GET /api/v1/me/skills
GET /api/v1/me/skills/timeline
GET /api/v1/me/domains
GET /api/v1/me/graph
GET /api/v1/me/gaps
GET /api/v1/me/recommendations
```

### Synchronization

```
POST /api/v1/sync
GET  /api/v1/sync/status
```

### Webhooks

```
POST /webhooks/github
```

### Operations

```
GET /health
GET /metrics
```

### API Design

Routers delegate to services, services delegate to repositories:

```
Router -> Service -> Repository -> Database
```

Routers handle request validation and response serialization. Services contain business logic. Repositories handle data access.

## Ingestion Layer

Two ingestion paths that converge into the same unified event pipeline:

### Initial Sync (first-time GitHub connection)

```
User connects GitHub
       |
       v
POST /api/v1/sync -> Create SyncJob -> Queue BackfillTask
       |
       v
Worker fetches: repositories, languages, topics, dependency files, activity
       |
       v
Normalize -> Unified Event -> Event Store
```

### Webhook (continuous updates)

```
GitHub push event
       |
       v
POST /webhooks/github
       |
       v
Verify HMAC signature -> Parse event -> Normalize -> Event Store -> Queue task
```

Both paths produce the same `UnifiedEvent` format, so downstream workers are provider-agnostic.

## Unified Event Model

All GitHub events are normalized into one internal format:

```python
class UnifiedEvent:
    event_id: str
    user_id: UUID
    provider: str
    event_type: str
    resource_id: str
    repository_id: str
    occurred_at: datetime
    payload: dict
```

Supported event types:

- `repository_created`
- `repository_updated`
- `commit`
- `pull_request_opened`
- `pull_request_merged`
- `issue_opened`
- `issue_closed`
- `release_created`

## Event Processing Layer

### Queue Architecture

```
Redis
 |
 +-- sync_queue
 +-- event_queue
 +-- feature_queue
 +-- scoring_queue
 +-- classifier_queue
 +-- graph_queue
```

V1 starts with a single `default` queue, splitting when complexity demands it.

### Workers

| Worker           | Responsibility                                                   |
|------------------|------------------------------------------------------------------|
| Sync Worker      | Fetch GitHub repositories, languages, topics, raw events         |
| Feature Worker   | Extract skill evidence from repo metadata, dependencies, topics  |
| Scoring Worker   | Compute temporal skill scores with quality weighting and recency decay |
| Classifier Worker | Classify repositories into domains using multi-label classifier |
| Graph Worker     | Update knowledge graph, detect gaps, generate recommendations    |

### Event Processing Lifecycle

```
Developer pushes commit
       |
       v
GitHub webhook
       |
       v
HMAC verification -> Normalize event -> Idempotency check -> PostgreSQL event store
       |
       v
Queue processing job -> Celery worker
       |
       v
Extract evidence -> Skill evidence -> Temporal scoring -> Developer skill edge
       |
       v
Graph update -> Graph reasoner -> Recommendations -> Frontend
```

### Idempotency

GitHub events can be delivered more than once. The event store uses a unique key:

```
(user_id, provider, event_type, resource_id, occurred_at)
```

With `INSERT ... ON CONFLICT DO NOTHING`, duplicate events produce one logical event.

Processing is also idempotent: processing the same event twice produces the same skill score, not an incremented one.

### Retry Architecture

Transient failures (GitHub timeout, Redis failure, DB connection error) retry up to 5 times with exponential backoff. Permanent failures (deleted repo, malformed event) do not retry indefinitely.

```
Task -> Attempt 1 -> Success: Done
                    -> Failure: Retry 1 -> Retry 2 -> ... -> Retry 5 -> DLQ
```

### Dead-Letter Queue (DLQ)

Stores failed tasks with:

- `task_name`
- `task_arguments`
- `failure_reason`
- `retry_count`
- `created_at`

Enables inspection of why a task failed and manual retry via `POST /admin/dlq/{id}/retry`.

## Intelligence Layer

Four major engines:

```
           Intelligence Layer
                  |
    +-------------+-------------+
    |             |             |
    v             v             v
Skill Scorer  Domain Classifier  Graph Reasoner
    |             |             |
    +-------------+-------------+
                  |
         Recommendation Engine
```

### Skill Evidence Extraction

Evidence extraction is the first step, not scoring. A repository produces raw evidence:

```
Repository
 +-- requirements.txt -> fastapi, sqlalchemy, redis
 +-- Dockerfile -> Docker
 +-- Python files -> Python
 +-- GitHub topics -> backend, api
```

Produces evidence like:

```json
{"Python": 1.0, "FastAPI": 1.0, "SQLAlchemy": 1.0, "Redis": 1.0, "Docker": 1.0}
```

This is evidence, not a skill score.

### Temporal Skill Scoring

```
score(skill) = sum(evidence_i * quality_i * recency_i) normalized to 0-100
recency_weight = exp(-lambda * age_in_days)
```

Output:

```json
{
  "skill": "FastAPI",
  "score": 82.4,
  "velocity": 4.7,
  "evidence_count": 27,
  "last_active_at": "2026-07-20"
}
```

### Skill Velocity

Tracks whether a developer is getting stronger. Distinguishes stable proficiency from rapid growth:

```
Developer A: FastAPI = 80 (stable)
Developer B: FastAPI = 80 (grew from 30 -> 80)
```

### Domain Classifier

Multi-label classifier operating at repository level:

```
Repository -> FeatureBuilder (dependencies, languages, topics) -> DomainClassifier -> Domain probabilities
```

Example:

```json
{"backend": 0.92, "devops": 0.81, "machine_learning": 0.14, "frontend": 0.05}
```

Aggregated across repositories into a developer domain profile.

### Recommendation Engine

Consumes: skill gaps, domain adjacencies, skill dependencies, skill trajectory.

Produces recommendations of types: `skill_gap`, `domain_expansion`, `natural_progression`.

Each recommendation includes an explainable reason derived from graph reasoning.

## Knowledge Graph

### Three Categories of Information

**Static Knowledge:**
```
FastAPI --BELONGS_TO--> Backend
FastAPI --REQUIRES--> Python
FastAPI --COMMONLY_WITH--> PostgreSQL
```

**Developer Evidence:**
```
Developer --USES--> FastAPI
Developer --USES--> Python
Developer --USES--> PostgreSQL
```

**Derived Intelligence:**
```
Developer --STRONG_IN--> Backend
Developer --HAS_GAP--> Docker
Developer --ADJACENT_TO--> Data Engineering
```

### Graph Reasoning

Gap detection example:

```
Developer Backend confidence = 0.91
Docker expected weight (from static graph) = 0.90
Docker actual score = 0.12
-> Gap detected -> Recommendation: "Strengthen Docker"
```

The recommendation includes the reasoning chain, not just the suggestion.

### Temporal Architecture

**Current state** (developer_skill_edges, developer_domain_edges) answers: "What does TRACE think about me now?"

**Historical state** (graph_snapshots) answers: "How has my developer profile changed?"

Combined they produce trajectory data.

## Persistence Layer

PostgreSQL is the system of record. Redis handles operational state only.

### Logical Schema

```
USER
 +-- REPOSITORIES
 |     +-- EVENTS
 +-- DEVELOPER_SKILL_EDGES
 |     +-- SKILL_NODES
 +-- DEVELOPER_DOMAIN_EDGES
 |     +-- DOMAIN_NODES
 +-- GRAPH_SNAPSHOTS
 +-- RECOMMENDATIONS
 +-- SYNC_JOBS
```

Static graph:
```
SKILL_NODES --SKILL_DOMAIN_EDGES--> DOMAIN_NODES
SKILL_NODES --SKILL_DEPENDENCY_EDGES--> SKILL_NODES
DOMAIN_NODES --DOMAIN_ADJACENCY_EDGES--> DOMAIN_NODES
```

### PostgreSQL vs Redis

| PostgreSQL (source of truth) | Redis (operational state)    |
|------------------------------|------------------------------|
| Events, Users, Skills, Graph | Celery broker                |
| Historical snapshots         | Caching                      |
| Recommendations              | Rate limits                  |
|                              | Sync progress                |

## Infrastructure

### Development

```
Docker Compose
 +-- postgres     ✅ v0.3
 +-- backend      ✅ v0.3
 +-- redis        ⏳ future
 +-- celery-worker ⏳ future
 +-- frontend     ⏳ future
```

### Production

```
Internet -> Reverse Proxy -> React App + FastAPI
                                      |
                           +----------+----------+
                           |          |          |
                        PostgreSQL   Redis    Celery Workers
```

## Observability

### Structured Logging

Events tracked: `event_received`, `event_stored`, `task_started`, `task_retry`, `task_failed`, `skill_updated`, `graph_updated`, `recommendation_generated`.

### Metrics

- `events_processed_total`
- `events_failed_total`
- `tasks_retried_total`
- `dlq_size`
- `sync_duration_seconds`
- `github_api_calls_total`
- `github_rate_limit_remaining`
- `skill_updates_total`
- `recommendations_generated_total`
- `api_request_duration_seconds`

### Tracing

Request/task correlation IDs enable following the full lifecycle from webhook ingestion through graph update.

## Security

### GitHub OAuth

Tokens encrypted at rest, never stored as plaintext.

### Webhooks

HMAC signature verification (`X-Hub-Signature-256`) before processing.

### Authorization

Every user-specific query scoped: `WHERE user_id = current_user.id`. No user ID in URL paths without authorization checks.

## Development Roadmap

1. **Month 1**: Event system (ingestion, normalization, queues, retries, idempotency)
2. **Month 2**: Skill intelligence + knowledge graph
3. **Month 3**: Domain ML classifier + graph reasoning + frontend visualization
