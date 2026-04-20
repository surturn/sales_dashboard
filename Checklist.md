# Bizard Leads — Checklist



Last updated: April 20, 2026 | All 48 tests passing | Production-ready

---

## Quick Start (5 minutes)

```bash
# 1. Clone and setup
git clone https://github.com/Finn-tech-art/sales_dashboard.git
cd sales_dashboard

# 2. Install dependencies
pip install -r backend/requirements.txt
python -m pytest backend/tests -q  # Run 48 tests

# 3. Start via Docker Compose (production config)
docker compose -f docker-compose.yml up --build

# 4. Or start via compose.yaml (development with hot reload)
docker compose up --build
```

Local API: `http://localhost:8000`  
Frontend: `http://localhost/` (via nginx)

---

## Architecture Overview

**Bizard Leads** is an AI-powered lead discovery and outreach automation platform built as a **layered monolith** with LangGraph agents orchestrating complex workflows.

### Core Stack
- **Backend:** FastAPI 0.109.0 + SQLAlchemy ORM
- **Agents:** LangGraph 0.2.28 (StateGraph-based with checkpointing)
- **LLM:** OpenAI (critique/reasoning) + Groq (fast/cheap tasks)
- **Data:** PostgreSQL 16 (persistence) + Redis 7.4.0 (Celery + agent checkpoints)
- **Vector DB:** Qdrant v1.11.3 (semantic memory for leads, support KB, ICP profiles)
- **Background Tasks:** Celery 5.3.0 + RedBeat scheduler (agent-first with fallback)
- **Reverse Proxy:** Nginx 1.27

### Key Agents (Phase 3-7)
1. **Lead Discovery** (Phase 3): Multi-source retrieval, PRIME scoring, HubSpot sync
2. **Lead Scorer** (Phase 4): Two-pass scoring with OpenAI critique
3. **Outreach** (Phase 5): LLM drafting, OpenAI critique, approval queues
4. **Support** (Phase 6): Qdrant KB retrieval, semantic memory
5. **Reporting** (Phase 7): Metrics, narrative, ICP learning loop

---

## Critical Configuration

### Environment Variables (`.env` file)
```env
# Database & Cache
POSTGRES_URL=postgresql://user:pass@postgres:5432/bizard_leads
REDIS_URL=redis://redis:6379/0

# LLM Providers
OPENAI_API_KEY=sk-...          # Required for critique tasks
GROQ_API_KEY=gsk-...           # Required for fast tasks
OPENAI_MODEL=gpt-4o-mini       # Critique model (better reasoning)
GROQ_MODEL_FAST=llama-3.1-8b-instant
GROQ_MODEL_LARGE=llama-3.1-70b-versatile

# External Integrations
APOLLO_API_KEY=...
HUBSPOT_API_KEY=...
SENDGRID_API_KEY=...
CHATWOOT_API_KEY=...

# Auth & Security
JWT_SECRET=<generate-secure-random-string>

# Qdrant Vector DB
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=<generate-secure-random-string>

# Environment
APP_ENV=development  # or 'production'
DEBUG=false
```

### LLM Routing Strategy
**File:** `backend/services/llm_router.py`

- **Critique tasks** (`score_critic`, `email_critique`) → OpenAI **first** (better reasoning), fallback to Groq
- **Fast tasks** (`score_fast`, `email_draft`, etc.) → Groq **first** (cheap/fast), fallback to OpenAI

This balances cost (Groq for bulk operations) with quality (OpenAI for reasoning).

---

## Testing & Validation

### Run All Tests
```bash
python -m pytest backend/tests -q
# Expected: 48 passed in ~25 minutes
```

### Run Specific Test Suite
```bash
python -m pytest backend/tests/test_agents/test_lead_discovery_agent.py -v
python -m pytest backend/tests/test_services/test_approvals_api.py -v
```

### Test Coverage
-  **48 tests** covering API routes, agents, services, workers, webhooks
-  **Agent checkpointer:** MemorySaver in tests, AsyncRedisSaver in production
-  **Async/await:** pytest configured with `asyncio_mode = auto`
-  **CI/CD:** GitHub Actions validates on every push (PostgreSQL + Redis services included)

---

## Deployment Checklist

### Before Production
- [ ] Set `APP_ENV=production` in `.env`
- [ ] Generate strong `JWT_SECRET` and `QDRANT_API_KEY`
- [ ] Provision PostgreSQL 16 (managed DB or self-hosted)
- [ ] Provision Redis 7.4.0+ (for Celery + agent checkpoints)
- [ ] Provision Qdrant v1.11.3+ (for semantic memory)
- [ ] Configure HubSpot, Apollo, SendGrid, Chatwoot API keys
- [ ] Set up HTTPS/TLS for nginx (see `infra/nginx/default.conf`)
- [ ] Configure webhook secret for HubSpot signature verification
- [ ] Set up log aggregation (Sentry, DataDog, or similar)
- [ ] Run health checks: `GET /health` (shallow) and `GET /ready` (deep)

### Docker Compose Production
```bash
# Use production config (explicit file specification)
docker compose -f docker-compose.yml up -d --build

# Or Kubernetes (example)
kubectl apply -f infra/k8s/  # Create these manifests
```

### Kubernetes Example
See `infra/k8s/deployment.yaml` for sample manifests (to be created based on your hosting platform).

---

## API Overview

### Authentication
```bash
POST /auth/signup          # Register new user
POST /auth/login           # Login (returns access + refresh tokens)
POST /auth/refresh         # Refresh access token
```

### Dashboard & Leads
```bash
GET  /dashboard            # Metrics cards, charts
GET  /leads                # Lead list with filters
POST /leads/{id}/approve   # Approve lead for outreach
```

### Outreach
```bash
GET  /outreach             # Pending outreach tasks
POST /outreach/{id}/send   # Send email (triggers agent)
```

### Reports
```bash
GET  /reports/weekly       # Weekly summary (generated by agent)
GET  /reports/icp          # ICP learning metrics
```

### Webhooks
```bash
POST /webhook/hubspot      # HubSpot CRM sync webhook
POST /webhook/chatwoot     # Chatwoot support webhook
```

---

## Troubleshooting

### Agent Checkpointer Unavailable
If you see `agent_checkpointer_unavailable` in startup logs:
1. Verify Redis is running: `redis-cli ping` → should return `PONG`
2. Check `REDIS_URL` in `.env` is correct
3. Ensure `redis` version is ≥ 7.4.0 (required for LangGraph checkpointing)

### Tests Hang or Timeout
- Tests use `asyncio_mode = auto` (pytest.ini configured)
- Full suite takes ~25 minutes (48 tests with async database operations)
- If hanging: kill the process and check for stuck Redis/PostgreSQL connections

### LLM Provider Failures
- If OpenAI fails for critique tasks, system falls back to Groq automatically
- If Groq fails for fast tasks, system falls back to OpenAI
- Check API keys in `.env`: `OPENAI_API_KEY` and `GROQ_API_KEY` must be valid
- Monitor logs for `llm_openai_success`, `llm_groq_success`, or `llm_all_providers_failed`

### Docker Build Issues
```bash
# Explicit production config (avoids dev overrides)
docker compose -f docker-compose.yml build

# If services not starting
docker compose logs -f api        # Check FastAPI logs
docker compose logs -f celery-worker  # Check Celery worker
```

---

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app entrypoint, lifespan hooks |
| `backend/app/config.py` | Pydantic settings (environment variables) |
| `backend/app/agents/` | LangGraph agent implementations (lead_discovery.py, lead_scorer.py, outreach.py, support.py, reporting.py) |
| `backend/services/llm_router.py` | LLM provider routing (OpenAI for critique, Groq for speed) |
| `backend/workers/scheduler.py` | Agent-first scheduler (tries agents first, falls back to Celery) |
| `backend/models/` | SQLAlchemy ORM models (User, Lead, OutreachLog, etc.) |
| `backend/api/routes/` | FastAPI routers (auth, dashboard, leads, outreach, reports, webhooks) |
| `frontend/` | Static HTML/JS (served by nginx) |
| `docker-compose.yml` | Production services (api, postgres, redis, qdrant, celery, nginx) |
| `compose.yaml` | Development override (hot reload, debug mode) |
| `infra/nginx/` | Nginx reverse proxy config |
| `backend/app/agents/Migration.md` | Complete n8n → LangGraph migration documentation |

---

## Recent Changes (This Handover)

 **Completed Tasks:**

1. **Fixed pytest-cov argument** (term-summary → term-missing)
2. **Updated GitHub Actions to v4** (deprecated v3 sunset)
3. **Fixed Docker Compose configuration** (explicit `-f docker-compose.yml`, env vars)
4. **Upgraded Redis** 4.6.0 → 7.4.0 (langgraph-checkpoint-redis requirement)
5. **Created comprehensive Migration.md** (n8n → LangGraph documentation)
6. **Rewrote README.md** (product-focused, not technical)
7. **Removed n8n completely:**
   - Deleted `N8N_WEBHOOK_BASE` from config.py and .env files
   - Deleted n8n Docker service from docker-compose.yml
   - Deleted n8n service extends from compose.yaml
   - System is now 100% agent-based
8. **Fixed LLM routing for critique tasks:**
   - Implemented `TASK_PROVIDER_MAP` with provider-aware dispatch
   - Critique tasks now route to **OpenAI first** (gpt-4o-mini) for better reasoning
   - Fast tasks route to **Groq first** for cost efficiency
9. **All 48 tests passing** ✅

---


**Welcome to Bizard Leads!** This is a sophisticated AI sales platform with the following strengths:

1. **Agent-first architecture:** LangGraph agents handle all workflows, not n8n
2. **Smart LLM routing:** OpenAI for reasoning, Groq for speed
3. **Robust checkpointing:** Agents resume from checkpoints if interrupted
4. **Full test coverage:** 48 tests ensure reliability
5. **Production-ready:** Docker Compose config handles all infrastructure

**Next steps :**

1. Read [README.md](README.md) for product overview
2. Read [backend/app/agents/Migration.md](backend/app/agents/Migration.md) for architecture deep-dive
3. Set up `.env` with API keys (see "Critical Configuration" section above)
4. Run `python -m pytest backend/tests -q` to validate setup
5. Start development with `docker compose up --build`

**Questions?** Check:
- README.md for product/deployment overview
- Migration.md for agent architecture
- API docstrings in `backend/app/api/routes/`
- Test files in `backend/tests/` for usage examples

---

**Status:**  Production-ready | All tests passing | n8n completely removed | LLM routing optimized


