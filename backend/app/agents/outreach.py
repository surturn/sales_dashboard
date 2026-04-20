"""Outreach agent with human approval gate.

This phase introduces a LangGraph-compatible outreach flow that drafts a
personalized email, critiques it, persists a pending approval record,
and pauses until a human approves or rejects the draft.

The repo still uses synchronous SQLAlchemy sessions and a synchronous
SMTP sender, so blocking work is wrapped with `asyncio.to_thread(...)`
to keep the agent entrypoint async-friendly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, TypedDict

from sqlalchemy import or_, select

from backend.app.agents.base import AgentResult, LeadRecord, get_checkpointer, make_thread_id
from backend.app.config import get_settings
from backend.app.core.observability import AgentObservabilityCallback, get_logger
from backend.app.database import session_scope
from backend.domains.leads.models.lead import Lead
from backend.domains.leads.services.outreach_service import send_outreach_for_lead, upsert_lead_from_contact
from backend.models.outreach_approval_queue import OutreachApprovalQueue
from backend.services.email_sender import EmailSender
from backend.services.llm_router import call_llm

settings = get_settings()
log = get_logger("outreach_agent")


class OutreachState(TypedDict):
    user_id: str
    lead: LeadRecord
    contact_context: str
    email_draft: str
    critique_notes: str
    refined_draft: str
    approved: Optional[bool]
    final_draft: str
    send_result: dict
    errors: list[str]
    run_id: str


def context_builder(state: OutreachState) -> OutreachState:
    """Build a concise lead summary for the drafting prompt."""
    lead = state["lead"]
    context = (
        f"Name: {lead.get('name') or 'unknown'}\n"
        f"Title: {lead.get('title') or 'unknown'}\n"
        f"Company: {lead.get('company') or 'unknown'}\n"
        f"Industry: {lead.get('industry') or 'unknown'}\n"
        f"Intent signals: {', '.join(lead.get('signal_tags') or []) or 'none detected'}\n"
        f"Source: found via {', '.join(lead.get('sources') or []) or 'unknown'}\n"
    )
    return {**state, "contact_context": context}


async def email_drafter(state: OutreachState) -> OutreachState:
    """Draft a concise first-person outreach email body."""
    system = (
        "You are a skilled outreach specialist writing a personalised cold email. "
        "Write in first person, under 150 words, with one specific reference to "
        "the recipient's context, and one clear CTA. No generic phrases like "
        "'I hope this finds you well'. No attachments mentioned."
    )
    prompt = (
        f"Write a cold outreach email to:\n{state['contact_context']}\n"
        "Return ONLY the email body - no subject line, no sign-off."
    )
    draft = await call_llm(prompt, system=system, task="email_draft")
    return {**state, "email_draft": draft}


async def email_critic(state: OutreachState) -> OutreachState:
    """Critique then refine the drafted email."""
    prompt = (
        "Critique this cold email in 2 sentences. Flag: generic openers, "
        "missing personalisation, weak CTA, over 150 words.\n\n"
        f"Email:\n{state['email_draft']}"
    )
    critique = await call_llm(prompt, task="email_critique")
    refine_prompt = (
        f"Original email:\n{state['email_draft']}\n\n"
        f"Critique:\n{critique}\n\n"
        "Rewrite the email addressing the critique. Return ONLY the email body."
    )
    refined = await call_llm(refine_prompt, task="email_draft")
    return {**state, "critique_notes": critique, "refined_draft": refined}


async def approval_gate(state: OutreachState) -> OutreachState:
    """Persist a pending approval record then pause the graph.

    This repo currently uses the `NodeInterrupt` pattern exposed by the
    installed LangGraph version. The approval API later injects the human
    decision back into the graph state and resumes execution.
    """
    draft_id = str(uuid.uuid4())

    def _persist_pending() -> None:
        with session_scope() as db:
            approval = OutreachApprovalQueue(
                id=draft_id,
                user_id=int(state["user_id"]),
                lead_id=int(state["lead"]["id"]) if state["lead"].get("id") is not None else None,
                lead_email=state["lead"]["email"],
                draft=state["refined_draft"],
                final_draft=None,
                status="pending",
                thread_id=state["run_id"],
            )
            db.add(approval)
            db.commit()

    await asyncio.to_thread(_persist_pending)

    from langgraph.errors import NodeInterrupt

    raise NodeInterrupt({"draft_id": draft_id, "draft": state["refined_draft"]})


def should_send(state: OutreachState) -> str:
    """Only send after explicit approval."""
    from langgraph.graph import END

    return "send_email" if state.get("approved") else END


async def send_email(state: OutreachState) -> OutreachState:
    """Send the approved email using the existing SMTP sender."""

    def _send() -> dict:
        lead = state["lead"]
        subject_target = lead.get("company") or lead.get("name") or "your team"
        subject = f"Quick idea for {subject_target}"
        return EmailSender().send_email(
            to=lead["email"],
            subject=subject,
            body=state["final_draft"],
        )

    result = await asyncio.to_thread(_send)
    return {**state, "send_result": result}


async def build_outreach_graph():
    """Compile the approval-gated outreach graph."""
    try:
        from langgraph.graph import StateGraph, END
    except Exception as exc:
        raise RuntimeError("LangGraph is not available") from exc

    graph = StateGraph(OutreachState)
    graph.add_node("context_builder", context_builder)
    graph.add_node("email_drafter", email_drafter)
    graph.add_node("email_critic", email_critic)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("send_email", send_email)
    graph.set_entry_point("context_builder")
    graph.add_edge("context_builder", "email_drafter")
    graph.add_edge("email_drafter", "email_critic")
    graph.add_edge("email_critic", "approval_gate")
    graph.add_conditional_edges("approval_gate", should_send, {"send_email": "send_email", END: END})
    graph.add_edge("send_email", END)

    checkpointer = await get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def _lead_to_record(lead: Lead) -> LeadRecord:
    """Normalize the existing Lead ORM row into the shared agent shape."""
    return {
        "id": lead.id,
        "email": lead.email or "",
        "name": lead.name or "Unknown",
        "company": lead.company or "",
        "title": lead.title or "",
        "industry": lead.industry or "",
        "linkedin_url": lead.linkedin_url,
        "phone": lead.phone,
        "sources": [lead.source] if lead.source else [],
        "signal_tags": [],
        "score": None,
        "score_rationale": None,
        "score_critique": None,
    }


async def run_outreach(user_id: int, lead: LeadRecord) -> AgentResult:
    """Run the outreach graph and fall back to the legacy outreach service."""
    thread_id = make_thread_id("outreach", str(user_id))
    initial_state: OutreachState = {
        "user_id": str(user_id),
        "lead": lead,
        "contact_context": "",
        "email_draft": "",
        "critique_notes": "",
        "refined_draft": "",
        "approved": None,
        "final_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": thread_id,
    }

    try:
        graph = await build_outreach_graph()
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [AgentObservabilityCallback("outreach", str(user_id))],
        }
        result = await graph.ainvoke(initial_state, config=config)
        return {
            "success": True,
            "data": result,
            "error": None,
            "fallback_used": False,
            "run_id": thread_id,
            "agent_name": "outreach",
        }
    except Exception as exc:
        try:
            from langgraph.errors import GraphInterrupt
        except Exception:
            GraphInterrupt = None

        if GraphInterrupt is not None and isinstance(exc, GraphInterrupt):
            log.info("outreach_agent_paused_for_approval", user_id=user_id, run_id=thread_id)
            return {
                "success": True,
                "data": {"status": "awaiting_approval"},
                "error": None,
                "fallback_used": False,
                "run_id": thread_id,
                "agent_name": "outreach",
            }
        log.warning("outreach_agent_failed_using_fallback", error=str(exc), user_id=user_id)
        if not getattr(settings, "AGENT_FALLBACK_ENABLED", True):
            raise

        def _fallback_send() -> dict:
            with session_scope() as db:
                lead_row = None
                lead_id = lead.get("id")
                if lead_id is not None:
                    lead_row = db.scalar(select(Lead).where(Lead.id == int(lead_id)))
                if lead_row is None and lead.get("email"):
                    lead_row = db.scalar(
                        select(Lead).where(
                            Lead.email == lead["email"],
                            or_(Lead.user_id == user_id, Lead.user_id.is_(None)),
                        )
                    )
                if lead_row is None:
                    contact = {
                        "email": lead.get("email"),
                        "fullname": lead.get("name"),
                        "company": lead.get("company"),
                        "jobtitle": lead.get("title"),
                        "linkedin_url": lead.get("linkedin_url"),
                        "phone": lead.get("phone"),
                    }
                    lead_row = upsert_lead_from_contact(db, contact=contact, user_id=user_id)

                log_row = send_outreach_for_lead(db, lead=lead_row, user_id=user_id)
                return {"log_id": log_row.id, "status": log_row.status}

        fallback_result = await asyncio.to_thread(_fallback_send)
        return {
            "success": True,
            "data": fallback_result,
            "error": str(exc),
            "fallback_used": True,
            "run_id": thread_id,
            "agent_name": "outreach",
        }


async def run_outreach_for_lead_id(user_id: int, lead_id: int) -> AgentResult:
    """Load a lead from Postgres then hand it to the outreach agent."""

    def _fetch_lead() -> Lead:
        with session_scope() as db:
            lead = db.scalar(
                select(Lead).where(Lead.id == lead_id, or_(Lead.user_id == user_id, Lead.user_id.is_(None)))
            )
            if lead is None:
                raise ValueError("Lead not found")
            return lead

    lead = await asyncio.to_thread(_fetch_lead)
    return await run_outreach(user_id=user_id, lead=_lead_to_record(lead))
