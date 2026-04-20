# Bizard Leads

**AI-powered outreach automation for B2B sales teams.**

Bizard Leads is a platform that discovers leads, scores them by likelihood to convert, drafts personalized outreach, and measures campaign success—all powered by autonomous AI agents.

## What It Does

- **Lead Discovery**: Automatically source leads from Apollo, HubSpot, and custom data sources
- **Lead Scoring**: AI-powered two-pass scoring with smart critique to identify high-intent prospects
- **Outreach**: LLM-drafted, critique-reviewed, approval-gated personalized emails at scale
- **Support**: AI agent resolves customer inquiries with semantic search over your knowledge base
- **Reporting**: Weekly insights with ICP learning loop—the system improves scoring based on actual conversions
- **Integrations**: HubSpot, Chatwoot, SendGrid, Apollo, OpenAI/Groq, Tavily (intent signals)

## Quick Start

### Requirements

- Python 3.12
- PostgreSQL 16
- Redis 7.4
- (Optional) Qdrant for vector search, OpenAI/Groq for LLMs

### Local Development

```bash
# Clone and setup
git clone <repo>
cd sales_dashboard
python -m venv .venv
source .venv/Scripts/Activate.ps1  # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt

# Database
alembic upgrade head

# Run API
python -m uvicorn backend.app.main:app --reload

# In another terminal: workers
celery -A backend.workers.celery_app worker --loglevel=info
celery -A backend.workers.celery_app beat --loglevel=info
```

Navigate to `http://localhost:3000` (frontend served via Nginx in Docker, or static files in dev).

### Docker Compose

```bash
docker compose up --build
```

Services:
- FastAPI (port 8000)
- Celery workers + scheduler
- PostgreSQL
- Redis
- Qdrant (vector search)
- Nginx (reverse proxy, port 3000)

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

**Required:**
- `DATABASE_URL` – PostgreSQL connection string
- `REDIS_URL` – Redis connection string
- `JWT_SECRET` – Session signing key
- `OPENAI_API_KEY` or `GROQ_API_KEY` – LLM provider

**Integrations:**
- `HUBSPOT_ACCESS_TOKEN` – HubSpot sync
- `CHATWOOT_API_KEY` – Customer support agent
- `TAVILY_API_KEY` – Intent signal discovery (optional)

**Qdrant (semantic search):**
- `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_API_KEY`

See `.env.example` for full list.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                   (Static HTML/JS)                           │
└───────────────┬───────────────────────────────────────────────┘
                │
    ┌───────────┴──────────┬─────────────────┐
    │                      │                 │
┌───▼──────────┐  ┌────────▼────────┐  ┌───▼──────────┐
│   FastAPI    │  │  Celery Workers │  │  Celery Beat │
│              │  │                 │  │  (Scheduler) │
│  • Auth      │  │ • Lead sourcing │  │              │
│  • Dashboard │  │ • Scoring       │  │ Daily/weekly │
│  • Webhooks  │  │ • Outreach      │  │ triggers     │
│  • Approvals │  │ • Support       │  │              │
│  • Reporting │  │ • Reporting     │  │              │
└───┬──────────┘  └────────┬────────┘  └────┬─────────┘
    │                      │                 │
    │         ┌────────────┼─────────────────┘
    │         │            │
    │  ┌──────▼────────┬───▼──────┬──────────┬─────────┐
    │  │  PostgreSQL   │  Redis   │  Qdrant  │   n8n   │
    │  │               │          │ (vectors)│ (legacy)│
    │  │ • Users       │ • Broker │          │         │
    │  │ • Leads       │ • Cache  │ • Leads  │         │
    │  │ • Conversions │          │ • KB     │         │
    └──▼───────────────┴──────────┴──────────┴─────────┘
```

**Execution Model:**
- **Primary**: LangGraph agents (AI-driven workflows with checkpointing)
- **Fallback**: Celery workers (reliable background task queues)
- All agents have graceful fallback to Celery when unavailable

## Testing

Run the test suite:

```bash
python -m pytest backend/tests -q
```

48 tests covering:
- API endpoints
- Agent workflows
- Service integrations
- Worker behavior

## CI/CD

GitHub Actions pipeline (`.github/workflows/ci.yml`):
- **test**: 48 tests against PostgreSQL + Redis
- **docker**: Validate and build images (main/master only)
- **lint**: Code quality checks (optional)

## For Developers

For a deep dive into the agent-first architecture, migration work, and deployment checklist, see [`backend/app/agents/Migration.md`](backend/app/agents/Migration.md).

### Key Directories

```
backend/
  app/
    agents/          # LangGraph workflows (lead discovery, scoring, outreach, support, reporting)
    api/             # FastAPI route handlers
    services/        # External integrations (HubSpot, Chatwoot, OpenAI, etc.)
    models/          # SQLAlchemy ORM models
    schemas/         # Pydantic request/response schemas
  workers/           # Celery tasks and scheduler
  migrations/        # Alembic database migrations
  tests/             # Unit and integration tests

frontend/
  dashboard.html, leads.html, outreach.html, reports.html, ...
  js/                # Frontend logic
  css/               # Styling

infra/
  docker/            # Dockerfile
  nginx/             # Reverse proxy config

n8n/
  workflows/         # Legacy automation workflows (being replaced by agents)
```

## Health & Readiness

- `/health` – Shallow health check (API is running)
- `/ready` – Deep readiness check (database, Redis, Qdrant, agents available)

## Deployment

Before deploying:

```bash
# Test locally
python -m pytest backend/tests -q

# Validate docker-compose
docker compose -f docker-compose.yml config --quiet

# Run migrations
alembic upgrade head

# Start services
docker compose up -d
```

Verify:
```bash
curl http://localhost:3000/api/health
curl http://localhost:3000/api/ready
```

## Support & Troubleshooting

### Tests failing?
- Ensure PostgreSQL and Redis are running: `docker compose up postgres redis -d`
- Check Python version: `python --version` (should be 3.12+)
- See [`backend/app/agents/Migration.md`](backend/app/agents/Migration.md) for known issues

### Docker build failing?
- Verify `.env` variables are set
- Check `docker compose -f docker-compose.yml config` for validation errors
- See migration docs for environment variable requirements

### Agents not executing?
- Verify Redis is reachable (`REDIS_URL` set correctly)
- Check Celery workers are running: `celery -A backend.workers.celery_app inspect active`
- Set `AGENT_FALLBACK_ENABLED=true` to allow Celery fallback

## License

See LICENSE file.

---

**Last Updated:** April 20, 2026

For technical implementation details and migration notes, see [`backend/app/agents/Migration.md`](backend/app/agents/Migration.md).
