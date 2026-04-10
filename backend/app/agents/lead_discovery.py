"""Lead Discovery agent (Phase 3 initial nodes).

Provides a simple StateGraph-style runner and the `icp_loader` node
which loads a user's ICP from Postgres or synthesizes a default via
an LLM cold-start. Checkpointing uses the LangGraph Redis saver when
available and falls back to a raw Redis key.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import logging
from typing import TypedDict, Optional, List

from sqlalchemy import text
import redis.asyncio as aioredis
import importlib
import inspect

from backend.app.config import get_settings
from backend.app.core.observability import get_logger
from backend.app.core.retry import with_retry
from backend.app.database import session_scope
from backend.services.llm_router import call_llm
from backend.app.agents.base import LeadRecord, get_checkpointer
from backend.domains.leads.services.lead_service import create_workflow_run

settings = get_settings()
log = get_logger("lead_discovery")


class LeadDiscoveryState(TypedDict):
    user_id: str
    icp_profile: Optional[dict]
    raw_google_leads: Optional[List[dict]]
    raw_linkedin_leads: Optional[List[dict]]
    raw_apollo_leads: Optional[List[dict]]
    tavily_signals: Optional[List[dict]]
    triangulated_leads: Optional[List[LeadRecord]]
    deduplicated_leads: Optional[List[LeadRecord]]
    hubspot_results: Optional[List[dict]]
    errors: Optional[List[str]]
    run_id: Optional[str]


@with_retry(service="icp_loader")
async def _icp_load_impl(user_id: str) -> dict:
    """Internal implementation that is retried on transient failures.

    Blocking DB access is executed via `asyncio.to_thread(...)` so the
    wrapper remains fully async-friendly.
    """

    def _fetch_from_db(uid: str):
        with session_scope() as db:
            row = db.execute(
                text("SELECT icp_config FROM user_icp_config WHERE user_id = :uid"),
                {"uid": uid},
            ).fetchone()
            if row and row[0]:
                return {"icp": row[0], "description": None}

            # Fallback: use business_description from users table
            user_row = db.execute(
                text("SELECT business_description FROM users WHERE id = :uid"),
                {"uid": uid},
            ).fetchone()
            description = user_row[0] if user_row else "small business"
            return {"icp": None, "description": description}

    res = await asyncio.to_thread(_fetch_from_db, str(user_id))

    if res.get("icp"):
        return res["icp"]

    # No ICP found — perform Cold Start via LLM
    description = res.get("description") or "small business"
    cold_start_prompt = (
        f"A professional describes their business as: {description}\n"
        "Reason from first principles about: which industry their ideal customers "
        "are in, geography, company size (1-10, 10-50, 50-200, 200+), seniority "
        "(owner/director/manager), and 3 search keywords. "
        "Return ONLY valid JSON with keys: industry, location, company_size, "
        "seniority, keywords (list), exclude_keywords (list)."
    )

    llm_resp = await call_llm(cold_start_prompt, task="icp_analysis")
    icp = json.loads(llm_resp.strip())
    return icp


async def icp_loader(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Public node used by the graph.

    On persistent failures we return a safe default ICP and append an
    error to the state's `errors` list so downstream nodes can continue.
    """
    try:
        icp = await _icp_load_impl(state["user_id"])
        return {**state, "icp_profile": icp}
    except Exception as exc:
        log.error("icp_loader_failed", error=str(exc))
        default_icp = {
            "industry": "all",
            "location": "global",
            "company_size": "any",
            "seniority": "owner",
            "keywords": [],
            "exclude_keywords": [],
        }
        errors = list(state.get("errors") or []) + [f"icp_loader: {str(exc)}"]
        return {**state, "icp_profile": default_icp, "errors": errors}


# --- Node: multi_source_retriever -------------------------------------------
@with_retry(max_attempts=2)
async def multi_source_retriever(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Run Apollo, Google Maps, LinkedIn and Tavily in parallel.

    Each source is called in a best-effort way. If a source or import is
    unavailable we return an empty list for that source and record the
    exception in `state['errors']`.
    """
    icp = state.get("icp_profile") or {}

    # Build a simple query from ICP keywords for services that expect a text query
    keywords = []
    if isinstance(icp, dict):
        keywords = icp.get("keywords") or []
    query = " ".join(keywords) if keywords else settings.DEFAULT_LEAD_QUERY

    async def _call_apollo():
        # Try several likely import paths and function names
        candidates = [
            ("backend.app.services.apollo", ["search_leads", "apollo_search", "search"]),
            ("backend.services.apollo", ["search_leads", "apollo_search", "search"]),
        ]
        for mod_path, names in candidates:
            try:
                mod = importlib.import_module(mod_path)
            except Exception:
                continue
            for name in names:
                fn = getattr(mod, name, None)
                if not fn:
                    continue
                try:
                    if inspect.iscoroutinefunction(fn):
                        return await fn(icp)
                    return await asyncio.to_thread(fn, icp)
                except Exception as e:
                    return e
        return []

    async def _call_maps():
        try:
            mod = importlib.import_module("backend.app.services.maps_scraper")
            cls = getattr(mod, "MapsScraperService", None)
            if cls:
                inst = cls()
                fn = getattr(inst, "search_companies", None)
                if fn:
                    return await asyncio.to_thread(fn, query, 20)
            # module-level fallbacks
            for name in ("scrape_leads", "maps_search", "search_companies"):
                fn = getattr(mod, name, None)
                if fn:
                    if inspect.iscoroutinefunction(fn):
                        return await fn(icp)
                    return await asyncio.to_thread(fn, icp)
        except Exception as e:
            return e
        return []

    async def _call_linkedin():
        try:
            mod = importlib.import_module("backend.app.services.linkedin_service")
            cls = getattr(mod, "LinkedInService", None)
            if cls:
                inst = cls()
                fn = getattr(inst, "discover_decision_makers", None)
                if fn:
                    # try using the first keyword as a company hint
                    company_hint = keywords[0] if keywords else None
                    if inspect.iscoroutinefunction(fn):
                        return await fn(company_name=company_hint)
                    return await asyncio.to_thread(fn, company_name=company_hint)
            # module-level fallback names
            for name in ("discover_leads", "linkedin_search"):
                fn = getattr(mod, name, None)
                if fn:
                    if inspect.iscoroutinefunction(fn):
                        return await fn(icp)
                    return await asyncio.to_thread(fn, icp)
        except Exception as e:
            return e
        return []

    async def _call_tavily():
        # Prefer an app-provided wrapper if present
        try:
            mod = importlib.import_module("backend.app.services.tavily_client")
            fn = getattr(mod, "get_intent_signals", None)
            if fn:
                if inspect.iscoroutinefunction(fn):
                    return await fn(icp)
                return await asyncio.to_thread(fn, icp)
        except Exception:
            pass

        # Fallback: try langchain_community utility
        try:
            wrapper_mod = importlib.import_module("langchain_community.utilities.tavily_search")
            Tavily = getattr(wrapper_mod, "TavilySearchAPIWrapper", None)
            if Tavily is None:
                Tavily = getattr(wrapper_mod, "TavilySearchAPIWrapper", None)
            if Tavily:
                # The wrapper will read the API key from env if not provided
                try:
                    w = Tavily(tavily_api_key=settings.TAVILY_API_KEY)
                    q = query
                    # prefer sync run -> thread, else await arun
                    if hasattr(w, "run"):
                        return await asyncio.to_thread(w.run, q)
                    if hasattr(w, "arun"):
                        return await w.arun(q)
                except Exception as e:
                    return e
        except Exception:
            pass

        return []

    results = await asyncio.gather(
        _call_apollo(), _call_maps(), _call_linkedin(), _call_tavily(), return_exceptions=True
    )

    apollo_leads, maps_leads, li_leads, tavily_signals = [
        r if not isinstance(r, Exception) else [] for r in results
    ]

    errors = [f"{src}: {err}" for src, err in zip(["apollo", "maps", "linkedin", "tavily"], results) if isinstance(err, Exception)]

    return {
        **state,
        "raw_apollo_leads": apollo_leads,
        "raw_google_leads": maps_leads,
        "raw_linkedin_leads": li_leads,
        "tavily_signals": tavily_signals,
        "errors": list(state.get("errors") or []) + errors,
    }


def triangulation_validator(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Merge source lists and mark triangulated vs single-source leads.

    Uses email as the canonical key. Leads that appear in 2+ distinct
    sources receive `confidence: "high"`; single-source leads get
    `confidence: "low"` and are kept for later scoring.
    """
    from collections import defaultdict

    all_leads: dict[str, dict] = {}
    source_count: dict[str, int] = defaultdict(int)

    sources = [
        ("apollo", state.get("raw_apollo_leads") or []),
        ("maps", state.get("raw_google_leads") or []),
        ("linkedin", state.get("raw_linkedin_leads") or []),
    ]

    for source_name, leads in sources:
        for lead in leads or []:
            email = (lead.get("email") or "").lower().strip()
            if not email:
                continue
            if email not in all_leads:
                all_leads[email] = {
                    "email": email,
                    "name": lead.get("name") or lead.get("full_name") or "",
                    "company": lead.get("company") or lead.get("company_name") or "",
                    "title": lead.get("title") or "",
                    "industry": lead.get("industry") or "",
                    "linkedin_url": lead.get("linkedin_url") or lead.get("source_url") or None,
                    "phone": lead.get("phone") or None,
                    "sources": [source_name],
                    "signal_tags": [],
                    "score": None,
                    "score_rationale": None,
                    "score_critique": None,
                }
            else:
                existing = all_leads[email]
                if source_name not in existing["sources"]:
                    existing["sources"].append(source_name)
                for field in ("name", "title", "linkedin_url", "phone", "industry", "company"):
                    if (not existing.get(field)) and lead.get(field):
                        existing[field] = lead.get(field)
            source_count[email] += 1

    # Attach Tavily signal tags by company match (case-insensitive)
    signal_index: dict[str, list] = {}
    for s in state.get("tavily_signals") or []:
        try:
            comp = (s.get("company") or "").lower()
            tags = s.get("tags") or s.get("signal_tags") or []
            if comp:
                signal_index[comp] = tags
        except Exception:
            continue

    triangulated: list[dict] = []
    for email, rec in all_leads.items():
        company_key = (rec.get("company") or "").lower()
        if company_key and company_key in signal_index:
            rec["signal_tags"] = signal_index[company_key]
        # Confidence based on number of distinct sources
        rec["confidence"] = "high" if source_count[email] >= 2 else "low"
        triangulated.append(rec)

    return {**state, "triangulated_leads": triangulated}


async def dedup_filter(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Filter out leads that already exist for the target user.

    Loads existing lead emails from Postgres into a Python `set` for
    O(1) lookups. Uses a blocking DB call inside `asyncio.to_thread`
    so this node remains non-blocking to the event loop.
    """
    from backend.app.database import session_scope

    def _fetch_existing_emails(uid: int) -> set:
        try:
            with session_scope() as db:
                res = db.execute(
                    text("SELECT email FROM leads WHERE user_id = :uid"),
                    {"uid": uid},
                ).fetchall()
                return {row[0].lower() for row in res if row and row[0]}
        except Exception:
            return set()

    try:
        uid_raw = state.get("user_id")
        existing_emails: set[str] = set()
        if uid_raw is None or uid_raw == "global":
            existing_emails = set()
        else:
            try:
                uid_int = int(uid_raw)
            except Exception:
                existing_emails = set()
            else:
                existing_emails = await asyncio.to_thread(_fetch_existing_emails, uid_int)

        triangulated = state.get("triangulated_leads") or []
        new_leads = [
            lead
            for lead in triangulated
            if lead.get("email") and lead["email"].lower().strip() not in existing_emails
        ]
        return {**state, "deduplicated_leads": new_leads}
    except Exception as exc:
        log.error("dedup_filter_failed", error=str(exc))
        errors = list(state.get("errors") or []) + [f"dedup_filter: {str(exc)}"]
        # On failure, return the triangulated set so downstream nodes can continue
        return {**state, "deduplicated_leads": state.get("triangulated_leads") or [], "errors": errors}


async def score_leads(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Apply the Phase 4 PRIME scorer to the deduplicated leads.

    The lead scorer was implemented in Phase 4, but it needs to sit on
    the active lead discovery path rather than only inside the legacy
    sequential helper. This node keeps the agent-first flow intact while
    preserving a direct node-level fallback when the compiled scorer
    graph is unavailable.
    """
    scorer_initial = {
        "user_id": state.get("user_id"),
        "icp_profile": state.get("icp_profile") or {},
        "leads_to_score": state.get("deduplicated_leads") or [],
        "scored_leads": [],
        "critiqued_leads": [],
        "errors": [],
    }

    if not scorer_initial["leads_to_score"]:
        return state

    try:
        from backend.app.agents.lead_scorer import build_scorer_graph

        scorer_graph = await build_scorer_graph()
        scorer_result = await scorer_graph.ainvoke(scorer_initial)
        scored_leads = (
            scorer_result.get("critiqued_leads")
            or scorer_result.get("scored_leads")
            or scorer_initial["leads_to_score"]
        )
        scorer_errors = list(scorer_result.get("errors") or [])
    except Exception as exc:
        log.warning("scorer_graph_unavailable_fallback", error=str(exc))
        try:
            from backend.app.agents.lead_scorer import first_pass_scorer, self_critique_scorer

            scorer_state = await first_pass_scorer(scorer_initial)
            scorer_state = await self_critique_scorer(scorer_state)
            scored_leads = (
                scorer_state.get("critiqued_leads")
                or scorer_state.get("scored_leads")
                or scorer_initial["leads_to_score"]
            )
            scorer_errors = list(scorer_state.get("errors") or [])
        except Exception as fallback_exc:
            log.error("scorer_nodes_failed", error=str(fallback_exc))
            scored_leads = scorer_initial["leads_to_score"]
            scorer_errors = [f"scorer_failed: {str(fallback_exc)}"]

    return {
        **state,
        "deduplicated_leads": scored_leads,
        "errors": list(state.get("errors") or []) + scorer_errors,
    }


@with_retry(max_attempts=3)
async def hubspot_sync(state: LeadDiscoveryState) -> LeadDiscoveryState:
    """Chunk deduplicated leads and sync to HubSpot, persisting to Postgres per chunk.

    Each chunk is retried independently via the inner `_send_chunk` helper so
    a single failing chunk won't abort the whole node.
    """
    leads = state.get("deduplicated_leads") or []
    if not leads:
        return {**state, "hubspot_results": []}

    from backend.services.hubspot import HubSpotClient

    hubspot = HubSpotClient()
    results: list = []
    chunk_size = 50

    @with_retry(max_attempts=3, service="hubspot")
    async def _send_chunk(client: HubSpotClient, payloads: list[dict]) -> dict:
        return await asyncio.to_thread(client.batch_upsert_contacts, payloads)

    def _persist_chunk(uid: int | None, chunk_batch: list[dict]) -> None:
        try:
            with session_scope() as db:
                from backend.domains.leads.models.lead import Lead as LeadModel

                to_add: list[LeadModel] = []
                for lead in chunk_batch:
                    email = lead.get("email")
                    if not email:
                        continue
                    # Check existence for this user to avoid duplicates
                    try:
                        existing = db.execute(
                            text("SELECT id FROM leads WHERE user_id = :uid AND email = :email"),
                            {"uid": uid, "email": email},
                        ).fetchone()
                    except Exception:
                        existing = None
                    if existing:
                        continue

                    first_name = lead.get("first_name") or (lead.get("name") or "").split()[0:1][0] if lead.get("name") else None
                    last_name = lead.get("last_name") or (lead.get("name") or "").split()[1:2][0] if lead.get("name") and len((lead.get("name") or "").split()) > 1 else None

                    lm = LeadModel(
                        user_id=int(uid) if uid is not None else None,
                        external_id=lead.get("external_id"),
                        name=lead.get("name"),
                        email=email,
                        phone=lead.get("phone"),
                        first_name=first_name,
                        last_name=last_name,
                        company=lead.get("company"),
                        company_domain=lead.get("company_domain"),
                        linkedin_url=lead.get("linkedin_url"),
                        title=lead.get("title"),
                        industry=lead.get("industry"),
                        source=",".join(lead.get("sources") or ["agent"]),
                        status="new",
                    )
                    to_add.append(lm)

                if to_add:
                    db.add_all(to_add)
                    db.commit()
        except Exception:
            # Let caller handle errors; avoid raising inside thread
            raise

    for i in range(0, len(leads), chunk_size):
        chunk = leads[i : i + chunk_size]
        hubspot_payloads: list[dict] = []
        for ld in chunk:
            if not ld.get("email"):
                continue
            hubspot_payloads.append(
                {
                    "email": ld.get("email"),
                    "firstname": ld.get("first_name") or (ld.get("name") or "").split()[0:1][0],
                    "lastname": ld.get("last_name") or (ld.get("name") or "").split()[1:2][0] if ld.get("name") and len((ld.get("name") or "").split()) > 1 else None,
                    "company": ld.get("company"),
                    "website": ld.get("company_domain"),
                    "jobtitle": ld.get("title"),
                }
            )

        try:
            resp = await _send_chunk(hubspot, hubspot_payloads)
            results.append(resp)

            # Persist successful chunk to Postgres (run in thread)
            uid_raw = state.get("user_id")
            try:
                uid_int = int(uid_raw) if uid_raw not in (None, "global") else None
            except Exception:
                uid_int = None

            try:
                await asyncio.to_thread(_persist_chunk, uid_int, chunk)
            except Exception as exc:
                # If DB persist fails, record error but continue
                err = f"hubspot_persist_chunk_{i}: {str(exc)}"
                state["errors"] = list(state.get("errors") or []) + [err]
        except Exception as exc:
            state["errors"] = list(state.get("errors") or []) + [f"hubspot_chunk_{i}: {str(exc)}"]
            continue

    return {**state, "hubspot_results": results}


async def _save_checkpoint(run_uuid: str, step: str, state: dict) -> None:
    """Attempt to persist a checkpoint. Prefer LangGraph saver; fallback to Redis."""
    key = f"lead_discovery:{run_uuid}:{step}"
    try:
        cp = await get_checkpointer()
        # Try common async save method names
        if hasattr(cp, "save"):
            maybe = getattr(cp, "save")
            if asyncio.iscoroutinefunction(maybe):
                await maybe(key, json.dumps(state))
            else:
                maybe(key, json.dumps(state))
            return
        if hasattr(cp, "asave"):
            await cp.asave(key, json.dumps(state))
            return
        if hasattr(cp, "aset"):
            await cp.aset(key, json.dumps(state))
            return
    except Exception:
        log.debug("checkpoint_langgraph_unavailable_or_failed", step=step)

    # Fallback: write a simple redis key
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.set(key, json.dumps(state))
        await r.close()
    except Exception:
        log.debug("checkpoint_fallback_failed", step=step)


async def _run_lead_discovery_sequential(user_id: int | None = None, query: str | None = None) -> dict:
    """Legacy sequential runner preserved for local/in-process execution.

    The new `run_lead_discovery` wrapper will attempt to run the
    LangGraph-compiled agent first and only fall back to the Celery
    worker if agent execution fails or LangGraph is unavailable.
    """
    run_uuid = uuid.uuid4().hex
    uid_str = str(user_id) if user_id is not None else "global"

    try:
        with session_scope() as db:
            create_workflow_run(
                db,
                workflow_name="lead_discovery",
                domain="leads",
                trigger_source="agent",
                user_id=user_id,
                payload={"run_uuid": run_uuid, "query": query},
            )
    except Exception:
        log.exception("create_workflow_run_failed", run_uuid=run_uuid)

    state: LeadDiscoveryState = {
        "user_id": uid_str,
        "icp_profile": None,
        "raw_google_leads": None,
        "raw_linkedin_leads": None,
        "raw_apollo_leads": None,
        "tavily_signals": None,
        "triangulated_leads": None,
        "deduplicated_leads": None,
        "hubspot_results": None,
        "errors": [],
        "run_id": run_uuid,
    }

    # Node: ICP loader
    state = await icp_loader(state)
    await _save_checkpoint(run_uuid, "icp_loaded", state)

    # Node: multi-source retriever (maps, linkedin, apollo + Tavily signals)
    state = await multi_source_retriever(state)
    await _save_checkpoint(run_uuid, "sources_retrieved", state)

    # Node: triangulation validator (PRIME)
    state = triangulation_validator(state)
    await _save_checkpoint(run_uuid, "triangulated", state)

    # Node: deduplication filter (remove emails already in DB)
    state = await dedup_filter(state)
    await _save_checkpoint(run_uuid, "deduplicated", state)

    # Node: Lead Scorer (PRIME two-pass)
    state = await score_leads(state)

    await _save_checkpoint(run_uuid, "scored", state)

    # Node: hubspot sync (chunked, persist after each successful chunk)
    state = await hubspot_sync(state)
    await _save_checkpoint(run_uuid, "hubspot_synced", state)

    # Additional nodes (scoring) are left as TODO

    await _save_checkpoint(run_uuid, "finished", state)
    return {"success": True, "run_id": run_uuid, "state": state}


async def build_lead_discovery_graph():
    """Compile a LangGraph StateGraph for lead discovery.

    This is imported lazily so the module can be imported even when
    LangGraph is not installed. Any exception raised here should be
    handled by callers and trigger the fallback path.
    """
    try:
        from langgraph.graph import StateGraph, END
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("LangGraph is not available") from exc

    g = StateGraph(LeadDiscoveryState)
    g.add_node("icp_loader", icp_loader)
    g.add_node("multi_source_retriever", multi_source_retriever)
    g.add_node("triangulation_validator", triangulation_validator)
    g.add_node("dedup_filter", dedup_filter)
    g.add_node("score_leads", score_leads)
    g.add_node("hubspot_sync", hubspot_sync)
    g.set_entry_point("icp_loader")
    g.add_edge("icp_loader", "multi_source_retriever")
    g.add_edge("multi_source_retriever", "triangulation_validator")
    g.add_edge("triangulation_validator", "dedup_filter")
    g.add_edge("dedup_filter", "score_leads")
    g.add_edge("score_leads", "hubspot_sync")
    g.add_edge("hubspot_sync", END)

    checkpointer = await get_checkpointer()
    return g.compile(checkpointer=checkpointer)


async def run_lead_discovery(user_id: int | None = None, query: str | None = None) -> dict:
    """Agent-first entrypoint used by scheduler entrypoints.

    Attempts to run the LangGraph agent; on any failure it will schedule
    the legacy Celery `source_leads_task` (if `AGENT_FALLBACK_ENABLED`) and
    return a success result indicating the fallback was used.
    """
    thread_user = str(user_id) if user_id is not None else "global"
    try:
        graph = await build_lead_discovery_graph()
        from backend.app.agents.base import make_thread_id
        from backend.app.core.observability import AgentObservabilityCallback

        thread_id = make_thread_id("lead_discovery", thread_user)
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [AgentObservabilityCallback("lead_discovery", thread_user)],
        }

        initial_state = LeadDiscoveryState(
            user_id=thread_user,
            icp_profile={},
            raw_google_leads=[],
            raw_linkedin_leads=[],
            raw_apollo_leads=[],
            tavily_signals=[],
            triangulated_leads=[],
            deduplicated_leads=[],
            hubspot_results=[],
            errors=[],
            run_id=thread_id,
        )

        result = await graph.ainvoke(initial_state, config=config)
        log.info("lead_discovery_agent_success", user_id=user_id, leads_synced=len(result.get("deduplicated_leads") or []))
        return {"success": True, "data": result, "fallback_used": False}

    except Exception as exc:  # pragma: no cover - exercised in integration
        log.error("lead_discovery_agent_failed_using_fallback", user_id=user_id, error=str(exc))
        # If enabled, schedule the legacy Celery task as a fallback
        if getattr(settings, "AGENT_FALLBACK_ENABLED", True):
            try:
                from backend.workers.lead_sourcing import source_leads_task

                # Schedule the existing Celery job and return as handled
                source_leads_task.delay(query=query or settings.DEFAULT_LEAD_QUERY, user_id=user_id)
                return {"success": True, "data": None, "fallback_used": True}
            except Exception:
                log.exception("fallback_scheduling_failed", user_id=user_id)
                raise
        raise
