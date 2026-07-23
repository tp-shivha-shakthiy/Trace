# TRACE

A production-style developer intelligence platform. TRACE ingests raw developer activity from GitHub, normalizes it into immutable events, asynchronously processes it into structured evidence, transforms it into a temporal knowledge graph, and queries it with reasoning engines to produce explainable developer intelligence.

## Architecture

TRACE has eight logical layers:

```
1. Presentation Layer       React + TypeScript + D3.js
2. API / Application Layer  FastAPI
3. Ingestion Layer          GitHub adapters + Event normalizer
4. Event Processing Layer   Celery workers + Redis queues
5. Intelligence Layer       Skill scorer + Domain classifier + Graph reasoner
6. Knowledge Graph Layer    Temporal developer knowledge graph
7. Persistence Layer        PostgreSQL (source of truth)
8. Infrastructure           Docker Compose + Observability
```

### Data Flow

```
External Activity (GitHub)
       |
       v
  Ingestion (Webhook / Initial Sync)
       |
       v
  Unified Event (idempotent store)
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

### Tech Stack

| Layer              | Technology                              |
|--------------------|-----------------------------------------|
| Frontend           | React, TypeScript, Vite, Tailwind, D3.js, React Query |
| API                | FastAPI, Pydantic                       |
| Database           | PostgreSQL                              |
| Queue / Cache      | Redis                                   |
| Workers            | Celery                                  |
| Infrastructure     | Docker Compose                          |

### API Endpoints

**Authentication**
```
GET  /auth/github
GET  /auth/github/callback
POST /auth/logout
GET  /auth/me
```

**Developer Intelligence**
```
GET /api/v1/me
GET /api/v1/me/skills
GET /api/v1/me/skills/timeline
GET /api/v1/me/domains
GET /api/v1/me/graph
GET /api/v1/me/gaps
GET /api/v1/me/recommendations
```

**Synchronization**
```
POST /api/v1/sync
GET  /api/v1/sync/status
```

**Webhooks**
```
POST /webhooks/github
```

**Operations**
```
GET /health
GET /metrics
```

### Worker Types

| Worker           | Responsibility                                        |
|------------------|-------------------------------------------------------|
| Sync Worker      | Fetch GitHub repositories, languages, topics, events  |
| Feature Worker   | Extract skill evidence from repository metadata       |
| Scoring Worker   | Compute temporal skill scores with recency decay      |
| Classifier Worker | Classify repositories into domains                   |
| Graph Worker     | Update knowledge graph, detect gaps, gen recommendations |

### Event Model

All GitHub events (webhooks and backfill) are normalized into a single `UnifiedEvent` format before entering the processing pipeline, ensuring downstream workers are provider-agnostic.

### Temporal Skill Scoring

```
score(skill) = sum(evidence_i * quality_i * recency_i) normalized to 0-100
recency_weight = exp(-lambda * age_in_days)
```

Skill velocity tracks score trajectory over time to distinguish stable proficiency from rapid growth.

### Knowledge Graph

Three categories of information:

- **Static Knowledge**: Skill-to-domain mappings, skill dependencies, domain adjacencies
- **Developer Evidence**: What skills/domains a developer uses
- **Derived Intelligence**: Strengths, gaps, and adjacent domains

### Recommendations

Generated from skill gaps, domain adjacencies, skill dependencies, and trajectory data. Each recommendation includes an explainable reason based on graph reasoning.

## Project Structure

```
trace/
  docs/          Architecture and design documents
  prototype/     Initial adaptive engine prototype
```

## Development

```bash
docker-compose up
```

