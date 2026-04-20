from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.dependencies import get_current_user
from backend.app.database import get_db
from backend.app.main import create_app
from backend.models import Base
from backend.models.user import User
from backend.models.workflow_run import WorkflowRun


def build_test_client():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    db = TestingSessionLocal()

    user = User(email="social-owner@example.com", hashed_password="hashed", role="user", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, user


def test_start_trend_discovery_creates_queued_job(monkeypatch) -> None:
    from backend.app.api.routes import workflows as workflow_routes

    client, db, user = build_test_client()
    monkeypatch.setattr(
        workflow_routes.discover_social_trends_task,
        "delay",
        lambda **kwargs: SimpleNamespace(id="celery-trend-1"),
    )

    response = client.post(
        "/api/workflows/start-trend-discovery",
        json={"topic": "Small Business Marketing", "platforms": ["linkedin"], "limit": 8},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "started"
    assert payload["job_id"].startswith("trend_")

    run = db.get(WorkflowRun, payload["workflow_run_id"])
    assert run is not None
    assert run.status == "queued"
    assert run.workflow_name == "social-trend-discovery"
    assert "celery-trend-1" in (run.payload or "")
    assert run.user_id == user.id


def test_start_trend_discovery_blocks_duplicate_active_job(monkeypatch) -> None:
    from backend.app.api.routes import workflows as workflow_routes

    client, db, user = build_test_client()
    monkeypatch.setattr(
        workflow_routes.discover_social_trends_task,
        "delay",
        lambda **kwargs: SimpleNamespace(id="celery-trend-2"),
    )

    first_response = client.post(
        "/api/workflows/start-trend-discovery",
        json={"topic": "Lead Generation", "platforms": ["instagram"], "limit": 5},
    )
    duplicate_response = client.post(
        "/api/workflows/start-trend-discovery",
        json={"topic": "Lead Generation", "platforms": ["instagram"], "limit": 5},
    )

    assert first_response.status_code == 202
    assert duplicate_response.status_code == 409
    detail = duplicate_response.json()["detail"]
    assert detail["message"] == "Trend discovery is already running"
    assert detail["job_id"] == first_response.json()["job_id"]


def test_workflow_status_promotes_started_task_to_running(monkeypatch) -> None:
    from backend.app.api.routes import workflows as workflow_routes

    client, db, user = build_test_client()
    run = WorkflowRun(
        user_id=user.id,
        domain="social",
        workflow_name="social-trend-discovery",
        trigger_source="user",
        status="queued",
        payload='{"task_id":"celery-trend-3"}',
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    monkeypatch.setattr(
        workflow_routes.celery_app,
        "AsyncResult",
        lambda task_id: SimpleNamespace(state="STARTED", result=None),
    )

    response = client.get(f"/api/workflows/status/trend_{run.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    db.refresh(run)
    assert run.status == "running"


def test_stop_workflow_revokes_task_and_marks_run_stopped(monkeypatch) -> None:
    from backend.app.api.routes import workflows as workflow_routes

    client, db, user = build_test_client()
    run = WorkflowRun(
        user_id=user.id,
        domain="social",
        workflow_name="social-trend-discovery",
        trigger_source="user",
        status="running",
        payload='{"task_id":"celery-trend-4"}',
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    revoked = {}

    def fake_revoke(task_id, terminate=False):
        revoked["task_id"] = task_id
        revoked["terminate"] = terminate

    monkeypatch.setattr(workflow_routes.celery_app.control, "revoke", fake_revoke)

    response = client.post(f"/api/workflows/stop/trend_{run.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert revoked == {"task_id": "celery-trend-4", "terminate": True}
    db.refresh(run)
    assert run.status == "stopped"
    assert run.completed_at is not None


def test_list_workflows_includes_payload_for_recent_runs() -> None:
    client, db, user = build_test_client()
    run = WorkflowRun(
        user_id=user.id,
        domain="social",
        workflow_name="social-trend-discovery",
        trigger_source="user",
        status="completed",
        payload='{"topic":"Founder content","platforms":["linkedin"],"limit":4}',
    )
    db.add(run)
    db.commit()

    response = client.get("/api/workflows/")

    assert response.status_code == 200
    recent_runs = response.json()["recent_runs"]
    trend_run = next(item for item in recent_runs if item["workflow_name"] == "social-trend-discovery")
    assert trend_run["payload"]["topic"] == "Founder content"
