# Bizard Leads

**Autonomous AI-powered lead discovery, scoring, and outreach platform for B2B sales teams.**

Bizard Leads automates your entire sales development workflow. Discover high-quality leads from multiple sources, intelligently score them by likelihood to convert, draft personalized outreach emails, manage customer support with AI, and measure campaign success—all powered by autonomous LangGraph agents with human approval gates and continuous learning.

---

## The Problem

Sales teams spend weeks:
- Manually sourcing leads from multiple platforms (Apollo, LinkedIn, Google, etc.)
- Scoring leads inconsistently across different criteria
- Writing repetitive outreach emails with limited personalization
- Managing support tickets without context
- Analyzing campaign metrics without actionable insights

Result: **Low reply rates, missed opportunities, operational inefficiency.**

## The Solution

Bizard Leads replaces manual workflows with an **autonomous agent-first platform** that:

1. **Discovers leads** from Apollo, Google Maps, LinkedIn, and custom sources simultaneously
2. **Scores leads intelligently** using a two-pass PRIME framework with LLM-powered critique
3. **Drafts personalized outreach** with human approval gates before sending
4. **Handles support** with semantic knowledge base retrieval and intelligent responses
5. **Learns over time** by embedding conversion data to improve future scoring

All workflows run as **compiled LangGraph agents** with Redis checkpointing, graceful fallback to Celery workers, and built-in observability.

---

## Core Capabilities

### 1. Lead Discovery (Phase 3)
- **Multi-source retrieval**: Fetch leads from Apollo, Google Maps, LinkedIn, Tavily in parallel
- **ICP-aware discovery**: Load user's Ideal Customer Profile or synthesize via LLM cold-start
- **Deduplication**: Remove duplicates by email/phone across sources
- **Lead scoring**: Evaluate fit against ICP (0-100 score)
- **HubSpot sync**: Automatically upsert qualified leads to HubSpot

### 2. Lead Scoring (Phase 4)
- **Two-pass PRIME scoring**:
  - **First pass**: Fast Groq model batch scores all leads (50 tokens per lead)
  - **Second pass**: Larger LLM critiques top-tier leads (score ≥70) for obvious errors
- **Smart critique**: Flags wrong industry, geography, seniority, irrelevant signals
- **Configurable batching**: Respects token budgets and model capacity
- **Intent signals**: Optional Tavily integration for real-time buyer intent

### 3. Outreach (Phase 5)
- **LLM-drafted emails**: Personalized, first-person cold emails (max 150 words)
- **Automated critique**: Flag generic openers, weak CTAs, over-length
- **Human approval gate**: Drafts pause in queue until sales team approves/rejects
- **Batch sending**: Approved emails sent via SMTP with logging
- **Audit trail**: Full history of drafts, critiques, approvals, and sends

### 4. Support (Phase 6)
- **Semantic KB retrieval**: Qdrant vector search over knowledge base for relevant answers
- **Postgres fallback**: Full KB text search if Qdrant unavailable
- **LLM-grounded replies**: Draft customer responses using retrieved context
- **Chatwoot integration**: Route support conversations through the agent, send replies back
- **Conversation history**: All exchanges logged for future reference

### 5. Reporting & Learning Loop (Phase 7)
- **Weekly metrics**: Leads sourced, conversion rate, outreach engagement
- **Executive summaries**: LLM-generated narratives (2–3 paragraphs, founder-focused)
- **ICP learning loop**: Embed converted leads, upsert to Qdrant for scorer improvement
- **Intent signals**: Optional Tavily intent data attached to reports and ICP profiles
- **Continuous improvement**: System learns from your conversions week-over-week

---

## Architecture

### High-Level System Design

```
┌──────────────────────────────────────────────────────────────┐
│                      User Dashboard                          │
│              (Browser: HTML/JS + API calls)                  │
└─────────────────────┬──────────────────────────────────────────┘
                      │
         ┌────────────┴────────────┬──────────────────┐
         │                         │                  │
    ┌────▼────────┐    ┌──────────▼────────┐   ┌────▼──────────┐
    │  FastAPI    │    │  Celery Workers   │   │  Celery Beat  │
    │  (REST API) │    │  (Background Jobs)│   │  (Scheduler)  │
    │             │    │                   │   │               │
    │ • Auth      │    │ • Lead Discovery  │   │ Daily triggers│
    │ • Dashboard │    │ • Scoring         │   │ • Lead source │
    │ • Approvals │    │ • Outreach        │   │ • Weekly      │
    │ • Webhooks  │    │ • Support         │   │   report      │
    │ • Reports   │    │ • Reporting       │   │               │
    └────┬────────┘    └──────────┬────────┘   └────┬──────────┘
         │                        │                 │
         │    ┌───────────────────┼─────────────────┘
         │    │                   │
    ┌────▼────▼──────────────────▼──────────┬──────────┬─────────┐
    │                                       │          │         │
 ┌──▼─────┐  ┌──────────┐  ┌──────────┐  ┌▼───────┐ ┌▼──────┐ │
 │ Postgres│  │ Redis    │  │ Qdrant   │  │  n8n   │ │Chatwoot
 │         │  │          │  │ (vectors)│  │(legacy)│ │ (support)
 │ • Users │  │ • Broker │  │          │  │        │ │
 │ • Leads │  │ • Cache  │  │ • Leads  │  │        │ │
 │ • Drafts│  │ • Checks │  │ • KB     │  │        │ │
 │ • Logs  │  │ • State  │  │ • ICP    │  │        │ │
 └─────────┘  └──────────┘  └──────────┘  └────────┘ └────────┘
```

### Execution Model

**Agent-First with Graceful Fallback:**

```
Celery Beat
    ↓
Scheduler Wrapper (agent-first decision)
    ├→ Try LangGraph Agent (primary path)
    │   └→ Compiled graph with Redis checkpoint
    │       └→ Full state persistence & resumability
    │
    └→ If agent fails, fallback to Celery Worker (reliable fallback)
        └→ Legacy task execution (backward compatible)
```

### Key Components

| Component | Purpose | Tech |
|-----------|---------|------|
| **FastAPI** | REST API, webhooks, dashboards | Python 3.12 |
| **LangGraph Agents** | AI-driven workflow orchestration | langgraph 0.2.28 |
| **Celery** | Background task queues & fallback | celery 5.3.0 |
| **PostgreSQL** | Persistent data (users, leads, drafts, logs) | 16-alpine |
| **Redis** | Agent checkpoints, Celery broker | 7.4.0 |
| **Qdrant** | Vector database for semantic search | v1.11.3 |
| **Nginx** | Reverse proxy, static file serving | Latest |
| **n8n** | Legacy workflows (fallback, being phased out) | - |

---

## How It Works

### Workflow Example: Lead Discovery to Outreach

```
1. Scheduler triggers daily at 03:00 UTC
   └→ run_lead_discovery()

2. Lead Discovery Agent:
   ├→ icp_loader: Load user's ICP or create via LLM
   ├→ multi_source_retriever: Fetch from Apollo, Google, LinkedIn, Tavily in parallel
   ├→ triangulation: Cross-reference leads across sources
   ├→ deduplication: Remove email/phone duplicates
   ├→ scoring: Score 0-100 fit against ICP
   └→ hubspot_sync: Upsert qualified leads to HubSpot
   
   └→ Checkpoint every step (resumable if interrupted)

3. Leads stored in Postgres → Dashboard shows "New leads available"

4. Sales team reviews & clicks "Create outreach"

5. Outreach Agent:
   ├→ context_builder: Summarize lead (name, title, company, signals)
   ├→ email_drafter: LLM writes personalized cold email
   ├→ email_critic: Check for generic language, weak CTA
   └→ approval_gate: PAUSE → Draft stored in DB, waits for approval
   
   └→ Human decision: API endpoint /approvals/draft_id/approve
   
   └→ Resume graph execution with approved=True
   
   ├→ send_email: SMTP sends the email
   └→ Complete: Log in Postgres

6. Weekly reporting aggregates metrics & learns from conversions
```

---

## Key Integrations

### Lead Sources
- **Apollo** – Email/phone enrichment and company search
- **Google Maps** – Local business discovery
- **LinkedIn** – Profile scraping (custom integrations)
- **Tavily** – Real-time intent signals

### Outreach & Support
- **HubSpot** – Sync leads, deals, contacts; receive webhooks
- **Chatwoot** – Route support conversations through agent, send replies back
- **SendGrid / SMTP** – Email delivery and tracking

### LLM & Inference
- **Groq** – Fast model for batching & scoring (default: llama-3.1-8b-instant)
- **OpenAI** – Larger model for critique & reasoning (default: gpt-4o-mini)
- **Built-in LLM cache** – 24-hour cache to reduce API costs

### Semantic Search
- **Qdrant** – Vector DB for lead similarity, KB retrieval, ICP profiles
- **Sentence-Transformers** – Local embeddings (no external API calls)

---

## Getting Started

### Requirements

**Minimum:**
- Python 3.12
- PostgreSQL 16+
- Redis 7.4+

**Recommended:**
- Qdrant v1.11.3+ (for semantic search)
- Groq API key (faster, cheaper LLM inference)
- OpenAI API key (larger model for critique)
- HubSpot access token
- Apollo API key
- Chatwoot instance (optional, for support)

### Local Development (5 minutes)

#### 1. Clone & Setup
```bash
git clone https://github.com/Finn-tech-art/sales_dashboard.git
cd sales_dashboard
python -m venv .venv
source .venv/Scripts/Activate.ps1  # Windows: .venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

#### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys and database URLs
```

**Required variables:**
```bash
DATABASE_URL=postgresql+psycopg://user:pass@localhost/bizard_leads
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=your-secret-key
GROQ_API_KEY=gsk_...
OPENAI_API_KEY=sk_...
HUBSPOT_ACCESS_TOKEN=pat_...
```

#### 3. Database Setup
```bash
alembic upgrade head
```

#### 4. Run Services
**Terminal 1 – API:**
```bash
python -m uvicorn backend.app.main:app --reload
```

**Terminal 2 – Workers:**
```bash
celery -A backend.workers.celery_app worker --loglevel=info
```

**Terminal 3 – Scheduler:**
```bash
celery -A backend.workers.celery_app beat --loglevel=info
```

**Access:**
- API: `http://localhost:8000`
- Dashboard: `http://localhost:3000` (served by Nginx in Docker)
- Docs: `http://localhost:8000/docs`

### Docker Compose (1 command)

```bash
docker compose up --build
```

Services started:
- FastAPI (port 8000)
- PostgreSQL (port 5432)
- Redis (port 6379)
- Qdrant (port 6333)
- Nginx (port 3000)
- Celery worker
- Celery beat
- n8n (legacy, port 5678)

**Access:**
- Dashboard: `http://localhost:3000`
- API: `http://localhost:8000`
- Qdrant UI: `http://localhost:6333/dashboard`

---

## Configuration

All settings are environment variables (see `.env.example`):

### Core
- `DATABASE_URL` – PostgreSQL connection
- `REDIS_URL` – Redis connection
- `JWT_SECRET` – Session signing key
- `APP_ENV` – development|production|test

### LLM & Agents
- `GROQ_API_KEY` – Fast model provider
- `GROQ_MODEL_FAST` – Fast model (default: llama-3.1-8b-instant)
- `GROQ_MODEL_LARGE` – Large model for critique
- `OPENAI_API_KEY` – OpenAI provider
- `OPENAI_MODEL` – Model (default: gpt-4o-mini)
- `LLM_CACHE_TTL_SECONDS` – Cache duration (default: 86400 = 1 day)
- `LLM_MAX_TOKENS_PER_NODE` – Token budget per node (default: 2000)

### Agent Behavior
- `AGENT_FALLBACK_ENABLED` – Use Celery fallback on agent error (default: true)
- `AGENT_MAX_RETRIES` – Retry attempts per node (default: 3)
- `AGENT_RETRY_BASE_DELAY` – Retry delay in seconds (default: 1.0)
- `AGENT_CIRCUIT_BREAKER_THRESHOLD` – Failures before circuit break (default: 5)

### Semantic Search (Qdrant)
- `QDRANT_HOST` – Qdrant server host
- `QDRANT_PORT` – Qdrant port (default: 6333)
- `QDRANT_API_KEY` – Qdrant API key (if auth enabled)
- `QDRANT_COLLECTION_LEADS` – Collection name for leads
- `QDRANT_COLLECTION_SUPPORT_KB` – Collection for knowledge base
- `QDRANT_COLLECTION_ICP` – Collection for ICP profiles (learning loop)

### Integrations
- `HUBSPOT_ACCESS_TOKEN` – HubSpot private app token
- `HUBSPOT_CLIENT_SECRET` – For webhook signature verification
- `CHATWOOT_API_KEY` – Chatwoot agent inbox API key
- `CHATWOOT_BASE_URL` – Chatwoot instance URL
- `TAVILY_API_KEY` – Tavily intent signals (optional)
- `APOLLO_API_KEY` – Apollo API key
- `SENDGRID_API_KEY` – SendGrid email delivery

---

## Testing

### Run All Tests
```bash
python -m pytest backend/tests -q
```

**Test Coverage:**
- 48 tests total
- API endpoint tests (auth, approvals, dashboards)
- Agent integration tests (full graph execution with mocks)
- Service tests (LLM, email, Qdrant)
- Worker and scheduler tests

### Run Specific Test
```bash
python -m pytest backend/tests/integration/test_lead_discovery_agent.py -v
```

### Run with Coverage
```bash
python -m pytest backend/tests --cov=backend --cov-report=term-missing
```

---

## Deployment

### Pre-Deployment Checklist

```bash
# 1. Test locally
python -m pytest backend/tests -q

# 2. Validate Docker setup
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml build

# 3. Run migrations
alembic upgrade head

# 4. Check API health
curl http://localhost:8000/health     # Shallow check
curl http://localhost:8000/ready      # Deep check (all deps)
```

### Production Environment

Set these in your deployment (Kubernetes secrets, Docker secrets, or env vars):

**Required:**
```yaml
DATABASE_URL: postgresql+psycopg://...
REDIS_URL: redis://...
JWT_SECRET: <random-32-char-string>
GROQ_API_KEY: gsk_...
```

**Recommended:**
```yaml
QDRANT_HOST: qdrant
QDRANT_PORT: 6333
QDRANT_API_KEY: <api-key>
HUBSPOT_ACCESS_TOKEN: pat_...
AGENT_FALLBACK_ENABLED: "true"
APP_ENV: production
```

### Kubernetes Deployment Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: bizard-leads-config
data:
  APP_ENV: production
  QDRANT_HOST: qdrant.default.svc.cluster.local
  QDRANT_PORT: "6333"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bizard-api
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: bizard-leads:latest
        envFrom:
        - configMapRef:
            name: bizard-leads-config
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: bizard-secrets
              key: database-url
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Health Checks

**Shallow health (API running):**
```bash
curl http://localhost:8000/health
# Response: {"status": "ok"}
```

**Deep readiness (all dependencies available):**
```bash
curl http://localhost:8000/ready
# Response: {"status": "ready", "database": "ok", "redis": "ok", "qdrant": "ok", "agents": "ok"}
```

---

## API Overview

### Authentication
- **POST /auth/login** – Get JWT access/refresh tokens
- **POST /auth/signup** – Register new account
- **POST /auth/refresh** – Refresh expired token

### Lead Management
- **GET /api/leads** – List leads with filters
- **POST /api/leads** – Create lead manually
- **GET /api/leads/{id}** – Get lead details
- **PUT /api/leads/{id}** – Update lead

### Outreach
- **GET /api/outreach/approvals** – List pending approval drafts
- **POST /api/outreach/approvals/{draft_id}/approve** – Approve and send
- **POST /api/outreach/approvals/{draft_id}/reject** – Reject draft
- **GET /api/outreach/sent** – List sent emails

### Support
- **POST /api/support/webhook/chatwoot** – Receive support conversations
- **GET /api/support/logs** – View support history

### Reports
- **GET /api/reports/weekly** – Get last week's metrics
- **GET /api/reports/metrics** – Get specific metrics

### Webhooks
- **POST /webhooks/hubspot** – Receive HubSpot updates
- **POST /webhooks/chatwoot** – Receive support conversations

Full API docs at `/docs` (Swagger UI) or `/redoc` (ReDoc).

---

## Troubleshooting

### Tests Failing
**Problem:** Tests fail locally  
**Solution:**
```bash
# Ensure postgres and redis are running
docker compose up postgres redis -d

# Check Python version
python --version  # Should be 3.12+

# Reinstall dependencies
pip install -r backend/requirements.txt --force-reinstall

# Run tests with verbose output
python -m pytest backend/tests -v
```

### Docker Build Fails
**Problem:** Docker image won't build  
**Solution:**
```bash
# Validate docker-compose
docker compose -f docker-compose.yml config

# Check env vars are set
cat .env | grep -E "^[A-Z_]+" | head -20

# Build with no cache
docker compose build --no-cache

# Check logs
docker compose logs api
```

### Agents Not Executing
**Problem:** Agents fail, Celery workers don't fallback  
**Solution:**
```bash
# Verify Redis is running and reachable
redis-cli ping  # Should respond "PONG"

# Check Celery worker is running
celery -A backend.workers.celery_app inspect active

# Enable fallback
export AGENT_FALLBACK_ENABLED=true

# Check logs for agent errors
tail -f /var/log/celery-worker.log
```

### Qdrant Connection Issues
**Problem:** KB retrieval fails, support agent errors  
**Solution:**
```bash
# Verify Qdrant is running
curl http://localhost:6333/health

# Check collections exist
curl http://localhost:6333/collections

# Recreate collections (app will do this on startup)
curl -X DELETE http://localhost:6333/collections/support_kb
curl -X DELETE http://localhost:6333/collections/leads
curl -X DELETE http://localhost:6333/collections/icp_profiles

# Restart API service to reinitialize collections
```

### High API Latency
**Problem:** Requests slow, agents timing out  
**Solution:**
```bash
# Check LLM provider health
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"

# Reduce LLM_MAX_TOKENS_PER_NODE if needed
export LLM_MAX_TOKENS_PER_NODE=1000

# Check Redis latency
redis-cli --latency

# Monitor Celery tasks
celery -A backend.workers.celery_app events
```

---

## For Developers

### Architecture & Phases

For a deep dive into the **n8n → LangGraph migration**, how each agent was designed, and the complete phase-by-phase breakdown, see:

📖 **[`backend/app/agents/Migration.md`](backend/app/agents/Migration.md)**

This document covers:
- All 5 phases and their nodes
- Execution model and checkpointing
- Migration artifacts and technical decisions
- Production readiness checklist
- Rollback procedures

### Codebase Structure

```
backend/
├── app/
│   ├── main.py                          # FastAPI app entry point
│   ├── config.py                        # Settings (Pydantic)
│   ├── database.py                      # SQLAlchemy setup
│   ├── agents/                          # LangGraph agent implementations
│   │   ├── base.py                      # Shared agent utilities
│   │   ├── lead_discovery.py            # Phase 3 agent
│   │   ├── lead_scorer.py               # Phase 4 agent
│   │   ├── outreach.py                  # Phase 5 agent
│   │   ├── support.py                   # Phase 6 agent
│   │   ├── reporting.py                 # Phase 7 agent
│   │   ├── entrypoints.py               # Agent-first scheduler wrappers
│   │   └── Migration.md                 # Complete migration documentation
│   ├── api/
│   │   └── routes/                      # FastAPI route handlers
│   ├── services/                        # External integrations
│   │   ├── llm_router.py                # LLM selection & caching
│   │   ├── qdrant_client.py             # Vector DB management
│   │   ├── chatwoot.py                  # Support integration
│   │   └── ...
│   └── core/                            # Security, logging, retry logic
├── models/                              # SQLAlchemy ORM models
├── schemas/                             # Pydantic request/response schemas
├── workers/                             # Celery tasks
│   ├── celery_app.py                    # Celery app definition
│   ├── scheduler.py                     # Agent-first scheduler shim
│   └── ...
├── migrations/                          # Alembic migrations
└── tests/                               # Unit & integration tests
    ├── integration/                     # Full agent test
    ├── test_agents/                     # Agent-specific tests
    └── ...

frontend/
├── dashboard.html, leads.html, ...      # Page templates
├── js/                                  # Frontend logic
└── css/                                 # Styling

infra/
├── docker/
│   └── Dockerfile
└── nginx/
    └── default.conf

n8n/
└── workflows/                           # Legacy workflows (fallback)
```

### Running Tests Locally

```bash
# All tests
python -m pytest backend/tests -q

# With coverage
python -m pytest backend/tests --cov=backend --cov-report=term-missing

# Integration test only
python -m pytest backend/tests/integration/test_lead_discovery_agent.py -v

# Watch mode (requires pytest-watch)
ptw backend/tests
```

### Adding a New Agent

1. Create new file `backend/app/agents/my_agent.py`
2. Define state TypedDict
3. Implement node functions
4. Build and compile graph
5. Add entrypoint in `entrypoints.py`
6. Register Celery fallback task in `backend/workers/my_agent.py`
7. Add tests in `backend/tests/test_agents/test_my_agent.py`

See `lead_discovery.py` for a complete example.

---

## Support & Community

### Issues & Bugs
Report issues on [GitHub Issues](https://github.com/Finn-tech-art/sales_dashboard/issues).

### Documentation
- **Product README:** This file
- **Migration & Architecture:** [Migration.md](backend/app/agents/Migration.md)
- **API Docs:** Available at `/docs` when running locally
- **Database Models:** See `backend/models/`
- **Environment Config:** See `.env.example`

### Contributing
Contributions welcome! Please:
1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for new features
4. Ensure all tests pass (`pytest backend/tests -q`)
5. Submit a pull request

---

## License

See [LICENSE](LICENSE) file.

---

## FAQ

**Q: Can I use Bizard without Qdrant?**  
A: Yes. Phases 1–5 work without Qdrant. Phase 6 (Support) falls back to Postgres full-text search if Qdrant is unavailable.

**Q: What if an agent fails?**  
A: If `AGENT_FALLBACK_ENABLED=true` (default), Celery workers automatically handle the workflow. Users experience no interruption.

**Q: Can I customize the LLM models?**  
A: Yes. Set `GROQ_MODEL_FAST`, `GROQ_MODEL_LARGE`, `OPENAI_MODEL` in your environment.

**Q: How much does it cost to run?**  
A: Primarily LLM API costs. Groq is ~10x cheaper than OpenAI. Cache reduces calls by 50%+. Infrastructure costs depend on your cloud provider.

**Q: Can I remove n8n?**  
A: Yes, once you're confident in the agents. n8n is still present as a fallback but can be removed from `docker-compose.yml` and not deployed.

**Q: How long to set up?**  
A: 5 minutes with Docker Compose, 15 minutes local dev with database setup.

---

**Last Updated:** April 20, 2026  
**Status:** Production-ready ✅  
**Test Coverage:** 48/48 tests passing ✅  
**Agent Phases:** 5/5 implemented (Lead Discovery, Scoring, Outreach, Support, Reporting) ✅

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
