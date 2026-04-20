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
from backend.app.core.retry import with_retry, circuit_breaker

settings = get_settings()
log = get_logger(__name__)

# Task → LLM provider mapping.
# Groq (fast/cheap): bulk scoring, drafting, summaries
# OpenAI (reasoning): critique, self-evaluation, complex reasoning
TASK_PROVIDER_MAP: dict[str, str] = {
    # Fast tasks → Groq (cheap, fast inference)
    "score_fast":     "groq",      # Bulk lead scoring
    "email_draft":    "groq",      # Email body generation
    "support_reply":  "groq",      # Support response drafting
    "report_summary": "groq",      # Weekly report narrative
    "icp_analysis":   "groq",      # Cold-start ICP synthesis
    
    # Reasoning/Critique tasks → OpenAI (better reasoning)
    "score_critic":   "openai",    # Lead score critique & adjustment
    "email_critique": "openai",    # Email quality critique & refinement
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

    # 3. Determine provider based on task type
    messages = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    provider = TASK_PROVIDER_MAP.get(task, "groq")
    
    # 4. Try primary provider first
    if provider == "openai":
        # Critique & reasoning → OpenAI (better for complex reasoning)
        try:
            @with_retry(service="openai")
            async def _invoke_openai(msgs):
                oai = ChatOpenAI(
                    model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                    api_key=settings.OPENAI_API_KEY,
                    max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
                )
                return await oai.ainvoke(msgs)
            
            result = await _invoke_openai(messages)
            text = result.content
            log.info("llm_openai_success", task=task, model="gpt-4o-mini")
        except Exception as oai_err:
            log.warning("llm_openai_failed_fallback", task=task, error=str(oai_err))
            # OpenAI failed → fallback to Groq for critique
            try:
                @with_retry(service="groq")
                async def _invoke_groq_fallback(msgs):
                    groq = ChatGroq(
                        model=settings.GROQ_MODEL_LARGE,
                        api_key=settings.GROQ_API_KEY,
                        max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
                    )
                    return await groq.ainvoke(msgs)
                
                result = await _invoke_groq_fallback(messages)
                text = result.content
                log.info("llm_groq_fallback_success", task=task)
            except Exception as groq_err:
                log.error("llm_all_providers_failed", openai_err=str(oai_err), groq_err=str(groq_err))
                raise RuntimeError(f"All LLM providers failed: OpenAI: {oai_err} | Groq: {groq_err}")
    else:
        # Fast tasks → Groq (cheap, fast)
        try:
            @with_retry(service="groq")
            async def _invoke_groq(msgs):
                groq = ChatGroq(
                    model=settings.GROQ_MODEL_FAST,
                    api_key=settings.GROQ_API_KEY,
                    max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
                )
                return await groq.ainvoke(msgs)
            
            result = await _invoke_groq(messages)
            text = result.content
            log.info("llm_groq_success", task=task, model=settings.GROQ_MODEL_FAST)
        except Exception as groq_err:
            log.warning("llm_groq_failed_fallback", task=task, error=str(groq_err))
            # Groq failed → fallback to OpenAI
            try:
                @with_retry(service="openai")
                async def _invoke_openai_fallback(msgs):
                    oai = ChatOpenAI(
                        model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                        api_key=settings.OPENAI_API_KEY,
                        max_tokens=settings.LLM_MAX_TOKENS_PER_NODE,
                    )
                    return await oai.ainvoke(msgs)
                
                result = await _invoke_openai_fallback(messages)
                text = result.content
                log.info("llm_openai_fallback_success", task=task)
            except Exception as oai_err:
                log.error("llm_all_providers_failed", groq_err=str(groq_err), openai_err=str(oai_err))
                raise RuntimeError(f"All LLM providers failed: Groq: {groq_err} | OpenAI: {oai_err}")

    # 5. Write to cache
    if redis_client:
        try:
            await redis_client.setex(cache_key, settings.LLM_CACHE_TTL_SECONDS, text)
        except Exception:
            log.exception("redis_cache_write_failed")

    return text
