"""Agent webhook handlers (stubs).

These handlers are minimal and return False so the existing webhook
dispatch/task flow remains the primary path. Implement full agent
handlers here in later phases; this module provides the import target
used by `backend.app.agents.entrypoints`.
"""

from __future__ import annotations

from typing import Iterable


def handle_hubspot_events(events: Iterable[dict]) -> bool:
    """Attempt to process HubSpot events with an agent.

    Phase 1: noop stub — return False to indicate fallback should run.
    """
    return False


def handle_chatwoot_event(payload: dict) -> bool:
    """Attempt to process Chatwoot event with an agent. Phase 1 stub."""
    return False
