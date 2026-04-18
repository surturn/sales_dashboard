"""Reporting agent + ICP learning loop (Phase 7).

Nodes:
- metrics_collector: collects metrics from Postgres (uses existing `build_report_metrics`)
- metrics_assembler: prepares an ordered presentation of metrics
- narrative_writer: calls LLM (`call_llm` task `report_summary`) to generate executive summary
- icp_updater: embeds recent conversions and upserts to Qdrant ICP collection
- report_sender: sends the report via `EmailSender` and records the run

Provides `build_reporting_graph()` and `run_reporting()` (agent-first, legacy fallback to `backend.workers.reporting`).
"""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from typing import Any, TypedDict, Optional

from backend.app.config import get_settings
from backend.app.core.observability import get_logger, AgentObservabilityCallback
from backend.app.agents.base import get_checkpointer, make_thread_id, AgentResult
from backend.app.database import session_scope
from backend.services.llm_router import call_llm
from backend.app.services.qdrant_client import get_qdrant
from backend.services.email_sender import EmailSender

log = get_logger("reporting_agent")
settings = get_settings()


class ReportingState(TypedDict):
    user_id: Optional[str]
    metrics: dict
    metrics_presented: dict
    summary: str
    icp_updated: bool
    conversions_this_week: int
    errors: list
    run_id: str


async def metrics_collector(state: ReportingState) -> ReportingState:
    errors = list(state.get("errors") or [])
    metrics: dict = {}
    try:
        # Use existing reporting builder which expects a SQLAlchemy Session
        from backend.workers.reporting import build_report_metrics

        def _collect():
            with session_scope() as db:
                uid = state.get("user_id")
                try:
                    user_id_int = int(uid) if uid else None
                except Exception:
                    user_id_int = None
                return build_report_metrics(db, user_id=user_id_int)

        metrics = await asyncio.to_thread(_collect)
    except Exception as exc:
        log.error("metrics_collector_failed", error=str(exc))
        errors.append(f"metrics_collector_failed: {str(exc)}")

    return {**state, "metrics": metrics, "errors": errors}


async def metrics_assembler(state: ReportingState) -> ReportingState:
    metrics = state.get("metrics") or {}
    # Simple ordered presentation: keep insertion order from the dict
    ordered = OrderedDict()
    for k, v in (metrics.items() if isinstance(metrics, dict) else []):
        ordered[k] = v
    return {**state, "metrics_presented": dict(ordered)}


async def narrative_writer(state: ReportingState) -> ReportingState:
    errors = list(state.get("errors") or [])
    try:
        metrics_for_prompt = state.get("metrics_presented") or state.get("metrics") or {}
        prompt = (
            "You are an executive assistant. Produce a concise (2-3 paragraph) executive summary of the weekly metrics. "
            "Write in plain English targeted at a startup founder.\n\n" + json.dumps(metrics_for_prompt, indent=2)
        )
        summary = await call_llm(prompt, task="report_summary")
    except Exception as exc:
        log.error("narrative_writer_failed", error=str(exc))
        summary = ""
        errors.append(f"narrative_writer_failed: {str(exc)}")

    return {**state, "summary": summary, "errors": errors}


async def icp_updater(state: ReportingState) -> ReportingState:
    """Embed recent conversions and upsert to Qdrant ICP collection.

    Uses `session_scope()` to read Postgres conversions for the user in the
    last 7 days, embeds each converted lead with `embed_lead`, and upserts to
    `settings.QDRANT_COLLECTION_ICP`.
    """
    errors = list(state.get("errors") or [])
    user_id = state.get("user_id")
    if not user_id:
        return {**state, "icp_updated": False}

    try:
        from sqlalchemy import text

        def _fetch_converted():
            with session_scope() as db:
                q = (
                    "SELECT l.* FROM leads l JOIN conversions c ON l.id = c.lead_id "
                    "WHERE c.user_id = :uid AND c.recorded_at >= NOW() - INTERVAL '7 days'"
                )
                res = db.execute(text(q), {"uid": int(user_id)})
                rows = res.fetchall()
                # Convert SQLAlchemy rows to plain dicts when possible
                out = []
                for r in rows:
                    try:
                        out.append(dict(r._mapping))
                    except Exception:
                        try:
                            out.append(dict(r))
                        except Exception:
                            out.append({})
                return out

        converted = await asyncio.to_thread(_fetch_converted)
    except Exception as exc:
        log.error("icp_updater_db_failed", error=str(exc))
        errors.append(f"icp_updater_db_failed: {str(exc)}")
        return {**state, "icp_updated": False, "errors": errors}

    if not converted:
        return {**state, "icp_updated": False, "errors": errors}

    try:
        from backend.app.services.embeddings import embed_lead
        from qdrant_client.models import PointStruct

        client = await get_qdrant()
        points = []
        for lead in converted:
            embedding = await embed_lead(lead)
            points.append(
                PointStruct(
                    id=str(lead.get("id")),
                    vector=embedding,
                    payload={
                        "user_id": str(user_id),
                        "converted": True,
                        "industry": lead.get("industry"),
                        "title": lead.get("title"),
                    },
                )
            )

        await client.upsert(collection_name=settings.QDRANT_COLLECTION_ICP, points=points)
        await client.close()
    except Exception as exc:
        log.error("icp_updater_qdrant_failed", error=str(exc))
        errors.append(f"icp_updater_qdrant_failed: {str(exc)}")
        return {**state, "icp_updated": False, "errors": errors}

    return {**state, "icp_updated": True, "conversions_this_week": len(converted), "errors": errors}


async def report_sender(state: ReportingState) -> ReportingState:
    errors = list(state.get("errors") or [])
    try:
        EmailSender().send_email(
            to=getattr(settings, "REPORT_RECIPIENT_EMAIL", ""),
            subject="Bizard Leads Weekly Report",
            body=state.get("summary") or "",
        )

        # Record the run via existing worker helper
        def _persist():
            from backend.workers.reporting import _record_run

            with session_scope() as db:
                _record_run(db, user_id=(int(state.get("user_id")) if state.get("user_id") else None), status="completed", payload=state.get("metrics") or {})

        await asyncio.to_thread(_persist)
    except Exception as exc:
        log.error("report_sender_failed", error=str(exc))
        errors.append(f"report_sender_failed: {str(exc)}")

    return {**state, "errors": errors}


async def build_reporting_graph():
    try:
        from langgraph.graph import StateGraph, END
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("LangGraph is not available") from exc

    g = StateGraph(ReportingState)
    g.add_node("metrics_collector", metrics_collector)
    g.add_node("metrics_assembler", metrics_assembler)
    g.add_node("narrative_writer", narrative_writer)
    g.add_node("icp_updater", icp_updater)
    g.add_node("report_sender", report_sender)
    g.set_entry_point("metrics_collector")
    g.add_edge("metrics_collector", "metrics_assembler")
    g.add_edge("metrics_assembler", "narrative_writer")
    g.add_edge("narrative_writer", "icp_updater")
    g.add_edge("icp_updater", "report_sender")
    g.add_edge("report_sender", END)

    try:
        cp = await get_checkpointer()
    except Exception:
        cp = None

    if cp is not None:
        return g.compile(checkpointer=cp)
    return g.compile()


async def run_reporting(user_id: Optional[int] | None = None) -> AgentResult:
    """Run the reporting agent; fall back to legacy Celery worker on failure."""
    from backend.workers.reporting import generate_weekly_report_task

    thread_id = make_thread_id("reporting", str(user_id or "system"))
    initial: ReportingState = {
        "user_id": str(user_id) if user_id is not None else None,
        "metrics": {},
        "metrics_presented": {},
        "summary": "",
        "icp_updated": False,
        "conversions_this_week": 0,
        "errors": [],
        "run_id": thread_id,
    }

    try:
        graph = await build_reporting_graph()
        config = {"configurable": {"thread_id": thread_id}, "callbacks": [AgentObservabilityCallback("reporting", str(user_id or "system"))]}
        result = await graph.ainvoke(initial, config=config)
        return {
            "success": True,
            "data": result,
            "error": None,
            "fallback_used": False,
            "run_id": thread_id,
            "agent_name": "reporting",
        }
    except Exception as exc:
        # Fallback: run legacy reporting worker synchronously in thread
        fallback_result = await asyncio.to_thread(generate_weekly_report_task)
        log.warning("reporting_agent_failed_using_fallback", error=str(exc))
        return {
            "success": True,
            "data": fallback_result,
            "error": str(exc),
            "fallback_used": True,
            "run_id": thread_id,
            "agent_name": "reporting",
        }
