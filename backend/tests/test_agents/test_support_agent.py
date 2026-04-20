from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.agents.support import kb_retriever, run_support
from backend.models import Base, import_models
from backend.models.user import User
from backend.models.user_support_config import UserSupportConfig


@pytest.mark.asyncio
async def test_kb_retriever_uses_qdrant_chunks(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    fake_client = FakeClient()

    async def fake_embed_text(text):
        assert text == "How do I reset my password?"
        return [0.1, 0.2, 0.3]

    async def fake_get_qdrant():
        return fake_client

    async def fake_search_kb(client, query_embedding, user_id, top_k=3):
        assert client is fake_client
        assert query_embedding == [0.1, 0.2, 0.3]
        assert user_id == "7"
        assert top_k == 3
        return ["Step one", "Step two"]

    monkeypatch.setitem(
        sys.modules,
        "backend.app.services.embeddings",
        SimpleNamespace(embed_text=fake_embed_text),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.app.services.qdrant_client",
        SimpleNamespace(get_qdrant=fake_get_qdrant, search_kb=fake_search_kb),
    )

    state = {
        "user_id": "7",
        "account_id": None,
        "conversation_id": None,
        "conversation": {},
        "customer_message": "How do I reset my password?",
        "kb_context": "",
        "reply_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": "support-1",
    }

    result = await kb_retriever(state)

    assert result["kb_context"] == "Step one\n\nStep two"
    assert result["errors"] == []
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_kb_retriever_falls_back_to_postgres(monkeypatch):
    import_models()
    fd, db_file = tempfile.mkstemp(prefix="support_agent_", suffix=".db", dir=str(Path.cwd()))
    os.close(fd)
    db_path = Path(db_file)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with TestingSessionLocal() as db:
        user = User(email="support@example.com", hashed_password="hashed", role="user", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(UserSupportConfig(user_id=user.id, kb_text="Full KB fallback"))
        db.commit()

    @contextmanager
    def fake_session_scope():
        db = TestingSessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def fake_embed_text(_text):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setitem(
        sys.modules,
        "backend.app.services.embeddings",
        SimpleNamespace(embed_text=fake_embed_text),
    )
    monkeypatch.setattr("backend.app.agents.support.session_scope", fake_session_scope)

    state = {
        "user_id": str(user.id),
        "account_id": None,
        "conversation_id": None,
        "conversation": {},
        "customer_message": "Need help",
        "kb_context": "",
        "reply_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": "support-2",
    }

    result = await kb_retriever(state)

    assert result["kb_context"] == "Full KB fallback"
    assert any("qdrant_kb_fallback" in error for error in result["errors"])
    engine.dispose()
    db_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_run_support_falls_back_to_legacy_worker(monkeypatch):
    async def fake_build_graph():
        raise RuntimeError("langgraph unavailable")

    def fake_process(payload):
        assert payload["content"] == "Need help"
        return {"status": "processed"}

    monkeypatch.setattr("backend.app.agents.support.build_support_graph", fake_build_graph)
    monkeypatch.setattr("backend.domains.leads.workers.support.process_chatwoot_webhook", fake_process)

    result = await run_support({"content": "Need help", "conversation": {}})

    assert result["success"] is True
    assert result["fallback_used"] is True
    assert result["data"]["status"] == "processed"
