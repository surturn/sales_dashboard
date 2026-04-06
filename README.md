# Bizard Leads

Bizard Leads is an AI-powered outreach automation platform for SMBs. The repo follows a layered monolith shape:

- `backend/app/api/routes` for FastAPI endpoints
- `backend/services` for integrations and business logic
- `backend/workers` for Celery workflows
- `backend/models` and `backend/migrations` for persistence
- `frontend` for the static dashboard and auth pages
- `infra` for nginx and compose-related support files

## Architecture (Phase 1: LangGraph Agents Scaffolding)

Bizard Leads is being refactored to replace n8n automation with **LangGraph agents**. Phase 1 provides:

- **`backend/app/agents/`**: New agent package with LangGraph StateGraph implementations (replacing n8n workflows).
- **Agent entrypoints**: Minimal stubs in `backend/app/agents/entrypoints.py` that are tried first, with fallback to existing Celery workers.
- **Shared agent base** (`backend/app/agents/base.py`): TypedDicts, Redis checkpointer factory, agent result wrappers.
- **LLM router** (`backend/services/llm_router.py`): Unified entry point for LLM calls (delegates to OpenAI; Groq + fallback in later phases).
- **Core utilities** (`backend/app/core/observability.py`, `backend/app/core/retry.py`): Minimal logging and retry stubs.
- **Approval routing** (`backend/app/api/routes/approvals.py`): Stubs for future human-in-the-loop outreach approval.

### Current integration workflow:

- **Lead discovery**: Google Maps scraping -> website parsing -> LinkedIn discovery (Celery fallback; LangGraph agent scaffolded)
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
- **Phase 1 (LLM router)**: `GROQ_API_KEY` (optional; uses OpenAI fallback if not set)
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
- Qdrant (Phase 2+): localhost:6333

## Testing

Run the test suite locally:

```powershell
python -m pytest -q
```

All 25 tests should pass. Tests include smoke tests, HubSpot webhook handlers, and workflow dispatch.

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

## Phase 1 Status

✅ **Done**:
- Scaffolded `backend/app/agents/` with base types, llm_router, observability, retry stubs
- Extended `backend/app/config.py` with Groq, Tavily, Qdrant, Sentry, and agent tuning settings
- Updated `.env.example` with all new variables
- Wired scheduler and webhook routes to agent entrypoints with safe fallbacks
- All existing tests pass (25 passed)

⏳ **Next** (Phases 2–11):
- Phase 2: LLM router (Groq primary, OpenAI fallback, caching)
- Phase 3: Lead Discovery agent (multi-source retrieval, Tavily signals, triangulation)
- Phase 4: Lead Scorer agent (PRIME two-pass scoring)
- Phase 5: Outreach agent (email generation, human approval gate)
- Phase 6: Qdrant RAG infrastructure
- Phase 7: Support and Reporting agents with ICP learning loop
- Phase 8–11: Testing, CI/CD, Docker, and handoff

## Production Readiness

- **LangGraph checkpointer required in production:** agents rely on LangGraph's Redis checkpointer (AsyncRedisSaver) for durable checkpoints. The application will fail-fast at startup in `production` if the checkpointer cannot be initialized. Ensure `langgraph` and `langgraph-checkpoint` are installed in production.
- **Redis required:** the agent checkpointer persists to Redis; configure `REDIS_URL` in your environment (see `.env.example`). `docker compose` now includes Redis and healthchecks.
- **Readiness probe:** the backend exposes `/ready` which verifies DB connectivity and the LangGraph checkpointer. Use this for orchestration readiness checks.
- **CI:** a GitHub Actions workflow (`.github/workflows/ci.yml`) runs the test suite with Postgres and Redis services. The `openai` dependency pin was relaxed to `openai>=1.54.0,<2.0.0` to satisfy transitive requirements from `langchain-openai`.

These changes make agent-based runs production-resilient by ensuring durable checkpoints and startup-time verification of critical dependencies.
