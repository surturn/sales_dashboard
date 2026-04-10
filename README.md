# Bizard Leads

Bizard Leads is an AI-powered outreach automation platform for SMBs. The repo follows a layered monolith shape:

- `backend/app/api/routes` for FastAPI endpoints
- `backend/services` for integrations and business logic
- `backend/workers` for Celery workflows
- `backend/models` and `backend/migrations` for persistence
- `frontend` for the static dashboard and auth pages
- `infra` for nginx and compose-related support files

## Architecture (Current State: Through Phase 4)

Bizard Leads is being refactored to replace n8n automation with **LangGraph agents**. The repo currently includes the Phase 1-4 foundation:

- **`backend/app/agents/`**: Agent package with LangGraph-compatible lead discovery and lead scorer implementations.
- **Agent entrypoints**: Scheduler and webhook paths try agents first, then safely fall back to existing Celery workers.
- **Shared agent base** (`backend/app/agents/base.py`): TypedDicts, thread ids, agent result wrappers, and optional Redis checkpointer loading.
- **LLM router** (`backend/services/llm_router.py`): Unified async entry point for LLM calls with Groq-primary / OpenAI-fallback behaviour.
- **Core utilities** (`backend/app/core/observability.py`, `backend/app/core/retry.py`): Structured logging, Sentry init, retries, and circuit breaker support.
- **Approval routing** (`backend/app/api/routes/approvals.py`): Stub endpoints reserved for the future human-in-the-loop outreach gate.

### Current integration workflow:

- **Lead discovery**: ICP loading -> multi-source retrieval -> triangulation -> deduplication -> PRIME scoring -> HubSpot sync
- **Lead scorer**: Two-pass scoring with first-pass batch scoring and a focused self-critique pass on top-tier leads
- **Email generation + verification**: pattern generation + SMTP verification
- **CRM sync**: HubSpot
- **Outreach delivery**: Mailtrap SMTP (approval gate scaffolded for Phase 5)
- **AI personalization**: OpenAI (via llm_router; Groq + fallback in Phase 2)
- **Reporting**: weekly summaries (Celery fallback; LangGraph agent scaffolded)
- **Support**: Chatwoot AI responses (Celery fallback; LangGraph + Qdrant RAG in Phase 6)

## Setup

### Step 1: Create and activate virtual environment

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
```

### Step 2: Install dependencies

```powershell
pip install -r backend/requirements.txt
```

### Step 3: Configure environment

Copy `.env.example` to `.env` and fill in the required secrets:

```powershell
cp .env.example .env
```

Required keys:
- **Core**: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`
- **Existing integrations**: `OPENAI_API_KEY`, `HUBSPOT_ACCESS_TOKEN`, `CHATWOOT_API_KEY`
- **Phase 1-4 (agent runtime)**: `GROQ_API_KEY` (optional; uses OpenAI fallback if not set)
- **Phase 2+**: `TAVILY_API_KEY` (intent signals), `QDRANT_HOST`/`PORT`/`QDRANT_API_KEY` (vector DB), `SENTRY_DSN` (error tracking)

### Local backend

```powershell
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

In separate terminals:

```powershell
# Celery worker
backend\.venv\Scripts\python.exe -m celery -A backend.app.workers.celery_app worker --loglevel=info

# Celery beat scheduler
backend\.venv\Scripts\python.exe -m celery -A backend.app.workers.celery_app beat --loglevel=info
```

### Full stack (Docker)

```powershell
docker compose up --build
```

Services:
- FastAPI: http://localhost:8000
- Flower (Celery monitor): http://localhost:5555
- Postgres: localhost:5432
- Redis: localhost:6379
- n8n: http://localhost:5678
- Qdrant (planned, not yet in compose): localhost:6333

## Testing

Run the test suite locally:

```powershell
python -m pytest -q
```

The current backend suite should pass locally. At the time of writing, the repo has **31 passing backend tests** covering smoke checks, workers, services, retry behaviour, and agent scoring/wiring.

## Agent Entrypoint Fallback Mechanism

Phase 1 introduces a **reversible fallback pattern**:

1. Scheduler and webhook handlers **try agent entrypoints first** (e.g., `try_run_lead_sourcing`).
2. If an agent function is not found, raises an exception, or returns `False`, the system **falls back to existing Celery tasks**.
3. This allows iterative agent implementation without disrupting the active platform.

Example (scheduler.py):
```python
handled = try_run_lead_sourcing(query=query, user_id=user_id)
if handled:
    return {"status": "agent_handled"}
return source_leads_task.delay(query=query, user_id=user_id)  # fallback
```

## Phase Status

✅ **Implemented through Phase 4 foundation**:
- Scaffolded `backend/app/agents/` with shared base types and agent entrypoints
- Extended `backend/app/config.py` with Groq, Tavily, Qdrant, Sentry, and agent tuning settings
- Added the async LLM router, observability layer, and retry/circuit-breaker utilities
- Implemented the lead discovery agent with ICP loading, multi-source retrieval, triangulation, deduplication, scoring, and HubSpot sync
- Implemented the Phase 4 PRIME lead scorer and wired it into the active lead discovery path
- Wired scheduler and webhook routes to agent entrypoints with safe fallbacks
- Current backend tests pass locally (31 passed)

⏳ **Next**:
- Phase 5: Outreach agent (email generation, human approval gate)
- Phase 6: Qdrant RAG infrastructure
- Phase 7: Support and Reporting agents with ICP learning loop
- Phase 8–11: Testing, CI/CD, Docker, and handoff

## Production Readiness

- **Redis is still required:** the app depends on Redis for Celery and agent fallback checkpoint storage; configure `REDIS_URL` in your environment (see `.env.example`). `docker compose` includes Redis and healthchecks.
- **Redis LangGraph saver is optional in this checkpoint:** the repo now loads the LangGraph Redis saver lazily. If `langgraph-checkpoint-redis` is not installed, the app can still install, test, and run with fallback behaviour. Durable LangGraph checkpointing can be enabled later by installing that optional package once version compatibility is settled.
- **Readiness probe:** the backend exposes `/ready` which verifies DB connectivity and the LangGraph checkpointer. Use this for orchestration readiness checks.
- **CI:** a GitHub Actions workflow (`.github/workflows/ci.yml`) runs the test suite with Postgres and Redis services. The `openai` dependency pin was relaxed to `openai>=1.54.0,<2.0.0` to satisfy transitive requirements from `langchain-openai`, and the incompatible Redis checkpoint package pin was removed from the default install set.

These changes keep the current agent-based rollout installable and testable while preserving the option to add durable Redis-backed LangGraph checkpoints later.
