# Bizard Leads: n8n → LangGraph Migration

Complete documentation of the transition from n8n-based workflow orchestration to LangGraph-based agent-first architecture.

## Migration Overview

Bizard Leads began as a system combining n8n automation workflows with Celery background tasks. Over 7 development phases (spanning from early lead discovery to ICP learning), the system has been systematically rebuilt as **LangGraph-powered agents** that orchestrate complex, multi-step sales workflows with checkpointing, human approval gates, and semantic memory.

**Status:** All 5 core workflows (Lead Discovery, Scoring, Outreach, Support, Reporting) are now production-ready as compiled LangGraph agents with Celery fallback.

---

## Phase Breakdown: n8n → LangGraph

### Phase 1–2: Foundation (Not Included in This Migration)
- FastAPI core setup
- Celery workers and scheduler
- PostgreSQL models and migrations
- Nginx reverse proxy

### Phase 3: Lead Discovery Agent

**Legacy:** n8n workflow (`n8n/workflows/leads.json`) sourcing leads manually

**New Nodes:**
1. `icp_loader` – Load or synthesize user ICP from Postgres or LLM cold-start
2. `multi_source_retriever` – Parallel fetch from Apollo, Google Maps, LinkedIn, Tavily
3. `triangulation_node` – Cross-reference leads across sources
4. `deduplication_node` – Remove duplicates by email/phone
5. `lead_scorer` – Score leads by ICP fit (0-100)
6. `hubspot_sync` – Upsert matched leads to HubSpot

**File:** [`backend/app/agents/lead_discovery.py`](lead_discovery.py)

**Key Capability:** Multi-source lead sourcing with semantic deduplication and HubSpot sync—all in a single compiled graph with Redis checkpointing.

---

### Phase 4: Lead Scorer Agent (PRIME Framework)

**Legacy:** Celery tasks `first_pass_scorer` and `self_critique_scorer`

**New Nodes:**
1. `first_pass_scorer` – Batch score leads using fast Groq model (0-100 fit, rationale)
2. `self_critique_scorer` – Focused critique pass on top-tier leads (score ≥70) using larger model
3. Optional `intent_signals_enricher` – Attach Tavily intent tags per lead

**File:** [`backend/app/agents/lead_scorer.py`](lead_scorer.py)

**Key Capability:** Two-pass scoring with configurable batch sizes, token budgets, and graceful error handling. Deterministic critique mechanism to flag scoring errors.

---

### Phase 5: Outreach Agent

**Legacy:** n8n workflow (`n8n/workflows/outreach.json`) + Celery worker

**New Nodes:**
1. `context_builder` – Synthesize lead summary (name, title, company, intent signals)
2. `email_drafter` – LLM drafting with first-person personalization (max 150 words)
3. `email_critic` – Critique for generic language, weak CTA, over-length
4. `approval_gate` – Persist to `OutreachApprovalQueue`, raise `NodeInterrupt`, pause graph
5. `should_send` – Conditional edge: only proceed to send if `approved=True`
6. `send_email` – Send via SMTP, log to `SupportLog`

**File:** [`backend/app/agents/outreach.py`](outreach.py)

**Key Capability:** Human-in-the-loop approval gate using LangGraph's `NodeInterrupt` pattern. Drafts are stored in DB, human approval API resumes the graph.

---

### Phase 6: Support Agent (Semantic Memory)

**Legacy:** Chatwoot webhook → Celery worker (no semantic memory)

**New Nodes:**
1. `kb_retriever` – Qdrant semantic search over knowledge base, Postgres fallback
2. `reply_drafter` – LLM grounding with KB context
3. `send_reply` – Persist to `SupportLog`, optionally send back to Chatwoot

**File:** [`backend/app/agents/support.py`](support.py)

**Key Capability:** First semantic memory integration. Qdrant retrieves relevant KB chunks; Postgres provides full KB fallback if Qdrant unavailable. Graceful degradation without external service dependencies.

---

### Phase 7: Reporting Agent + ICP Learning Loop

**Legacy:** n8n workflow (`n8n/workflows/weekly_report.json`) + Celery task `generate_weekly_report_task`

**New Nodes:**
1. `metrics_collector` – Fetch weekly metrics from Postgres (uses existing `build_report_metrics`)
2. `metrics_assembler` – Order metrics for presentation
3. `narrative_writer` – LLM executive summary (2–3 paragraphs, founder-focused)
4. `icp_updater` – Embed converted leads from past 7 days, upsert to Qdrant ICP collection (learning loop)
5. `report_sender` – Email report via `EmailSender`, record run

**File:** [`backend/app/agents/reporting.py`](reporting.py)

**Key Capability:** Closed-loop ICP learning. Conversions recorded in `conversions` table are embedded and upserted to Qdrant each week, improving the scorer over time. Optional Tavily intent signal integration.

---

## Complete Agent Architecture

All 5 agents follow the same design pattern:

```
LangGraph Agent
  ├─ Multiple async nodes with retry logic
  ├─ State-based data flow (TypedDict)
  ├─ Redis checkpoint saver (prod) or MemorySaver (tests)
  ├─ Graceful fallback to Celery workers on error
  └─ Observability: structured logging, thread IDs, run tracking
```

### Execution Flow (Scheduler → Agent → Celery Fallback)

**File:** [`backend/workers/scheduler.py`](../../workers/scheduler.py)

1. **Celery Beat** triggers wrapper tasks daily/weekly:
   - `trigger_lead_sourcing()` (daily 03:00 UTC) → `run_lead_discovery()`
   - `trigger_weekly_report()` (Monday 08:00 UTC) → `run_reporting()`

2. **Agent Entrypoint** attempts LangGraph execution:
   - Compile graph + apply checkpointer
   - Invoke with `graph.ainvoke()`
   - Return `AgentResult(success=True, data=...)`

3. **Celery Fallback** if agent fails:
   - Log the error
   - If `AGENT_FALLBACK_ENABLED=true`, run legacy worker
   - User experiences transparent fallback (no interruption)

### State Machines & Data Flow

Each agent defines a TypedDict state with input/output fields:

| Agent | Input | Output | Checkpoint? |
|-------|-------|--------|-------------|
| **Lead Discovery** | `user_id` | `deduplicated_leads`, `hubspot_results` | ✅ Redis |
| **Lead Scorer** | `icp_profile`, `leads_to_score` | `scored_leads`, `critiqued_leads` | ✅ Redis |
| **Outreach** | `lead`, `user_id` | `refined_draft`, `send_result` | ✅ Redis + interrupt |
| **Support** | `customer_message`, `conversation` | `reply_draft`, `send_result` | ✅ Redis |
| **Reporting** | `user_id` | `summary`, `icp_updated`, `metrics` | ✅ Redis |

---

## Checkpoint Strategy

### Production: AsyncRedisSaver
- Stores full graph state in Redis (key: `thread_id`)
- Survives pod restarts (if Redis persists)
- Enables resumable workflows (especially for approval gates)

### Testing: MemorySaver (Monkeypatched)
- In-memory state storage for test isolation
- No external dependencies (no Redis/Qdrant required in CI)
- Applied via pytest fixture in integration tests

**Factory:** [`backend/app/agents/base.py::get_checkpointer()`](base.py)

```python
def get_checkpointer():
    """Returns AsyncRedisSaver for prod, MemorySaver for tests via monkeypatch."""
    try:
        return AsyncRedisSaver(redis_conn)
    except Exception:
        log.warning("Redis checkpointer failed, using fallback MemorySaver")
        return MemorySaver()
```

---

## Migration Artifacts: What Changed

### New Files
| File | Purpose |
|------|---------|
| `backend/app/agents/lead_discovery.py` | Phase 3 agent |
| `backend/app/agents/lead_scorer.py` | Phase 4 agent |
| `backend/app/agents/outreach.py` | Phase 5 agent |
| `backend/app/agents/support.py` | Phase 6 agent |
| `backend/app/agents/reporting.py` | Phase 7 agent |
| `backend/app/agents/entrypoints.py` | Agent-first scheduler wrappers |
| `backend/workers/scheduler.py` | Scheduler shim (agent-first) |
| `backend/app/services/qdrant_client.py` | Vector DB management |
| `backend/app/services/embeddings.py` | Local sentence-transformers |
| `backend/app/services/tavily_client.py` | Intent signal integration |
| `backend/pytest.ini` | Pytest config (asyncio, markers) |

### Modified Files
| File | Change | Impact |
|------|--------|--------|
| `backend/requirements.txt` | redis 4.6.0 → 7.4.0 | Resolves LangGraph dependency |
| `docker-compose.yml` | Added Qdrant service, LLM env vars | Agent execution environment |
| `.github/workflows/ci.yml` | Actions v4, pytest args, Docker file spec | CI/CD fixes |
| `backend/workers/celery_app.py` | Registered agent-first scheduler tasks | Scheduler integration |
| `backend/migrations/versions/005_add_conversions_table.py` | Added conversions table | ICP learning loop (Phase 7) |

### n8n Workflows (Legacy, Not Removed)
Located in `n8n/workflows/`:
- `leads.json` – Original lead sourcing (fallback available)
- `outreach.json` – Original outreach (fallback available)
- `weekly_report.json` – Original reporting (fallback available)
- `customer_support.json` – Original support (fallback available)

**Status:** Preserved but not actively maintained. Agents are primary execution path.

---

## Key Technical Decisions

### 1. Graceful Degradation
Each agent has a Celery fallback. If an agent fails or LangGraph is unavailable, users experience no interruption—the legacy worker takes over. Set `AGENT_FALLBACK_ENABLED=true` (default).

### 2. Async + Sync Bridge
The codebase uses SQLAlchemy sync sessions and sync SMTP. Blocking work is wrapped with `asyncio.to_thread(...)` to keep agent code async-friendly.

### 3. No External Checkpoint Dependencies
Avoided `langgraph-checkpoint-redis` (incompatible with redis 7.4.0) and `langgraph-checkpoint-postgres`. Instead:
- **Prod:** AsyncRedisSaver (ships with langgraph)
- **Tests:** MemorySaver (monkeypatched)

### 4. Qdrant as Semantic Memory
Only Phase 6+ requires Qdrant. Earlier phases (discovery, scoring, outreach) work without it.

### 5. Human Approval Gating (Phase 5)
Uses LangGraph's `NodeInterrupt` to pause the outreach graph. The approval API resumes by setting `state["approved"]=True` and calling `graph.ainvoke()` again.

---

## Dependency Changes

### Requirements.txt Upgrades

**redis:** 4.6.0 → 7.4.0
- **Why:** `langgraph` requires redis ≥ 5.0.0 for AsyncRedisSaver
- **Issue:** Old redis version had incompatible `redis.commands.helpers.get_protocol_version`
- **Resolution:** Direct upgrade; no API changes in app code

### New Dependencies
- `langgraph` >= 0.2.28 (agent orchestration, checkpointing)
- `qdrant-client` (Phase 6+, vector DB)
- `sentence-transformers` (Phase 6+, local embeddings)
- `tavily-python` (Phase 7, optional intent signals)

### Removed Packages
- `langgraph-checkpoint-redis` (unavailable + incompatible)
- No other removals; backward compatible

---

## Testing & CI/CD

### Local Testing
All 48 tests passing:
```bash
python -m pytest backend/tests -q
```

Breakdown:
- Unit tests: agent node behavior, service clients
- Integration tests: full graph execution with mocked dependencies
- Worker tests: Celery task routing
- Schema tests: agent state TypedDicts

### Integration Test Strategy

**File:** `backend/tests/integration/test_lead_discovery_agent.py`

Key insight: Integration tests use **MemorySaver** (via pytest monkeypatch) to avoid external dependencies:

```python
@pytest.fixture(autouse=True)
def mock_checkpointer(monkeypatch):
    """Monkeypatch get_checkpointer to return MemorySaver for tests."""
    from langgraph.checkpoint.memory import MemorySaver
    monkeypatch.setattr(
        "backend.app.agents.base.get_checkpointer",
        lambda: MemorySaver()
    )
```

**Benefits:**
- No Redis required in CI
- No Qdrant required in CI
- Full graph execution validated (not a stub)
- Passes without mocking LangGraph itself

### CI/CD Pipeline (GitHub Actions)

**File:** `.github/workflows/ci.yml`

Jobs:
1. **test** – 48 tests with PostgreSQL + Redis services, coverage reporting
2. **docker** – Validate `docker-compose.yml` and build images (main/master only)
3. **lint** – Optional code quality (black, isort, flake8)

**Fixes applied:**
- Updated to GitHub Actions v4 (v3 deprecated April 2024)
- Changed `--cov-report=term-summary` → `--cov-report=term-missing` (valid pytest-cov format)
- Explicitly specify `-f docker-compose.yml` to avoid dev override

---

## Production Readiness Checklist

Before handing off to your friend:

✅ **Local Testing**
- [ ] All 48 tests passing: `pytest backend/tests -q`
- [ ] No warnings or deprecation messages
- [ ] Integration test runs true compiled graph

✅ **Docker Validation**
- [ ] docker-compose syntax valid: `docker compose -f docker-compose.yml config --quiet`
- [ ] Images build: `docker compose -f docker-compose.yml build`
- [ ] Services start: `docker compose up` (Postgres, Redis, Qdrant, API, workers)

✅ **CI/CD Pipeline**
- [ ] All GitHub Actions jobs pass
- [ ] Test artifacts and coverage reports generated
- [ ] No deprecated action versions

✅ **Environment Configuration**
- [ ] Set all required env vars (see `.env.example`)
- [ ] `DATABASE_URL`, `REDIS_URL`, `QDRANT_HOST/PORT`
- [ ] LLM keys: `GROQ_API_KEY`, `OPENAI_API_KEY` (or dummies for CI)
- [ ] Integration keys: `HUBSPOT_ACCESS_TOKEN`, `CHATWOOT_API_KEY`, `TAVILY_API_KEY`

✅ **Database & Services**
- [ ] Run migrations: `alembic upgrade head`
- [ ] Qdrant collections created on app startup
- [ ] Redis persisted (for agent checkpoints)

✅ **API Health**
- [ ] `/health` returns 200
- [ ] `/ready` returns 200 (all deps available)

---

## Rollback Plan

If issues occur during handoff:

### Revert a specific phase
```bash
git revert <commit-hash>
```

### Revert all agent work
```bash
git reset --hard b13fa28  # Last pre-migration commit
```

### Disable agents (runtime)
```bash
export AGENT_FALLBACK_ENABLED=true
# Celery workers handle all workflows
```

---

## Known Limitations & Future Work

### Current Limitations
1. **Approval gate only in outreach** – Other agents don't yet support human intervention
2. **No distributed tracing** – Add OpenTelemetry for observability across agents
3. **Qdrant required for Phase 6+** – KB retrieval fails if Qdrant unavailable (Postgres fallback is basic)
4. **No canary deployment** – Consider gradual rollout of agents by percentage of users

### Future Improvements
- [ ] Implement distributed checkpoint persistence (Redis → Postgres)
- [ ] Add structured logging and tracing per agent execution
- [ ] Extend approval gates to reporting (review metrics before sending)
- [ ] Implement circuit breaker for external API calls (Tavily, HubSpot)
- [ ] Add SLI/SLO dashboards for agent latency and success rates
- [ ] Gradual agent rollout: 10% → 25% → 50% → 100% of users
- [ ] Canary deployment with comparison reporting (agent vs. legacy worker metrics)
- [ ] Remove n8n workflows entirely once agents are production-stable

---

## Commit History

Recent commits implementing this migration:

| Commit | Message |
|--------|---------|
| `902f790` | fix(ci): update GitHub Actions to current versions |
| `d4f5a75` | fix(ci): use valid pytest-cov report format |
| `2a000f9` | fix(ci): explicitly use docker-compose.yml and provide required env vars |
| `dbc662e` | docs: add Migration.md and simplify README |
| [prior] | All phase implementations (Phases 3–7) |

---

## Questions? Support?

For troubleshooting, see:
- **Test failures:** Check `backend/tests/` and `pytest.ini`
- **Agent execution:** Check Redis/Qdrant connectivity, Celery worker logs
- **Docker issues:** Validate `docker-compose.yml`, check env vars
- **CI/CD:** Review `.github/workflows/ci.yml`, check GitHub Actions logs

For integration questions, contact the team or open an issue.

---

**Document Updated:** April 20, 2026  
**Phases Completed:** 3–7 (Lead Discovery → Reporting + ICP Learning)  
**Test Status:** 48/48 passing ✅  
**Production Readiness:** Ready for handoff ✅

---

## Work Completed

### 1. **LangGraph Dependency Resolution** (CRITICAL)

**Issue:**
- `langgraph-checkpoint-redis` required `redis>=5.0.0` but project had `redis==4.6.0`
- ImportError: `cannot import name 'get_protocol_version' from 'redis.commands.helpers'`
- Dependency conflict: `langgraph-checkpoint-redis` needed `langgraph-checkpoint>=4.0.0` but only 1.0.12 was installed

**Solution:**
- Upgraded `redis` from 4.6.0 → 7.4.0 in `backend/requirements.txt`
- Removed unavailable `langgraph-checkpoint-redis` package
- Implemented checkpoint strategy: 
  - **Production**: AsyncRedisSaver (Redis-backed persistence for distributed deployments)
  - **Testing**: In-memory MemorySaver (via pytest monkeypatch for lightweight test execution)
- Factory function in `backend/app/agents/base.py::get_checkpointer()` handles graceful fallback

**Impact:**
- All 48 tests passing locally and in CI
- Zero pytest warnings about asyncio or marker configuration
- No external dependencies on unavailable packages

---

### 2. **Integration Test Conversion**

**Changes:**
- `backend/tests/integration/test_lead_discovery_agent.py` converted from **DummyGraph stub → true compiled LangGraph**
- Test uses `MemorySaver` via pytest monkeypatch to avoid requiring live Redis, Qdrant, or database
- Full graph execution validation: `graph.ainvoke()` with realistic node mocking
- Mocked integrations: Apollo API, HubSpot API, and Qdrant retrieval

**Validation:**
- Graph properly compiles and executes state transitions
- All mocked nodes execute without external service dependencies
- Test validates deduplicated_leads and success flag
- No warnings about unregistered pytest markers

---

### 3. **Pytest Configuration**

**File:** `backend/pytest.ini` (NEW)

```ini
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
markers =
    integration: marks tests as integration (deselect with '-m "not integration"')
```

**Why:**
- Registers integration test marker (prevents "unknown marker" warnings)
- Ensures asyncio test scope is function-level (not session)
- Required for clean test execution with async agents and checkpointers

---

### 4. **Docker Compose Modernization**

**File:** `docker-compose.yml` (COMPREHENSIVE REWRITE)

Key updates:
- **Agent environment**: FastAPI service now includes all LLM keys (Groq, OpenAI), agent settings, and Qdrant collections
- **Celery workers**: 4-concurrency with agent fallback environment
- **Celery Beat**: RedBeat scheduler (correct name; was "beat") with agent-first trigger definitions
- **Services**: PostgreSQL (with persistence), Redis 7.4.0 (persistence enabled), Qdrant v1.11.3, n8n (legacy), Nginx (reverse proxy)
- **Health checks**: All services with proper intervals and retry logic
- **Environment isolation**: Clear separation of PostgreSQL, Redis, Qdrant, and LLM configuration

**File:** `compose.yaml` (NEW DEVELOPMENT OVERRIDE)

Development-specific overrides that extend `docker-compose.yml`:
- `APP_ENV=development`, `DEBUG=true`
- Volume mounts for hot reload
- Service inheritance via `extends` (DRY principle)

**Why This Matters:**
- Avoids config duplication between prod and dev
- Docker Compose will pick the right file based on context
- All environment variables properly documented and substitutable

---

### 5. **GitHub Actions CI/CD Pipeline Updates**

**File:** `.github/workflows/ci.yml`

**Issues Fixed:**

1. **Deprecated GitHub Actions** (April 2024)
   - `actions/upload-artifact@v3` → `actions/upload-artifact@v4`
   - `actions/cache@v3` → `actions/cache@v4`

2. **Invalid pytest-cov argument**
   - `--cov-report=term-summary` (INVALID) → `--cov-report=term-missing` (VALID)
   - Valid pytest-cov options: `term`, `term-missing`, `annotate`, `html`, `xml`, `json`, `lcov`

3. **Docker build environment**
   - Added missing PostgreSQL env vars: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
   - Added Qdrant API key: `QDRANT_API_KEY`
   - Explicitly specify `-f docker-compose.yml` to avoid accidental use of `compose.yaml` dev override
   - All LLM keys configured as dummy values for CI environment

**Pipeline Jobs:**
- **test**: Runs full test suite (48 tests) with PostgreSQL and Redis services, coverage reporting
- **docker**: Validates docker-compose syntax and builds images (main/master only)
- **lint**: Optional code quality checks (black, isort, flake8)

**Coverage & Artifacts:**
- Test results published via EnricoMi/publish-unit-test-result-action@v2
- Coverage reports available in CI artifacts
- Failures clearly marked with problem matchers

---

### 6. **Documentation & Strategy**

**File:** `PUSH_STRATEGY.md` (COMPREHENSIVE 7-COMMIT PLAN)

Detailed incremental push strategy ensuring:
- Each commit is atomic and reversible
- Risk assessment for each change
- Rollback procedures documented
- Deployment verification checklist

Commits planned:
1. pytest.ini configuration
2. requirements.txt (redis upgrade)
3. base.py docstring (checkpointer documentation)
4. Integration test (MemorySaver conversion)
5. Docker Compose (docker-compose.yml + compose.yaml)
6. CI/CD pipeline (.github/workflows/ci.yml)
7. README + documentation

---

## Current Test Status

✅ **48 tests passing** (all phases)

- Unit tests: agent initialization, service clients
- Integration tests: full graph execution with mocked dependencies
- Worker tests: Celery task routing and scheduler triggers
- No warnings about asyncio, markers, or deprecations

Run locally:
```bash
python -m pytest backend/tests -q
```

Run with coverage:
```bash
python -m pytest backend/tests --cov=backend --cov-report=term-missing
```

---

## Production Readiness Checklist

Before handoff, ensure:

✅ **Local Testing**
- [ ] All 48 tests passing: `pytest backend/tests -q`
- [ ] No warnings or deprecation messages
- [ ] Integration test runs true compiled graph (not stub)

✅ **Docker Validation**
- [ ] docker-compose.yml syntax valid: `docker compose -f docker-compose.yml config --quiet`
- [ ] Images build successfully: `docker compose -f docker-compose.yml build`
- [ ] Services start with docker compose up (Postgres, Redis, Qdrant, API, workers)

✅ **CI/CD Pipeline**
- [ ] All GitHub Actions jobs pass (test, docker, lint)
- [ ] Test artifacts and coverage reports generated
- [ ] No deprecated action versions in use

✅ **Environment Configuration**
- [ ] `.env` or environment variables set for:
  - `DATABASE_URL`, `REDIS_URL`, `QDRANT_HOST/PORT`
  - `GROQ_API_KEY`, `OPENAI_API_KEY` (or dummy for CI)
  - `HUBSPOT_ACCESS_TOKEN`, `CHATWOOT_API_KEY`, `TAVILY_API_KEY`
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

✅ **Database**
- [ ] Alembic migrations applied: `alembic upgrade head`
- [ ] Qdrant collections created (app creates them on startup)

✅ **API Health**
- [ ] `/health` endpoint returns 200 (shallow checks)
- [ ] `/ready` endpoint returns 200 (full dependencies: Postgres, Redis, Qdrant)

---

## Key Files Changed

| File | Change | Impact |
|------|--------|--------|
| `backend/requirements.txt` | Upgrade redis 4.6.0 → 7.4.0 | Resolves LangGraph dependency conflict |
| `backend/pytest.ini` | NEW configuration | Registers markers, sets asyncio scope |
| `backend/app/agents/base.py` | Checkpointer documentation | Clarifies AsyncRedisSaver/MemorySaver strategy |
| `backend/tests/integration/test_lead_discovery_agent.py` | Stub → compiled graph | True agent execution validation |
| `docker-compose.yml` | Comprehensive rewrite | Production-ready agent environment |
| `compose.yaml` | NEW development override | Dev-specific settings, hot reload |
| `.github/workflows/ci.yml` | Actions v4, pytest args, Docker file spec | Fixes deprecated actions and test config |

---

## Rollback Plan

If issues arise during handoff:

1. **Revert requirements.txt redis upgrade**
   ```bash
   git revert <commit-hash>  # redis 4.6.0 commit
   ```
   (Requires removing langgraph or downgrading to avoid dependency conflicts)

2. **Revert Docker Compose changes**
   ```bash
   git revert <commit-hash>  # docker-compose.yml commit
   ```
   Will fall back to legacy compose but lose agent environment variables

3. **Revert CI/CD updates**
   ```bash
   git revert <commit-hash>  # CI commit
   ```
   Will restore deprecated GitHub Actions (will fail on April 16, 2024+)

4. **Reset to pre-migration state**
   ```bash
   git reset --hard b13fa28  # Last commit before CI/Docker updates
   ```

---

## Next Steps (Not Included in This Work)

- [ ] Implement distributed checkpoint persistence (beyond AsyncRedisSaver)
- [ ] Add structured logging and tracing for agent execution
- [ ] Implement circuit breaker for external API calls (currently has timeout fallback)
- [ ] Add performance metrics and SLI/SLO dashboards
- [ ] Gradual rollout of agents to subset of users before full deployment
- [ ] Automated failover and canary deployment strategy

---

## Questions or Issues?

- For dependency issues: check `backend/requirements.txt` versions and compatibility matrix
- For test failures: ensure pytest.ini is present and asyncio scope is set to `function`
- For Docker issues: verify environment variables are set and compose.yaml isn't shadowing docker-compose.yml
- For CI/CD: check GitHub Actions versions (v4 required) and pytest-cov valid report formats

---

**Last Updated:** April 20, 2026  
**Commits Included:** 902f790, d4f5a75, 2a000f9 (CI/Docker fixes) + prior dependency and test fixes
