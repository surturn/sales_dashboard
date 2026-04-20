from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chains.base import LangChainDependencyError, build_chat_model

try:
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:  # pragma: no cover - handled at runtime when deps are absent
    ChatPromptTemplate = None


class OutreachEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(
        ...,
        description="A professional subject line between 4 and 8 words that is specific, credible, and never clickbait.",
    )
    body: str = Field(
        ...,
        description=(
            "A plain-text outreach email between 90 and 150 words with a greeting, tailored opener, concise value "
            "proposition, one low-friction CTA, and a professional sign-off from Bizard Leads."
        ),
    )
    personalization_summary: str = Field(
        ...,
        description=(
            "One sentence explaining how the email was personalized using the supplied lead context. If the context is "
            "thin, say that the message used light personalization."
        ),
    )
    call_to_action: str = Field(
        ...,
        description="The exact single CTA used in the email body, phrased as a short and easy next step.",
    )


def _prompt_value(value: Any) -> str:
    if value is None:
        return "Not provided"
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or "Not provided"
    return str(value)


@lru_cache(maxsize=1)
def build_outreach_email_prompt():
    if ChatPromptTemplate is None:
        raise LangChainDependencyError("langchain-core is not installed")

    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a senior outbound sales writer for Bizard Leads. "
                    "Write first-touch B2B outreach emails that sound human, commercially sharp, and respectful.\n"
                    "Rules:\n"
                    "- Use only the facts provided in the lead context.\n"
                    "- Never invent metrics, achievements, tools, pain points, or recent company news.\n"
                    "- If context is limited, stay tasteful and slightly more general instead of making things up.\n"
                    "- Optimize for credibility and reply rate, not hype.\n"
                    "- Avoid spam language, exclamation marks, emojis, markdown, bullet lists, and placeholder text.\n"
                    "- Keep the email plain text and ready to send."
                ),
            ),
            (
                "human",
                (
                    "Create a personalized outreach email for this lead.\n\n"
                    "Lead context:\n"
                    "- First name: {first_name}\n"
                    "- Last name: {last_name}\n"
                    "- Full name: {full_name}\n"
                    "- Job title: {title}\n"
                    "- Company: {company}\n"
                    "- Company domain: {company_domain}\n"
                    "- Industry: {industry}\n"
                    "- LinkedIn URL: {linkedin_url}\n"
                    "- Lead source: {source}\n"
                    "- Contact email: {email}\n\n"
                    "Business context:\n"
                    "- Sender: Bizard Leads\n"
                    "- Offer: AI-assisted lead sourcing, enrichment, and outreach automation for growth and sales teams\n"
                    "- Goal: start a conversation or secure a short intro call\n"
                    "- CTA style: low-friction, one question only\n\n"
                    "Writing requirements:\n"
                    "- Subject line should be 4 to 8 words.\n"
                    "- Body should be 90 to 150 words.\n"
                    "- Start with a natural greeting using the first name when available.\n"
                    "- Open with a relevant observation tied to the lead's role, company, industry, or likely priorities.\n"
                    "- Explain how Bizard Leads can help in concrete but non-fabricated terms.\n"
                    "- Include one clear value angle without overclaiming outcomes.\n"
                    "- End with one polite CTA and a simple sign-off.\n"
                    "- Do not mention AI, prompt instructions, missing data, or internal reasoning.\n\n"
                    "Return a response that matches the OutreachEmail schema exactly."
                ),
            ),
        ]
    )


def build_outreach_email_chain(*, model: str | None = None, api_key: str | None = None):
    prompt = build_outreach_email_prompt()
    llm = build_chat_model(model=model, api_key=api_key, temperature=0.4)
    return prompt | llm.with_structured_output(OutreachEmail)


def generate_outreach_email(
    contact: dict[str, Any],
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> OutreachEmail:
    chain = build_outreach_email_chain(model=model, api_key=api_key)
    return chain.invoke(
        {
            "first_name": _prompt_value(contact.get("first_name") or contact.get("firstName")),
            "last_name": _prompt_value(contact.get("last_name") or contact.get("lastName")),
            "full_name": _prompt_value(contact.get("full_name") or contact.get("fullName") or contact.get("name")),
            "title": _prompt_value(contact.get("title") or contact.get("jobtitle")),
            "company": _prompt_value(contact.get("company")),
            "company_domain": _prompt_value(contact.get("company_domain") or contact.get("domain")),
            "industry": _prompt_value(contact.get("industry")),
            "linkedin_url": _prompt_value(contact.get("linkedin_url") or contact.get("linkedin")),
            "source": _prompt_value(contact.get("source")),
            "email": _prompt_value(contact.get("email")),
        }
    )


__all__ = [
    "OutreachEmail",
    "build_outreach_email_chain",
    "build_outreach_email_prompt",
    "generate_outreach_email",
]
