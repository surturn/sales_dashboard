"""Structured observability: structlog + Sentry + LangChain callback.

Call `init_logging()` and `init_sentry()` once at application startup
(see `backend/app/main.py`). Agents and LangGraph nodes should use
`get_logger()` exclusively for structured logs.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import structlog
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from langchain_core.callbacks import BaseCallbackHandler

from backend.app.config import get_settings

settings = get_settings()


def init_sentry() -> None:
    """Call once in backend/app/main.py startup."""
    dsn = getattr(settings, "SENTRY_DSN", "")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=getattr(settings, "SENTRY_ENVIRONMENT", "development"),
        integrations=[FastApiIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
    )


def init_logging() -> None:
    """Call once in backend/app/main.py startup."""
    logging.basicConfig(level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def get_logger(name: str):
    return structlog.get_logger(name)


class AgentObservabilityCallback(BaseCallbackHandler):
    """
    LangChain/LangGraph callback that logs every node entry and exit.

    Pass as: graph.compile(checkpointer=cp, callbacks=[AgentObservabilityCallback(agent_name, user_id)])
    Emits structured logs readable by any log aggregator (Datadog, CloudWatch, etc.)
    """

    def __init__(self, agent_name: str, user_id: str):
        self.agent_name = agent_name
        self.user_id = user_id
        self.log = get_logger("agent_callback")
        self._timers: dict[str, float] = {}

    def on_chain_start(self, serialized: Any, inputs: Any, **kwargs) -> None:
        node = serialized.get("name", "unknown") if isinstance(serialized, dict) else "unknown"
        self._timers[node] = time.time()
        self.log.info("agent_node_start", agent=self.agent_name,
                      node=node, user_id=self.user_id)

    def on_chain_end(self, outputs: Any, **kwargs) -> None:
        node = kwargs.get("name", "unknown")
        elapsed = time.time() - self._timers.get(node, time.time())
        self.log.info("agent_node_end", agent=self.agent_name,
                      node=node, user_id=self.user_id, elapsed_ms=round(elapsed*1000))

    def on_chain_error(self, error: Exception, **kwargs) -> None:
        node = kwargs.get("name", "unknown")
        self.log.error("agent_node_error", agent=self.agent_name,
                       node=node, user_id=self.user_id, error=str(error))
        sentry_sdk.capture_exception(error)
