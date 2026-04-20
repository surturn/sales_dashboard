"""Small datetime helpers for consistent UTC handling.

Provides helpers to convert datetimes to UTC and compute elapsed seconds
while tolerating naive datetimes created by legacy code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def elapsed_seconds(start: datetime | None, end: datetime | None) -> Optional[float]:
    s = to_utc(start)
    e = to_utc(end)
    if s is None or e is None:
        return None
    return (e - s).total_seconds()
