import json
import pytest
import asyncio
from types import SimpleNamespace

from backend.app.agents.reporting import icp_updater


@pytest.mark.asyncio
async def test_icp_updater_no_conversions(monkeypatch):
    # fake session_scope that yields a DB whose execute().fetchall() returns []
    def fake_session_scope():
        class _Ctx:
            def __enter__(self):
                class _DB:
                    def execute(self, *args, **kwargs):
                        class _R:
                            def fetchall(self):
                                return []
                        return _R()
                return _DB()

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()

    monkeypatch.setattr("backend.app.agents.reporting.session_scope", fake_session_scope)

    state = {"user_id": "42", "metrics": {}, "metrics_presented": {}, "summary": "", "icp_updated": False, "conversions_this_week": 0, "errors": [], "run_id": "r1"}

    out = await icp_updater(state)
    assert out.get("icp_updated") is False


@pytest.mark.asyncio
async def test_icp_updater_with_conversions(monkeypatch):
    # Prepare a fake converted lead row
    converted = [{"id": 123, "industry": "tech", "title": "CEO", "company": "Acme", "name": "Alice"}]

    def fake_session_scope():
        class _Ctx:
            def __enter__(self):
                class _DB:
                    def execute(self, *args, **kwargs):
                        class _R:
                            def fetchall(self_inner):
                                return converted
                        return _R()
                return _DB()

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()

    async def fake_embed_lead(lead):
        assert lead.get("id") == 123
        return [0.1, 0.2, 0.3]

    class FakeClient:
        def __init__(self):
            self.upsert_calls = []
            self.closed = False

        async def upsert(self, collection_name, points):
            self.upsert_calls.append((collection_name, points))

        async def close(self):
            self.closed = True

    async def fake_get_qdrant():
        return FakeClient()

    monkeypatch.setattr("backend.app.agents.reporting.session_scope", fake_session_scope)
    # embed_lead is imported inside the node; ensure the embeddings module is available
    import sys
    sys.modules["backend.app.services.embeddings"] = SimpleNamespace(embed_lead=fake_embed_lead)
    # reporting module already imported get_qdrant at module-import time, patch that name
    monkeypatch.setattr("backend.app.agents.reporting.get_qdrant", fake_get_qdrant)

    state = {"user_id": "7", "metrics": {}, "metrics_presented": {}, "summary": "", "icp_updated": False, "conversions_this_week": 0, "errors": [], "run_id": "r2"}

    out = await icp_updater(state)
    assert out.get("icp_updated") is True
    assert out.get("conversions_this_week") == 1
