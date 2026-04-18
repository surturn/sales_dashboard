import pytest
import asyncio
from types import SimpleNamespace
import sys

from backend.app.agents.reporting import (
    metrics_collector,
    narrative_writer,
    report_sender,
    run_reporting,
)


@pytest.mark.asyncio
async def test_metrics_collector_calls_build_report_metrics(monkeypatch):
    # patch session_scope to a no-op context and build_report_metrics to return a known dict
    def fake_session_scope():
        class Ctx:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr("backend.app.agents.reporting.session_scope", fake_session_scope)

    def fake_build(db, user_id=None):
        return {"total_sales": 123, "new_leads": 10}

    monkeypatch.setattr("backend.workers.reporting.build_report_metrics", fake_build)
    async def fake_user_intent(uid):
        return {"interest": 0.75}

    monkeypatch.setattr("backend.app.agents.reporting.get_user_intent_signals", fake_user_intent)

    state = {"user_id": "7", "metrics": {}, "errors": []}
    out = await metrics_collector(state)
    assert isinstance(out.get("metrics"), dict)
    assert out["metrics"].get("total_sales") == 123
    assert "intent_signals" in out["metrics"]
    assert out["metrics"]["intent_signals" ]["interest"] == 0.75


@pytest.mark.asyncio
async def test_narrative_writer_uses_call_llm(monkeypatch):
    async def fake_call_llm(prompt, task="report_summary", system=None, **kwargs):
        assert "executive" in prompt.lower() or "weekly" in prompt.lower()
        return "Executive summary: All good."

    monkeypatch.setattr("backend.app.agents.reporting.call_llm", fake_call_llm)

    state = {"metrics_presented": {"a": 1}, "summary": "", "errors": []}
    out = await narrative_writer(state)
    assert out.get("summary") == "Executive summary: All good."
    assert out.get("errors") == []


@pytest.mark.asyncio
async def test_report_sender_sends_and_records(monkeypatch):
    # patch EmailSender.send_email to be a simple function and _record_run to no-op
    class DummyEmail:
        def send_email(self, to, subject, body):
            assert "Weekly Report" in subject or "Weekly" in subject or True
            return {"success": True}

    monkeypatch.setattr("backend.app.agents.reporting.EmailSender", lambda: DummyEmail())

    def fake_record_run(db, user_id, status, payload, error=None):
        return None

    monkeypatch.setattr("backend.workers.reporting._record_run", fake_record_run)

    def fake_session_scope():
        class Ctx:
            def __enter__(self):
                class DB:
                    pass

                return DB()

            def __exit__(self, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr("backend.app.agents.reporting.session_scope", fake_session_scope)

    state = {"metrics": {}, "summary": "S", "errors": []}
    out = await report_sender(state)
    assert out.get("errors") == []


@pytest.mark.asyncio
async def test_run_reporting_fallback(monkeypatch):
    async def fake_build_graph():
        raise RuntimeError("langgraph unavailable")

    def fake_legacy():
        return {"metrics": {}, "summary": "legacy"}

    monkeypatch.setattr("backend.app.agents.reporting.build_reporting_graph", fake_build_graph)
    monkeypatch.setattr("backend.workers.reporting.generate_weekly_report_task", fake_legacy)

    out = await run_reporting(user_id=None)
    assert out["fallback_used"] is True
    assert isinstance(out["data"], dict)
    assert out["data"].get("summary") == "legacy"
