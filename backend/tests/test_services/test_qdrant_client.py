from types import SimpleNamespace

import pytest

from backend.app.services.qdrant_client import ensure_collections, search_kb
from backend.app.config import get_settings


@pytest.mark.asyncio
async def test_ensure_collections_creates_missing_sets():
    settings = get_settings()

    class FakeClient:
        def __init__(self):
            self.created = []

        async def get_collections(self):
            return SimpleNamespace(
                collections=[SimpleNamespace(name=settings.QDRANT_COLLECTION_LEADS)]
            )

        async def create_collection(self, collection_name, vectors_config):
            self.created.append((collection_name, vectors_config.size, vectors_config.distance))

    client = FakeClient()

    await ensure_collections(client)

    created_names = [name for name, _, _ in client.created]
    assert settings.QDRANT_COLLECTION_SUPPORT_KB in created_names
    assert settings.QDRANT_COLLECTION_ICP in created_names
    assert settings.QDRANT_COLLECTION_LEADS not in created_names


@pytest.mark.asyncio
async def test_search_kb_returns_chunk_texts_and_user_scope():
    captured = {}

    class FakeClient:
        async def search(self, **kwargs):
            captured.update(kwargs)
            return [
                SimpleNamespace(payload={"text": "Chunk A"}, score=0.9),
                SimpleNamespace(payload={"text": "Chunk B"}, score=0.8),
            ]

    chunks = await search_kb(FakeClient(), [0.1, 0.2], user_id="15", top_k=2)

    assert chunks == ["Chunk A", "Chunk B"]
    assert captured["limit"] == 2
    assert captured["query_filter"].must[0].key == "user_id"
    assert captured["query_filter"].must[0].match.value == "15"
