import json
import pytest

from backend.app.agents.lead_scorer import first_pass_scorer, self_critique_scorer


@pytest.mark.asyncio
async def test_first_pass_scorer_batches_and_scores(monkeypatch):
    async def fake_call_llm(prompt, task="score_fast", system=None, **kwargs):
        return json.dumps([
            {"index": 1, "score": 80, "rationale": "great fit"},
            {"index": 2, "score": 60, "rationale": "ok fit"},
        ])

    monkeypatch.setattr("backend.app.agents.lead_scorer.call_llm", fake_call_llm)

    state = {
        "user_id": "u1",
        "icp_profile": {"industry": "tech", "location": "US", "seniority": "founder", "keywords": []},
        "leads_to_score": [
            {"name": "Alice", "title": "CEO", "company": "Acme", "industry": "tech", "signal_tags": []},
            {"name": "Bob", "title": "CTO", "company": "Beta", "industry": "tech", "signal_tags": []},
        ],
        "scored_leads": [],
        "critiqued_leads": [],
        "errors": [],
    }

    out = await first_pass_scorer(state)
    assert "scored_leads" in out
    scored = out["scored_leads"]
    assert len(scored) == 2
    assert int(scored[0]["score"]) == 80
    assert int(scored[1]["score"]) == 60


@pytest.mark.asyncio
async def test_self_critique_adjusts_top_leads(monkeypatch):
    async def fake_critic(prompt, task="score_critic", system=None, **kwargs):
        return json.dumps([
            {"index": 1, "adjusted_score": 70, "critique": "wrong company"}
        ])

    monkeypatch.setattr("backend.app.agents.lead_scorer.call_llm", fake_critic)

    state = {
        "user_id": "u1",
        "icp_profile": {"industry": "tech", "location": "US", "seniority": "founder", "keywords": []},
        "scored_leads": [
            {"name": "Alice", "score": 80, "score_rationale": "great"},
            {"name": "Bob", "score": 60, "score_rationale": "ok"},
        ],
        "critiqued_leads": [],
        "leads_to_score": [],
        "errors": [],
    }

    out = await self_critique_scorer(state)
    assert "critiqued_leads" in out
    critiqued = out["critiqued_leads"]
    # Alice was top and should be adjusted to 70 with critique present
    assert any(l.get("score") == 70 and l.get("score_critique") == "wrong company" for l in critiqued)
