from types import SimpleNamespace
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.dependencies import get_current_user
from backend.app.database import get_db
from backend.app.main import create_app
from backend.models import Base, import_models
from backend.models.outreach_approval_queue import OutreachApprovalQueue
from backend.models.user import User


def build_test_app():
    import_models()
    tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(tmpdir.name) / "approvals_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", future=True, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = TestingSessionLocal()

    user = User(email="owner@example.com", hashed_password="hashed", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    current_user = SimpleNamespace(id=user.id, email=user.email, is_active=True)

    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return app, db, current_user, tmpdir


def test_list_pending_approvals_returns_queue_rows():
    app, db, user, tmpdir = build_test_app()
    try:
        db.add(
            OutreachApprovalQueue(
                id="draft-1",
                user_id=user.id,
                lead_id=None,
                lead_email="lead@example.com",
                draft="Draft body",
                final_draft=None,
                status="pending",
                thread_id="thread-1",
            )
        )
        db.commit()

        client = TestClient(app)
        response = client.get("/api/approvals/pending")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["pending"]) == 1
        assert payload["pending"][0]["lead_email"] == "lead@example.com"
    finally:
        db.close()
        tmpdir.cleanup()


def test_approve_and_reject_resume_graph(monkeypatch):
    app, db, user, tmpdir = build_test_app()
    try:
        db.add(
            OutreachApprovalQueue(
                id="draft-2",
                user_id=user.id,
                lead_id=None,
                lead_email="lead@example.com",
                draft="Draft body",
                final_draft=None,
                status="pending",
                thread_id="thread-2",
            )
        )
        db.commit()

        class FakeGraph:
            def __init__(self):
                self.updated = []
                self.invoked = []

            async def aupdate_state(self, config, values, as_node=None):
                self.updated.append((config, values, as_node))
                return config

            async def ainvoke(self, value, config=None):
                self.invoked.append((value, config))
                return {"status": "ok"}

        fake_graph = FakeGraph()

        async def fake_build_graph():
            return fake_graph

        monkeypatch.setattr("backend.app.agents.outreach.build_outreach_graph", fake_build_graph)

        client = TestClient(app)

        approve = client.post("/api/approvals/draft-2/approve", json={"final_draft": "Edited draft"})
        assert approve.status_code == 200
        assert fake_graph.updated[0][1]["approved"] is True
        assert fake_graph.updated[0][2] == "approval_gate"

        db.add(
            OutreachApprovalQueue(
                id="draft-3",
                user_id=user.id,
                lead_id=None,
                lead_email="lead2@example.com",
                draft="Draft body 2",
                final_draft=None,
                status="pending",
                thread_id="thread-3",
            )
        )
        db.commit()

        reject = client.post("/api/approvals/draft-3/reject")
        assert reject.status_code == 200
        assert fake_graph.updated[1][1]["approved"] is False
    finally:
        db.close()
        tmpdir.cleanup()
