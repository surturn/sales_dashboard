import pytest

from backend.app.agents.outreach import context_builder, email_critic, email_drafter


def test_context_builder_creates_compact_prompt_context():
    state = {
        "user_id": "1",
        "lead": {
            "email": "lead@example.com",
            "name": "Ada Lovelace",
            "company": "Analytical Engines",
            "title": "Founder",
            "industry": "Software",
            "linkedin_url": None,
            "phone": None,
            "sources": ["apollo", "linkedin"],
            "signal_tags": ["HIRING"],
            "score": None,
            "score_rationale": None,
            "score_critique": None,
        },
        "contact_context": "",
        "email_draft": "",
        "critique_notes": "",
        "refined_draft": "",
        "approved": None,
        "final_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": "run-1",
    }

    result = context_builder(state)

    assert "Ada Lovelace" in result["contact_context"]
    assert "apollo, linkedin" in result["contact_context"]
    assert "HIRING" in result["contact_context"]


@pytest.mark.asyncio
async def test_email_drafter_uses_llm_router(monkeypatch):
    async def fake_call_llm(prompt, system="", task="email_draft", **kwargs):
        assert task == "email_draft"
        assert "Write a cold outreach email" in prompt
        return "Draft body"

    monkeypatch.setattr("backend.app.agents.outreach.call_llm", fake_call_llm)

    state = {
        "user_id": "1",
        "lead": {},
        "contact_context": "Name: Ada",
        "email_draft": "",
        "critique_notes": "",
        "refined_draft": "",
        "approved": None,
        "final_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": "run-1",
    }

    result = await email_drafter(state)
    assert result["email_draft"] == "Draft body"


@pytest.mark.asyncio
async def test_email_critic_refines_draft(monkeypatch):
    responses = iter(["Needs a stronger CTA", "Refined body"])

    async def fake_call_llm(prompt, system="", task="email_draft", **kwargs):
        return next(responses)

    monkeypatch.setattr("backend.app.agents.outreach.call_llm", fake_call_llm)

    state = {
        "user_id": "1",
        "lead": {},
        "contact_context": "",
        "email_draft": "Original body",
        "critique_notes": "",
        "refined_draft": "",
        "approved": None,
        "final_draft": "",
        "send_result": {},
        "errors": [],
        "run_id": "run-1",
    }

    result = await email_critic(state)
    assert result["critique_notes"] == "Needs a stronger CTA"
    assert result["refined_draft"] == "Refined body"
