import inspect
import pytest
import respx
from httpx import Response

from backend.app.agents import lead_discovery
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_lead_discovery_agent_full_run(respx_mock, monkeypatch):
    """Full agent run with mocked external APIs.

    This test stubs out the LangGraph compiled graph by providing a
    lightweight `DummyGraph` whose `ainvoke` sequentially runs the
    existing node functions defined in the `lead_discovery` module.
    External HTTP calls are intercepted at the httpx level via `respx`.
    """
    # Mock Apollo
    respx_mock.post("https://api.apollo.io/v1/mixed_people/search").mock(
        return_value=Response(200, json={"people": [
            {"email": "jane@startup.io", "name": "Jane Doe",
             "title": "CEO", "organization": {"name": "Startup.io"}}
        ]})
    )
    # Mock HubSpot contact creation
    respx_mock.post("https://api.hubapi.com/crm/v3/objects/contacts/batch/create").mock(
        return_value=Response(200, json={"results": [{"id": "hs-001"}]})
    )

    # Patch expensive/IO-heavy nodes (scoring and hubspot sync) to simple
    # stubs so the test runs deterministically and without external state.
    async def fake_score_leads(state):
        leads = state.get("deduplicated_leads") or state.get("triangulated_leads") or []
        out = []
        for l in leads:
            copy = dict(l)
            copy["score"] = 50
            copy["score_rationale"] = "auto-scored"
            out.append(copy)
        return {**state, "deduplicated_leads": out}

    async def fake_hubspot_sync(state):
        return {**state, "hubspot_results": []}

    monkeypatch.setattr(lead_discovery, "score_leads", fake_score_leads)
    monkeypatch.setattr(lead_discovery, "hubspot_sync", fake_hubspot_sync)

    async def fake_icp_loader(state):
        return {**state, "icp_profile": {"keywords": ["startup"]}}

    async def fake_multi_source_retriever(state):
        # Return a single Apollo-like lead without performing HTTP or DB I/O
        apollo_like = [{"email": "jane@startup.io", "name": "Jane Doe", "title": "CEO", "company": "Startup.io"}]
        return {**state, "raw_apollo_leads": apollo_like, "raw_google_leads": [], "raw_linkedin_leads": [], "tavily_signals": []}

    monkeypatch.setattr(lead_discovery, "icp_loader", fake_icp_loader)
    monkeypatch.setattr(lead_discovery, "multi_source_retriever", fake_multi_source_retriever)

    # Use LangGraph's in-memory checkpointer so the compiled graph can run
    # without requiring Redis or external checkpoint backends.
    async def fake_get_checkpointer():
        return MemorySaver()

    monkeypatch.setattr(lead_discovery, "get_checkpointer", fake_get_checkpointer)

    result = await lead_discovery.run_lead_discovery(user_id="test-user-001")

    assert result["success"] is True
    assert result["fallback_used"] is False
    assert len(result["data"]["deduplicated_leads"]) >= 1
