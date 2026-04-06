"""Minimal agent entrypoint shims used by scheduler and webhooks.

These functions attempt to call a full agent implementation (if present)
and return True when the agent handled the request. If the agent
module/function is not available or raises, they return False so the
caller can fall back to existing Celery workers.
"""

from __future__ import annotations

import importlib
import inspect
import asyncio
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _call_maybe_async(func, *args, **kwargs) -> Any:
    if inspect.iscoroutinefunction(func):
        return asyncio.run(func(*args, **kwargs))
    return func(*args, **kwargs)


def try_run_lead_sourcing(query: str | None = None, user_id: int | None = None) -> bool:
    """Try to run a lead sourcing agent. Return True if handled."""
    try:
        mod = importlib.import_module("backend.app.agents.lead_discovery")
        run = getattr(mod, "run_lead_discovery", None)
        if not run:
            return False
        _call_maybe_async(run, user_id=user_id, query=query)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Lead discovery agent not available or failed: %s", exc)
        return False


def try_run_weekly_report() -> bool:
    """Try to run the reporting agent. Return True if handled."""
    try:
        mod = importlib.import_module("backend.app.agents.reporting")
        run = getattr(mod, "run_reporting", None)
        if not run:
            return False
        _call_maybe_async(run)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Reporting agent not available or failed: %s", exc)
        return False


def try_handle_hubspot_events(events: Iterable[dict]) -> bool:
    """Try to let agents handle HubSpot webhook events. Return True if handled."""
    try:
        mod = importlib.import_module("backend.app.agents.webhooks")
        handler = getattr(mod, "handle_hubspot_events", None)
        if not handler:
            return False
        return bool(_call_maybe_async(handler, events))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("HubSpot webhook agent handler not available or failed: %s", exc)
        return False


def try_handle_chatwoot_event(payload: dict) -> bool:
    try:
        mod = importlib.import_module("backend.app.agents.webhooks")
        handler = getattr(mod, "handle_chatwoot_event", None)
        if not handler:
            return False
        return bool(_call_maybe_async(handler, payload))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Chatwoot webhook agent handler not available or failed: %s", exc)
        return False
