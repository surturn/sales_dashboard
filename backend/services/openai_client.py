from typing import Any

from openai import OpenAI

from backend.app.config import get_settings
from backend.services import ServiceConfigurationError


class OpenAIClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if not self.api_key:
            raise ServiceConfigurationError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _complete(self, prompt: str, max_tokens: int = 400, system_message: str | None = None) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_message or "You help Bizard Leads automate outreach, support, and reporting."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        return (response.choices[0].message.content or "").strip()

    @staticmethod
    def _parse_labeled_sections(content: str, labels: list[str]) -> dict[str, str]:
        sections = {label: "" for label in labels}
        current_label: str | None = None

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                if current_label and sections[current_label]:
                    sections[current_label] += "\n"
                continue

            matched_label = next((label for label in labels if line.upper().startswith(f"{label}:")), None)
            if matched_label:
                current_label = matched_label
                sections[current_label] = line.split(":", 1)[1].strip()
                continue

            if current_label:
                sections[current_label] = f"{sections[current_label]}\n{line}".strip()

        return {label: value.strip() for label, value in sections.items()}

    def _legacy_generate_outreach_email(self, contact: dict[str, Any]) -> tuple[str, str]:
        prompt = (
            "Write a concise B2B outreach email.\n"
            f"Name: {contact.get('first_name') or contact.get('firstName') or ''}\n"
            f"Company: {contact.get('company') or ''}\n"
            f"Title: {contact.get('title') or contact.get('jobtitle') or ''}\n"
            "Return the first line as 'SUBJECT: ...' and the rest as the email body."
        )
        content = self._complete(prompt, max_tokens=300)
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        subject = "Bizard Leads outreach"
        body_lines: list[str] = []
        for line in lines:
            if line.upper().startswith("SUBJECT:"):
                subject = line.split(":", 1)[1].strip() or subject
            else:
                body_lines.append(line)
        return subject, "\n".join(body_lines).strip()

    def generate_outreach_email(self, contact: dict[str, Any]) -> tuple[str, str]:
        if type(self)._complete is not OpenAIClient._complete:
            return self._legacy_generate_outreach_email(contact)

        try:
            from chains.base import LangChainDependencyError
            from chains.outreach import generate_outreach_email as generate_langchain_outreach_email

            email = generate_langchain_outreach_email(contact, model=self.model, api_key=self.api_key)
            return email.subject, email.body
        except (ImportError, LangChainDependencyError):
            return self._legacy_generate_outreach_email(contact)

    def generate_support_response(self, conversation: str, user_message: str) -> str:
        prompt = (
            "Respond as Bizard Leads support.\n"
            f"Conversation history: {conversation}\n"
            f"Latest user message: {user_message}\n"
            "Keep it helpful, short, and action-oriented."
        )
        return self._complete(prompt, max_tokens=220)

    def generate_weekly_report(self, metrics: dict[str, Any]) -> str:
        prompt = (
            "Create a weekly business summary for Bizard Leads.\n"
            f"Metrics: {metrics}\n"
            "Highlight wins, risks, and one recommendation."
        )
        return self._complete(prompt, max_tokens=500)

    def generate_social_post(self, topic: str, platform: str, context: str = "") -> tuple[str, str, str]:
        system_message = (
            "You are Bizard Leads' social strategy advisor. Be truthful, critical, and useful. "
            "Do not invent numbers, outcomes, or certainty. If the signal is weak, say so clearly. "
            "Prefer grounded strategic advice over hype, and make the post feel like it was written by a sharp operator."
        )
        prompt = (
            "Create a high-quality social media draft for Bizard Leads based on a discovered trend.\n"
            f"Topic: {topic}\n"
            f"Platform: {platform}\n"
            f"Trend context: {context}\n"
            "Requirements:\n"
            "- Make the insight practical, specific, and trustworthy.\n"
            "- Include one critical or contrarian observation where appropriate.\n"
            "- Do not overclaim or pretend weak context is strong evidence.\n"
            "- Keep the caption concise and useful.\n"
            "- In the content, include a hook, a grounded insight, a critical take, and a practical recommendation.\n"
            "Return exactly three sections labeled TITLE:, CAPTION:, and CONTENT:.\n"
            "Inside CONTENT, write multiple short paragraphs or bullets suitable for posting or editing."
        )
        content = self._complete(prompt, max_tokens=500, system_message=system_message)
        parsed = self._parse_labeled_sections(content, ["TITLE", "CAPTION", "CONTENT"])
        title = parsed["TITLE"] or f"{platform.title()} post"
        caption = parsed["CAPTION"] or topic
        body = parsed["CONTENT"] or content
        return title, caption, body
