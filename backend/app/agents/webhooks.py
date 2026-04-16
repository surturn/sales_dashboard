"""Agent webhook handlers used by scheduler and API routes."""

from __future__ import annotations

from typing import Iterable


def handle_hubspot_events(events: Iterable[dict]) -> bool:
    """HubSpot webhook agent flow is not implemented yet."""
    return False


async def handle_chatwoot_event(payload: dict) -> bool:
    """Process Chatwoot support webhooks via the Phase 6 support agent."""
    from backend.app.agents.support import run_support

    result = await run_support(payload)
    return bool(result.get("success"))
