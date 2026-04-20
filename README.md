# Bizard Leads

**An AI-powered platform for automated lead discovery, qualification, and outreach.**

Bizard Leads enables B2B sales teams to build and manage pipeline at scale. Using autonomous AI agents, the platform discovers high-intent leads, intelligently qualifies them, and manages outreach—all while learning from conversion data to continuously improve targeting and messaging.

## Overview

Sales teams rely on manual processes to fill pipeline. Finding qualified leads requires research across multiple platforms. Scoring and prioritization is inconsistent. Outreach is personalized at scale only through repetitive templates. Managing follow-ups and customer inquiries is reactive and time-consuming.

Bizard Leads automates this entire workflow with a system of intelligent agents that operate autonomously while maintaining human control through approval gates and transparent decision-making.

### Key Features

- **Lead Discovery**: Multi-source lead retrieval from Apollo, Google Maps, LinkedIn, and custom databases
- **Intelligent Qualification**: Two-pass scoring using LLM-powered critique to evaluate fit
- **Personalized Outreach**: LLM-drafted emails with human approval before sending
- **Knowledge Management**: Semantic search across support documentation and past interactions
- **Continuous Learning**: ICP refinement based on conversion data and intent signals
- **Full Audit Trail**: Complete record of sourcing, scoring, outreach, and responses

---

## System Architecture

Bizard Leads is built as a modern, scalable backend system with an autonomous agent-first architecture.

### Core Components

**API Server (FastAPI)**
- RESTful endpoints for dashboard, approvals, and webhooks
- JWT authentication with access/refresh token support
- Integrations with HubSpot, Chatwoot, and external APIs

**Agent Orchestration (LangGraph)**
- Stateful agent workflows with Redis checkpointing
- Graceful fallback to traditional Celery workers
- Built-in error recovery and retry logic

**Data Layer**
- PostgreSQL for persistent data (leads, users, interactions)
- Redis for task queue, caching, and agent state
- Qdrant for vector-based semantic search

**Background Processing**
- Celery workers for long-running operations
- RedBeat scheduler for recurring jobs
- Agent-first execution with automatic fallback

### Architecture Diagram

```
┌─────────────────────────────────────┐
│     User Interface                  │
│    (Dashboard + API Clients)        │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────────────┬────────────────┐
        │                     │                │
   ┌────▼──────┐   ┌─────────▼───────┐  ┌───▼────────┐
   │  FastAPI  │   │  LangGraph      │  │  Celery    │
   │  REST API │   │  Agents         │  │  Workers   │
   │           │   │                 │  │            │
   │ Routes &  │   │ • Discovery     │  │ • Legacy   │
   │ Auth      │   │ • Scoring       │  │   tasks    │
   │           │   │ • Outreach      │  │            │
   │           │   │ • Support       │  │            │
   │           │   │ • Reporting     │  │            │
   └────┬──────┘   └──────┬──────────┘  └────┬───────┘
        │                 │                   │
        └─────────────────┼───────────────────┘
                          │
         ┌────────────────┼──────────────────┬────────┐
         │                │                  │        │
    ┌────▼─────┐  ┌──────▼──────┐  ┌───────▼──┐  ┌──▼──────┐
    │PostgreSQL│  │Redis Broker │  │Qdrant    │  │Nginx    │
    │(Data)    │  │(State)      │  │(Vectors) │  │(Proxy)  │
    └──────────┘  └─────────────┘  └──────────┘  └─────────┘
```

---

## Getting Started

### Installation

**Prerequisites**
- Python 3.12+
- Docker & Docker Compose (recommended for full stack)
- PostgreSQL 16, Redis 7.4+, Qdrant v1.11+

**Development Setup (5 minutes)**

```bash
# 1. Clone repository
git clone https://github.com/Finn-tech-art/sales_dashboard.git
cd sales_dashboard

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Run tests
python -m pytest backend/tests -q
# Expected: 48 passed

# 5. Start development environment
docker compose up --build
```

Access the application at `http://localhost` (API at `http://localhost:8000`).

### Docker Deployment

```bash
# Production configuration
docker compose -f docker-compose.yml up -d --build

# Development with hot reload
docker compose up --build
```

---

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```env
# Database
POSTGRES_URL=postgresql://user:password@localhost:5432/bizard_leads
REDIS_URL=redis://localhost:6379/0

# LLM Providers
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk-...
OPENAI_MODEL=gpt-4o-mini
GROQ_MODEL_FAST=llama-3.1-8b-instant

# External Integrations
APOLLO_API_KEY=...
HUBSPOT_API_KEY=...
SENDGRID_API_KEY=...
CHATWOOT_API_KEY=...

# Security
JWT_SECRET=<generate-secure-random>
QDRANT_API_KEY=<generate-secure-random>

# Environment
APP_ENV=development
DEBUG=false
```

### LLM Provider Strategy

The platform intelligently routes tasks to different LLM providers:

- **OpenAI (gpt-4o-mini)**: Critique tasks, reasoning, complex evaluations
- **Groq (llama-3.1)**: Fast tasks, bulk operations, drafting

This approach optimizes for both cost and quality—using expensive models only where reasoning matters most.

---

## API Reference

### Authentication

```bash
POST /auth/signup
POST /auth/login                # Returns access + refresh tokens
POST /auth/refresh              # Refresh access token
```

### Dashboard

```bash
GET  /dashboard                 # Metrics and summary cards
GET  /health                    # Shallow health check
GET  /ready                     # Deep health check
```

### Leads

```bash
GET  /leads                     # List leads with filters
GET  /leads/{id}                # Get lead details
POST /leads/{id}/approve        # Approve lead for outreach
```

### Outreach

```bash
GET  /outreach                  # Pending outreach tasks
POST /outreach/{id}/send        # Send approved email
GET  /outreach/{id}/history     # View email history
```

### Reports

```bash
GET  /reports/weekly            # Weekly summary
GET  /reports/icp               # ICP metrics
```

### Webhooks

```bash
POST /webhook/hubspot           # HubSpot CRM sync
POST /webhook/chatwoot          # Customer support
```

---

## Testing

The platform includes comprehensive test coverage across all components.

```bash
# Run all tests
python -m pytest backend/tests -q

# Run specific test suite
python -m pytest backend/tests/test_agents -v
python -m pytest backend/tests/test_services -v

# Run with coverage
python -m pytest backend/tests --cov=backend --cov-report=html
```

**Test Results**: 48 tests covering agents, APIs, services, workers, and integrations.

---

## Deployment

### Pre-Deployment Checklist

- [ ] Set `APP_ENV=production`
- [ ] Generate strong `JWT_SECRET` and `QDRANT_API_KEY`
- [ ] Provision managed PostgreSQL 16
- [ ] Provision managed Redis 7.4+
- [ ] Provision Qdrant instance
- [ ] Configure all API keys (OpenAI, Groq, HubSpot, etc.)
- [ ] Set up TLS/HTTPS in Nginx
- [ ] Configure HubSpot webhook secret
- [ ] Enable log aggregation (Sentry/DataDog)

### Production Configuration

```bash
# Validate configuration
docker compose -f docker-compose.yml config --quiet

# Start services
docker compose -f docker-compose.yml up -d

# Verify health
curl http://localhost:8000/ready
```

### Kubernetes (Example)

```bash
kubectl apply -f infra/k8s/
kubectl rollout status deployment/api
```

---

## Monitoring & Observability

### Health Checks

**Shallow Health Check** (API responsive)
```bash
GET /health
```

**Deep Health Check** (All dependencies available)
```bash
GET /ready
```

### Logging

All components emit structured logs:
- **Agent execution**: `llm_groq_success`, `llm_openai_fallback_success`
- **Lead processing**: `lead_sourced`, `lead_scored`, `lead_sent`
- **Errors**: `agent_checkpointer_unavailable`, `llm_all_providers_failed`

### Metrics

Monitor via your logging/observability platform:
- Lead sourcing rate (leads/day)
- Conversion rate (conversions/leads)
- Outreach engagement (open rate, reply rate)
- System latency (agent execution time)

---

## Support & Troubleshooting

### Common Issues

**Agent Checkpointer Unavailable**
- Verify Redis is running: `redis-cli ping`
- Check `REDIS_URL` is correct in `.env`
- Ensure Redis version ≥ 7.4.0

**LLM Provider Failures**
- Verify API keys are valid
- Check rate limits on external services
- Inspect logs for specific error messages

**Docker Build Failures**
```bash
# Use explicit production config
docker compose -f docker-compose.yml build --no-cache

# Check service logs
docker compose logs api
docker compose logs celery-worker
```

---

## Technical Details

### Project Structure

```
backend/
├── app/                          # FastAPI application
│   ├── main.py                   # App entrypoint
│   ├── config.py                 # Settings management
│   ├── agents/                   # LangGraph agents
│   ├── api/routes/               # REST endpoints
│   ├── services/                 # Business logic
│   └── core/                     # Authentication, logging
├── models/                        # SQLAlchemy ORM
├── workers/                       # Celery tasks
└── tests/                         # Test suite (48 tests)

frontend/
├── dashboard.html                # Main dashboard
├── components/                   # UI components
├── js/                          # JavaScript
└── css/                         # Stylesheets

infra/
├── docker/                      # Docker config
├── nginx/                       # Reverse proxy
└── k8s/                        # Kubernetes (optional)
```

### Key Technologies

| Component | Technology | Version |
|-----------|-----------|---------|
| Web Framework | FastAPI | 0.109.0 |
| Agent Orchestration | LangGraph | 0.2.28 |
| Task Queue | Celery | 5.3.0 |
| Database | PostgreSQL | 16-alpine |
| Cache & Broker | Redis | 7.4.0 |
| Vector DB | Qdrant | v1.11.3 |
| Web Server | Nginx | 1.27-alpine |
| Runtime | Python | 3.12 |

---

## Contributing

This is a production system. Changes should be:

1. Tested: `python -m pytest backend/tests`
2. Validated: `docker compose -f docker-compose.yml config --quiet`
3. Committed with clear message
4. Pushed to main branch

---

## License

Proprietary. All rights reserved.

---

## Additional Resources

- **Architecture Deep-Dive**: See `backend/app/agents/Migration.md`
- **Deployment Guide**: See `HANDOVER_CHECKLIST.md`
- **API Documentation**: Built-in at `/docs` (Swagger UI)
- **OpenAPI Schema**: Available at `/openapi.json`

---

**Version**: 2.0 (Agent-First Architecture)  
**Last Updated**: April 20, 2026  
**Status**: Production Ready
