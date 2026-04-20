"""Qdrant client helpers for semantic memory collections."""

from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from backend.app.config import get_settings

settings = get_settings()
EMBEDDING_DIM = 384


async def get_qdrant() -> AsyncQdrantClient:
    """Return a configured async Qdrant client."""
    return AsyncQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        api_key=settings.QDRANT_API_KEY or None,
    )


async def ensure_collections(client: AsyncQdrantClient) -> None:
    """Create the Phase 6 collections when they do not already exist."""
    collection_names = (
        settings.QDRANT_COLLECTION_LEADS,
        settings.QDRANT_COLLECTION_SUPPORT_KB,
        settings.QDRANT_COLLECTION_ICP,
    )
    existing = {collection.name for collection in (await client.get_collections()).collections}
    for name in collection_names:
        if name in existing:
            continue
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


async def upsert_lead_embedding(client: AsyncQdrantClient, lead: dict[str, Any], embedding: list[float]) -> None:
    """Store a lead vector for semantic deduplication."""
    await client.upsert(
        collection_name=settings.QDRANT_COLLECTION_LEADS,
        points=[
            PointStruct(
                id=lead["id"],
                vector=embedding,
                payload={
                    "user_id": str(lead["user_id"]),
                    "email": lead.get("email"),
                    "company": lead.get("company"),
                    "score": lead.get("score", 0),
                },
            )
        ],
    )


async def search_similar_leads(
    client: AsyncQdrantClient,
    query_embedding: list[float],
    user_id: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return similar leads for the same user only."""
    results = await client.search(
        collection_name=settings.QDRANT_COLLECTION_LEADS,
        query_vector=query_embedding,
        query_filter=Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return [{"score": result.score, **(result.payload or {})} for result in results]


async def upsert_kb_chunk(
    client: AsyncQdrantClient,
    chunk_id: str,
    text: str,
    embedding: list[float],
    user_id: str,
) -> None:
    """Store one support knowledge-base chunk."""
    await client.upsert(
        collection_name=settings.QDRANT_COLLECTION_SUPPORT_KB,
        points=[
            PointStruct(
                id=chunk_id,
                vector=embedding,
                payload={"user_id": str(user_id), "text": text},
            )
        ],
    )


async def search_kb(
    client: AsyncQdrantClient,
    query_embedding: list[float],
    user_id: str,
    top_k: int = 3,
) -> list[str]:
    """Retrieve the top support KB chunks for a user."""
    results = await client.search(
        collection_name=settings.QDRANT_COLLECTION_SUPPORT_KB,
        query_vector=query_embedding,
        query_filter=Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
        ),
        limit=top_k,
        with_payload=True,
    )
    return [str((result.payload or {}).get("text", "")) for result in results if (result.payload or {}).get("text")]
