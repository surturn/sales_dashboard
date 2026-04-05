"""LangGraph node LLM router (Groq primary, OpenAI fallback).

This module is intended for use inside LangGraph agent nodes. It uses
Redis for short-term result caching and prefers Groq where available,
falling back to a ChatOpenAI invocation when Groq fails.

Important: the project's legacy `OpenAIClient` remains unchanged and is
still used by the synchronous workers; this router is async-only for
agent usage.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Optional

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
import redis.asyncio as aioredis

from backend.app.config import get_settings
from backend.app.core.observability import get_logger

settings = get_settings()
log = get_logger(__name__)

# Task → model mapping.
# score_fast: cheap + fast for bulk scoring (up to 500 leads/day)
# score_critic: used only on top 20% of leads after first-pass scoring
# email_draft, support_reply, report: fast model is sufficient
TASK_MODEL_MAP: dict[str, str] = {
    "score_fast":     settings.GROQ_MODEL_FAST,
    "score_critic":   settings.GROQ_MODEL_LARGE,
    "email_draft":    settings.GROQ_MODEL_FAST,
    "email_critique": settings.GROQ_MODEL_FAST,
    "support_reply":  settings.GROQ_MODEL_FAST,
    "report_summary": settings.GROQ_MODEL_FAST,
    "icp_analysis":   settings.GROQ_MODEL_FAST,
}


async def call_llm(
    prompt: str,
    system: str = "",
    task: str = "score_fast",
    redis_client: aioredis.Redis | None = None,
    force_json: bool = False,
) -> str:
    """
    Single entry point for all LLM calls in LangGraph nodes.
    Returns the model response as a plain string.
    Raises RuntimeError if both Groq and OpenAI fail.
    """
    # 1. Build cache key from task + prompt hash (not user_id: cache is shared)
    cache_key = f"llm:{task}:{hashlib.sha256(prompt.encode()).hexdigest()[:16]}"

    # 2. Check Redis cache
    if redis_client:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                log.debug("llm_cache_hit", task=task)
                # redis async returns bytes
                return cached.decode()
        except Exception:
            log.exception("redis_cache_check_failed")

    # 3. Attempt Groq (primary)
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    model_name = TASK_MODEL_MAP.get(task, settings.GROQ_MODEL_FAST)

    try:
        groq = ChatGroq(
            model=model_name,
            api_key=settings.GROQ_API_KEY,
            max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
        )
        result = await groq.ainvoke(messages)
        text = result.content
        log.info("llm_groq_success", task=task, model=model_name, tokens=len(prompt.split()))

    except Exception as groq_err:
        # 4. Groq failed (rate limit, network, etc.) — fall back to OpenAI
        log.warning("llm_groq_failed_fallback", task=task, error=str(groq_err))
        try:
            oai = ChatOpenAI(
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                api_key=settings.OPENAI_API_KEY,
                max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
            )
            result = await oai.ainvoke(messages)
            text = result.content
            log.info("llm_openai_fallback_success", task=task)
        except Exception as oai_err:
            log.error("llm_all_providers_failed", groq_err=str(groq_err), oai_err=str(oai_err))
            raise RuntimeError(f"All LLM providers failed: {groq_err} | {oai_err}")

    # 5. Write to cache
    if redis_client:
        try:
            await redis_client.setex(cache_key, settings.LLM_CACHE_TTL_SECONDS, text)
        except Exception:
            log.exception("redis_cache_write_failed")

    return text
