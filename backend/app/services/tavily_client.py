"""Tavily intent signals client helpers.

This module provides small async helpers to fetch intent signals from
Tavily for a user or a lead. In CI and tests the functions are typically
monkeypatched so the real HTTP integration is optional.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from backend.app.config import get_settings

log = logging.getLogger("tavily_client")
settings = get_settings()


async def get_user_intent_signals(user_id: str) -> Dict[str, Any]:
    """Return aggregated intent signals for a user (accounts/segments).

    If `TAVILY_API_KEY` is not set this returns an empty dict.
    """
    if not getattr(settings, "TAVILY_API_KEY", ""):
        return {}

    try:
        url = "https://api.tavily.ai/v1/intent/user"
        headers = {"Authorization": f"Bearer {settings.TAVILY_API_KEY}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params={"user_id": user_id})
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # pragma: no cover - network calls
        log.exception("tavily_user_signals_failed")
        return {}


async def get_intent_signals_for_lead(lead_identifier: str) -> Dict[str, Any]:
    """Return intent signals for a lead (email or company)."""
    if not getattr(settings, "TAVILY_API_KEY", ""):
        return {}

    try:
        url = "https://api.tavily.ai/v1/intent/lead"
        headers = {"Authorization": f"Bearer {settings.TAVILY_API_KEY}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params={"q": lead_identifier})
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # pragma: no cover - network calls
        log.exception("tavily_lead_signals_failed")
        return {}
