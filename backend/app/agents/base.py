"""Shared agent base definitions.

This module exposes the small set of types and helpers that every agent
imports: the `AgentResult` wrapper, common `LeadRecord` schema, a
`make_thread_id` helper, and an async `get_checkpointer()` factory that
returns a LangGraph-compatible Redis checkpointer.

The Redis checkpointer package is intentionally optional. The repo can
still run agents with graceful fallback behaviour when that package is
absent, which keeps local development and CI unblocked while the graph
logic continues to mature.
"""

from __future__ import annotations

from typing import TypedDict, Optional, Any
import importlib
import uuid

from backend.app.config import get_settings

settings = get_settings()





class AgentResult(TypedDict):
    """Standard result returned by agents.

    - `success`: whether the agent completed successfully
    - `data`: agent-specific payload (often the final state)
    - `error`: optional error message when `success` is False
    - `fallback_used`: whether the legacy fallback was invoked
    - `run_id`: unique id for this run
    - `agent_name`: human-friendly agent identifier
    """

    success: bool
    data: Any
    error: Optional[str]
    fallback_used: bool
    run_id: str
    agent_name: str


async def get_checkpointer() -> Any:
    """Create and return an AsyncRedisSaver connected to `settings.REDIS_URL`.

    The returned object implements the checkpointer interface expected by
    LangGraph graphs (async setup + async save/load). If the optional
    Redis saver package is not installed, a RuntimeError is raised with a
    clear message and callers can fall back to non-checkpointer paths.
    """
    try:
        redis_checkpoint_module = importlib.import_module("langgraph.checkpoint.redis.aio")
        async_redis_saver = getattr(redis_checkpoint_module, "AsyncRedisSaver", None)
    except Exception as exc:
        raise RuntimeError(
            "LangGraph AsyncRedisSaver is not available. Install the optional "
            "'langgraph-checkpoint-redis' package to enable durable agent checkpoints."
        ) from exc

    if async_redis_saver is None:
        raise RuntimeError(
            "LangGraph AsyncRedisSaver could not be imported from "
            "'langgraph.checkpoint.redis.aio'."
        )

    checkpointer = async_redis_saver.from_conn_string(settings.REDIS_URL)
    # Ensure any internal async setup is performed before returning.
    await checkpointer.asetup()
    return checkpointer


def make_thread_id(agent_name: str, user_id: str) -> str:
    """Return a concise thread id for grouping checkpoints and logs.

    Prefixed with the agent name to make traces easier to read in Flower
    and other task UIs.
    """

    return f"{agent_name}:{user_id}:{uuid.uuid4().hex[:8]}"


class LeadRecord(TypedDict):
    """Canonical lead record shared across agents and nodes.

    Fields are intentionally permissive because data comes from multiple
    third-party sources with varying schemas. Agents may extend this at
    runtime with additional keys.
    """

    email: str
    name: str
    company: str
    title: str
    industry: str
    linkedin_url: Optional[str]
    phone: Optional[str]
    sources: list[str]
    signal_tags: list[str]
    score: Optional[int]
    score_rationale: Optional[str]
    score_critique: Optional[str]

