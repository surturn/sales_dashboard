from types import SimpleNamespace

import pytest

from backend.app.agents.lead_discovery import score_leads


@pytest.mark.asyncio
async def test_score_leads_uses_compiled_scorer_graph(monkeypatch):
    async def fake_build_scorer_graph():
        class FakeGraph:
            async def ainvoke(self, state):
                return {
                    **state,
                    "critiqued_leads": [
                        {
                            **state["leads_to_score"][0],
                            "score": 91,
                            "score_rationale": "excellent fit",
                            "score_critique": "validated",
                        }
                    ],
                    "errors": [],
                }

        return FakeGraph()

    monkeypatch.setattr(
        "backend.app.agents.lead_scorer.build_scorer_graph",
        fake_build_scorer_graph,
    )

    state = {
        "user_id": "u1",
        "icp_profile": {"industry": "tech"},
        "raw_google_leads": [],
        "raw_linkedin_leads": [],
        "raw_apollo_leads": [],
        "tavily_signals": [],
        "triangulated_leads": [],
        "deduplicated_leads": [
            {
                "email": "a@example.com",
                "name": "Alice",
                "company": "Acme",
                "title": "CEO",
                "industry": "tech",
                "linkedin_url": None,
                "phone": None,
                "sources": ["apollo", "linkedin"],
                "signal_tags": ["HIRING"],
                "score": None,
                "score_rationale": None,
                "score_critique": None,
            }
        ],
        "hubspot_results": [],
        "errors": [],
        "run_id": "run-1",
    }

    result = await score_leads(state)

    assert result["deduplicated_leads"][0]["score"] == 91
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_score_leads_falls_back_to_direct_nodes(monkeypatch):
    async def fake_first_pass(state):
        scored = [{**state["leads_to_score"][0], "score": 72, "score_rationale": "good fit"}]
        return {**state, "scored_leads": scored, "errors": []}

    async def fake_critic(state):
        critiqued = [{**state["scored_leads"][0], "score": 70, "score_critique": "slight mismatch"}]
        return {**state, "critiqued_leads": critiqued, "errors": []}

    async def broken_graph():
        raise RuntimeError("compiled scorer unavailable")

    monkeypatch.setattr(
        "backend.app.agents.lead_scorer.build_scorer_graph",
        broken_graph,
    )
    monkeypatch.setattr("backend.app.agents.lead_scorer.first_pass_scorer", fake_first_pass)
    monkeypatch.setattr("backend.app.agents.lead_scorer.self_critique_scorer", fake_critic)

    state = {
        "user_id": "u1",
        "icp_profile": {"industry": "tech"},
        "raw_google_leads": [],
        "raw_linkedin_leads": [],
        "raw_apollo_leads": [],
        "tavily_signals": [],
        "triangulated_leads": [],
        "deduplicated_leads": [
            {
                "email": "a@example.com",
                "name": "Alice",
                "company": "Acme",
                "title": "CEO",
                "industry": "tech",
                "linkedin_url": None,
                "phone": None,
                "sources": ["apollo"],
                "signal_tags": [],
                "score": None,
                "score_rationale": None,
                "score_critique": None,
            }
        ],
        "hubspot_results": [],
        "errors": [],
        "run_id": "run-1",
    }

    result = await score_leads(state)

    assert result["deduplicated_leads"][0]["score"] == 70
    assert result["deduplicated_leads"][0]["score_critique"] == "slight mismatch"
