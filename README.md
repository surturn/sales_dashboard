# Bizard Leads

Bizard Leads is an outreach automation platform built around FastAPI, Celery, PostgreSQL, Redis, and a static frontend. The repository is in the middle of a staged migration from n8n-based workflow orchestration to LangGraph-based agents.

The current codebase includes the foundational agent infrastructure, a production-style lead discovery pipeline with scoring, an approval-gated outreach path, and the first Qdrant-backed semantic memory components. Legacy workers remain in place as operational fallbacks while the agent rollout continues.

## Overview

The system combines:

- A FastAPI application for API endpoints and dashboard data
- Celery workers and scheduled tasks for background processing
- PostgreSQL for persistent application data
- Redis for Celery broker/backend and agent fallback checkpoint storage
- A static frontend served through Nginx in containerized environments
- Existing n8n workflows that are being replaced incrementally by LangGraph agents

## Current State

The repository currently reflects the following implementation state:


The following work is not complete yet:


At the time of writing, the backend test suite passes locally with `41` passing tests.


## Phase 7 — Reporting Agent & ICP Learning Loop

Phase 7 replaces the legacy n8n weekly report workflow with a LangGraph-based
ReportingAgent and implements the PRIME ICP learning loop so the scorer learns
from actual conversions over time.

What changed
- New LangGraph reporting agent: [backend/app/agents/reporting.py](backend/app/agents/reporting.py)
  - Nodes: `metrics_collector`, `metrics_assembler`, `narrative_writer`, `icp_updater`, `report_sender`.
  - The agent tries to run first via the scheduler entrypoint and falls back to the
    existing worker `backend/workers/reporting.generate_weekly_report_task` on error.
- ICP learning loop: conversions recorded during the week are embedded and upserted
  into Qdrant (`settings.QDRANT_COLLECTION_ICP`) to improve per-user scoring.
  See: [backend/migrations/versions/005_add_conversions_table.py](backend/migrations/versions/005_add_conversions_table.py)

- Scheduler changes: the project now uses an agent-first scheduler shim
  [backend/workers/scheduler.py](backend/workers/scheduler.py) that exposes
  Celery wrapper tasks which attempt to run LangGraph agents first and fall
  back to the legacy Celery workers when agents are unavailable or fail.
  Celery beat was updated to call these wrappers (weekly reports via
  `backend.workers.scheduler.trigger_weekly_report`) and a new daily
  lead-sourcing job (`backend.workers.scheduler.trigger_lead_sourcing` at
  03:00 UTC) so agent-driven scheduling is the primary execution path.

Tavily (intent signals)
- Optional integration with Tavily to surface intent signals per-user and per-lead.
  - Client: [backend/app/services/tavily_client.py](backend/app/services/tavily_client.py)
  - When `TAVILY_API_KEY` is set, the reporting agent will attach `intent_signals`
    to the report metrics and to each ICP payload upserted to Qdrant. The agent
    falls back to empty signals when the key is not configured.

Database migrations
- A new migration adds `conversions` to track recorded conversions used by the
  ICP learning loop. Apply it with Alembic:

```bash
alembic upgrade head
```

Testing & CI
- Unit and integration tests added for the reporting agent and ICP updater. Run
  the tests locally with:

```bash
python -m pytest backend/tests -q
```

- The GitHub Actions CI runs the same test suite with Postgres and Redis services.
  Qdrant and Tavily calls are mocked in tests so CI does not require external
  Tavily credentials or a live Qdrant instance.

Deployment notes
- Add the following environment variables in production: `DATABASE_URL`, `REDIS_URL`,
  `QDRANT_HOST`, `QDRANT_PORT`, and optionally `TAVILY_API_KEY` if you want intent
  signals enabled.
- Ensure Qdrant collections exist; the app will try to create them on startup
  (`backend/app/services/qdrant_client.py`).
- Run migrations and verify the app's `/ready` endpoint before routing traffic.

Handoff / PR checklist
- Summary of changes and motivation (Phase 7: Reporting + ICP learning loop)
- Files changed: `backend/app/agents/reporting.py`, `backend/app/services/tavily_client.py`,
  `backend/migrations/versions/005_add_conversions_table.py`, and tests under
  `backend/tests/test_agents/`.
  Also updated scheduler and Celery config: `backend/workers/scheduler.py`,
  `backend/workers/celery_app.py`.
- Run locally: `python -m pytest backend/tests -q` (47 tests passing locally at time of change)
- Migration: `alembic upgrade head`
- Add `TAVILY_API_KEY` (optional) and ensure Qdrant is reachable in production.

If you'd like, I can open a PR with this checklist and a short description for your friend.
## Architecture

### Application Layers

  FastAPI route handlers and request/response orchestration
  External integrations and shared service utilities
  Celery entrypoints and scheduled task integrations
  Domain-specific services, workers, and models
  Shared persistence models and SQLAlchemy base wiring
  Alembic migrations
  LangGraph-oriented agent implementations and entrypoints
  Static dashboard, auth, and workflow pages
  Container and Nginx support files

### Agent Rollout Model

The migration strategy is intentionally conservative:

- New agent entrypoints are introduced behind existing scheduler and webhook paths
- Legacy workers remain available as fallbacks when an agent path is unavailable or fails
- Blocking database and SMTP operations are wrapped for compatibility with the async agent layer
- Optional LangGraph-specific dependencies are loaded lazily where possible to keep local development and CI stable

## Implemented Agent Components

### Lead Discovery

The active lead discovery flow includes:

- ICP loading
- multi-source retrieval
- triangulation
- deduplication
- lead scoring
- HubSpot sync

The lead scorer is a two-pass implementation:

- first-pass batch scoring
- focused self-critique on top-tier leads

### Outreach

The outreach work now includes:

- an outreach agent state definition
- context building for personalization
- LLM-based drafting
- critique and rewrite flow
- approval queue persistence
- approval and rejection API endpoints

The approval-gated flow is present in code, while broader production integration across all current trigger surfaces is still in progress.

### Semantic Memory and Support

Phase 6 adds the first semantic memory layer:

- Qdrant collection management for leads, support knowledge chunks, and ICP profiles
- a local sentence-transformers embedding service
- a support agent that retrieves relevant KB chunks before drafting a reply
- Postgres fallback to full support KB text when Qdrant retrieval is unavailable
- Chatwoot webhook handling routed through the support agent with legacy worker fallback

## Requirements

### Core Runtime

- Python 3.12 for local development in this repository
- PostgreSQL
- Redis

### Optional or Later-Phase Services

- Groq
- OpenAI
- HubSpot
- Chatwoot
- Mailtrap SMTP
- Tavily
- Qdrant

## Configuration

Copy `.env.example` to `.env` and provide the required values.

```powershell
Copy-Item .env.example .env
```

The most important variables are:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
- `OPENAI_API_KEY`
- `HUBSPOT_ACCESS_TOKEN`
- `CHATWOOT_API_KEY`
- `MAILTRAP_HOST`
- `MAILTRAP_PORT`
- `MAILTRAP_USERNAME`
- `MAILTRAP_PASSWORD`

Agent-related settings already supported by the application include:

- `GROQ_API_KEY`
- `GROQ_MODEL_FAST`
- `GROQ_MODEL_LARGE`
- `LLM_CACHE_TTL_SECONDS`
- `LLM_MAX_TOKENS_PER_NODE`
- `AGENT_MAX_RETRIES`
- `AGENT_RETRY_BASE_DELAY`
- `AGENT_CIRCUIT_BREAKER_THRESHOLD`
- `AGENT_FALLBACK_ENABLED`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `QDRANT_API_KEY`
- `QDRANT_COLLECTION_LEADS`
- `QDRANT_COLLECTION_SUPPORT_KB`
- `QDRANT_COLLECTION_ICP`

## Local Development

### Create and Activate a Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

### Run the API

```powershell
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

### Run Background Workers

```powershell
.venv\Scripts\python.exe -m celery -A backend.workers.celery_app worker --loglevel=info
```

```powershell
.venv\Scripts\python.exe -m celery -A backend.workers.celery_app beat --loglevel=info
```

## Containerized Development

Bring up the stack with:

```powershell
docker compose up --build
```

The current compose setup includes `Qdrant` alongside the existing services. `n8n` is still present because the repository is still in the middle of the staged LangGraph migration.

## Testing

Run the backend suite with:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

The current suite covers:

- API smoke tests
- service behavior
- worker behavior
- retry and circuit breaker behavior
- lead scorer behavior
- lead discovery phase wiring
- approvals API behavior
- outreach agent node behavior
- support agent behavior
- Qdrant client behavior

## CI

The repository includes a GitHub Actions workflow at `.github/workflows/ci.yml` that installs backend dependencies and runs the backend test suite against PostgreSQL and Redis services.

The default dependency set does not currently force-install `langgraph-checkpoint-redis`. That package is optional in this repository state because:

- it conflicts with the current pinned `langgraph` version in default installation paths
- the application already falls back gracefully when the Redis saver package is unavailable

## Operational Notes

- Redis is still required for Celery and the current agent fallback checkpoint strategy
- Qdrant is initialized at application startup when available and checked by `/ready`
- The application exposes `/health` and `/ready`
- The readiness endpoint checks database connectivity, agent checkpointer availability, and Qdrant connectivity
- Some later-phase LangGraph runtime behavior depends on version compatibility in the LangGraph stack and will continue to be tightened as the agent rollout progresses

## Repository Roadmap

The next major development areas are:

1. Complete the approval-gated outreach integration across trigger paths
2. Harden the new support and outreach agent paths across remaining trigger surfaces
3. Implement the reporting agent and later ICP learning loop
4. Finalize Docker and CI/CD handoff state
5. Remove n8n from active orchestration once the LangGraph replacements are fully in service
