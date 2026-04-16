# Bizard Leads

Bizard Leads is an outreach automation platform built around FastAPI, Celery, PostgreSQL, Redis, and a static frontend. The repository is in the middle of a staged migration from n8n-based workflow orchestration to LangGraph-based agents.

The current codebase includes the foundational agent infrastructure, a production-style lead discovery pipeline with scoring, and the first approval-gated outreach agent components. Legacy workers remain in place as operational fallbacks while the agent rollout continues.

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

- Phase 1: shared agent scaffolding, settings, and environment extensions
- Phase 2: LLM routing, retry behavior, and observability foundations
- Phase 3: lead discovery agent structure and multi-source retrieval flow
- Phase 4: lead scoring agent, now wired into the active lead discovery path
- Phase 5: outreach agent foundation with approval queue persistence and approval API endpoints

The following work is not complete yet:

- Full outreach production integration across all trigger paths
- Qdrant-backed retrieval and embeddings infrastructure
- Support and reporting agents
- Final Docker handoff state without n8n
- End-to-end CI/CD and deployment hardening beyond the current test workflow

At the time of writing, the backend test suite passes locally with `36` passing tests.

## Architecture

### Application Layers

- `backend/app/api/routes`
  FastAPI route handlers and request/response orchestration
- `backend/services`
  External integrations and shared service utilities
- `backend/workers`
  Celery entrypoints and scheduled task integrations
- `backend/domains`
  Domain-specific services, workers, and models
- `backend/models`
  Shared persistence models and SQLAlchemy base wiring
- `backend/migrations`
  Alembic migrations
- `backend/app/agents`
  LangGraph-oriented agent implementations and entrypoints
- `frontend`
  Static dashboard, auth, and workflow pages
- `infra`
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

The current compose setup still includes `n8n`. Qdrant has not yet been added to the active compose file in this repository state.

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

## CI

The repository includes a GitHub Actions workflow at `.github/workflows/ci.yml` that installs backend dependencies and runs the backend test suite against PostgreSQL and Redis services.

The default dependency set does not currently force-install `langgraph-checkpoint-redis`. That package is optional in this repository state because:

- it conflicts with the current pinned `langgraph` version in default installation paths
- the application already falls back gracefully when the Redis saver package is unavailable

## Operational Notes

- Redis is still required for Celery and the current agent fallback checkpoint strategy
- The application exposes `/health` and `/ready`
- The readiness endpoint checks database connectivity and agent checkpointer availability
- Some later-phase LangGraph runtime behavior depends on version compatibility in the LangGraph stack and will continue to be tightened as the agent rollout progresses

## Repository Roadmap

The next major development areas are:

1. Complete the approval-gated outreach integration across trigger paths
2. Add vector infrastructure and retrieval components
3. Implement support and reporting agents
4. Finalize Docker and CI/CD handoff state
5. Remove n8n from active orchestration once the LangGraph replacements are fully in service
