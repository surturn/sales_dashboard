"""Embedding helpers backed by sentence-transformers."""

from __future__ import annotations

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the embedding model once per process."""
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


async def embed_text(text: str) -> list[float]:
    """Embed arbitrary text without blocking the event loop."""
    loop = asyncio.get_running_loop()
    model = get_model()
    vector = await loop.run_in_executor(None, lambda: model.encode(text).tolist())
    return vector


async def embed_lead(lead: dict) -> list[float]:
    """Embed the lead fields used for semantic deduplication."""
    text = " ".join(
        [
            str(lead.get("name") or ""),
            str(lead.get("company") or ""),
            str(lead.get("title") or ""),
            str(lead.get("industry") or ""),
        ]
    ).strip()
    return await embed_text(text)
