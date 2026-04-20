"""Lead Scorer agent (Phase 4 PRIME scorer).

Provides a two-pass scoring flow. This module implements the
first-pass batched scorer which uses the fast Groq model to assign a
0-100 fit score and a one-line rationale for each lead.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TypedDict, Optional, List

from backend.app.config import get_settings
from backend.app.core.observability import get_logger
from backend.app.core.retry import with_retry
from backend.app.agents.base import LeadRecord
from backend.services.llm_router import call_llm

settings = get_settings()
log = get_logger("lead_scorer")


class LeadScorerState(TypedDict):
    user_id: str
    icp_profile: dict
    leads_to_score: List[LeadRecord]
    scored_leads: List[LeadRecord]
    critiqued_leads: List[LeadRecord]
    errors: List[str]


@with_retry(service="lead_scorer_first_pass")
async def first_pass_scorer(state: LeadScorerState) -> LeadScorerState:
    """Score leads in batches using the fast Groq model.

    - Default batch size: 20
    - Token budget: ~50 tokens per lead; respect `LLM_MAX_TOKENS_PER_NODE`.
    - Returns `scored_leads` sorted descending by score.
    """
    leads = state.get("leads_to_score") or []
    icp = state.get("icp_profile") or {}
    scored: List[dict] = []

    # Compute safe batch size from token budget (50 tokens per lead)
    try:
        budget = int(getattr(settings, "LLM_MAX_TOKENS_PER_NODE", 2000) or 2000)
    except Exception:
        budget = 2000
    default_batch = 20
    batch_size = max(1, min(default_batch, budget // 50))

    for i in range(0, len(leads), batch_size):
        batch = leads[i : i + batch_size]

        leads_text_lines = []
        for j, l in enumerate(batch, start=1):
            name = l.get("name") or ""
            title = l.get("title") or ""
            company = l.get("company") or ""
            industry = l.get("industry") or ""
            signals = ",".join(l.get("signal_tags") or [])
            leads_text_lines.append(f"{j}. {name} | {title} | {company} | {industry} | signals: {signals}")

        leads_text = "\n".join(leads_text_lines)

        prompt = (
            f"ICP: industry={icp.get('industry')}, location={icp.get('location')}, "
            f"seniority={icp.get('seniority')}, keywords={icp.get('keywords')}\n\n"
            f"Score each lead 0-100 for fit. Return ONLY a JSON array of objects with "
            f"keys: index (1-based), score (int), rationale (max 15 words).\n\n"
            f"Leads:\n{leads_text}"
        )

        try:
            result_str = await call_llm(prompt, task="score_fast")
            scores = json.loads(result_str)
            if not isinstance(scores, list):
                raise ValueError("LLM returned non-list JSON")
        except Exception as exc:
            log.error("first_pass_scorer_batch_failed", batch_start=i, error=str(exc))
            # On error, append a batch-level error and give each lead a 0 score
            errors = list(state.get("errors") or []) + [f"first_pass_batch_{i}: {str(exc)}"]
            for lead in batch:
                lead_copy = dict(lead)
                lead_copy["score"] = 0
                lead_copy["score_rationale"] = "scoring_failed"
                scored.append(lead_copy)
            state["errors"] = errors
            continue

        for lead, score_obj in zip(batch, scores):
            lead_copy = dict(lead)
            try:
                sc = int(score_obj.get("score", 0))
            except Exception:
                sc = 0
            lead_copy["score"] = max(0, min(100, sc))
            lead_copy["score_rationale"] = (score_obj.get("rationale") or "")
            scored.append(lead_copy)

    scored_sorted = sorted(scored, key=lambda x: -int(x.get("score", 0)))
    return {**state, "scored_leads": scored_sorted, "errors": list(state.get("errors") or [])}


@with_retry(service="lead_scorer_critic")
async def self_critique_scorer(state: LeadScorerState) -> LeadScorerState:
    """Run a focused critic pass on top-tier leads using the larger model.

    Only processes leads with score >= 70 (conservative top tier) to
    conserve the large-model quota. The critic returns adjusted scores
    and brief critiques; changes are applied deterministically.
    """
    scored = state.get("scored_leads") or []
    top_leads = [l for l in scored if int(l.get("score", 0)) >= 70]
    rest = [l for l in scored if int(l.get("score", 0)) < 70]

    if not top_leads:
        return {**state, "critiqued_leads": scored}

    critique_system = (
        "You are a critical reviewer challenging lead scores. Look for obvious errors: "
        "wrong industry, wrong geography, wrong seniority level, or signals that are "
        "irrelevant to the ICP. Reduce scores for clear mismatches. "
        "Do NOT make subtle adjustments — only flag obvious errors. "
        "Return ONLY JSON array matching input structure."
    )

    leads_text_lines = []
    for j, l in enumerate(top_leads, start=1):
        name = l.get("name") or ""
        title = l.get("title") or ""
        company = l.get("company") or ""
        leads_text_lines.append(
            f"{j}. {name} | {title} | {company} | score:{l.get('score')} | rationale:{l.get('score_rationale')}"
        )

    leads_text = "\n".join(leads_text_lines)

    prompt = (
        f"ICP: {json.dumps(state.get('icp_profile') or {})}\n\n"
        f"Challenge these scores. For each lead return: index, adjusted_score (int), critique (max 20 words).\n\n{leads_text}"
    )

    try:
        result_str = await call_llm(prompt, system=critique_system, task="score_critic")
        critiques = json.loads(result_str)
        if not isinstance(critiques, list):
            raise ValueError("Critic LLM returned non-list JSON")
    except Exception as exc:
        log.error("self_critique_failed", error=str(exc))
        errors = list(state.get("errors") or []) + [f"self_critique: {str(exc)}"]
        # If critic fails, return original scored list as critiqued
        return {**state, "critiqued_leads": scored, "errors": errors}

    adjusted: list[dict] = []
    for lead, critique in zip(top_leads, critiques):
        lead_copy = dict(lead)
        try:
            adj = int(critique.get("adjusted_score", lead_copy.get("score")))
        except Exception:
            adj = lead_copy.get("score")
        lead_copy["score"] = max(0, min(100, adj))
        lead_copy["score_critique"] = critique.get("critique") or ""
        adjusted.append(lead_copy)

    all_leads = sorted(adjusted + rest, key=lambda x: -int(x.get("score", 0)))
    return {**state, "critiqued_leads": all_leads, "errors": list(state.get("errors") or [])}


async def build_scorer_graph():
    """Compile the lead scorer StateGraph for agent execution.

    Lazy-imports LangGraph so the module can be imported in environments
    without the package installed; callers should handle RuntimeError.
    """
    try:
        from langgraph.graph import StateGraph, END
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("LangGraph is not available") from exc

    g = StateGraph(LeadScorerState)
    g.add_node("first_pass_scorer", first_pass_scorer)
    g.add_node("self_critique_scorer", self_critique_scorer)
    g.set_entry_point("first_pass_scorer")
    g.add_edge("first_pass_scorer", "self_critique_scorer")
    g.add_edge("self_critique_scorer", END)

    from backend.app.agents.base import get_checkpointer

    cp = await get_checkpointer()
    return g.compile(checkpointer=cp)
