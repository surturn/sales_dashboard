from backend.services.openai_client import OpenAIClient


class FakeOpenAIClient(OpenAIClient):
    def _complete(self, prompt: str, max_tokens: int = 400, system_message: str | None = None) -> str:
        return "SUBJECT: Hello there\nThis is the email body."


def test_generate_outreach_email_parses_subject_and_body() -> None:
    client = FakeOpenAIClient(api_key="test-key")

    subject, body = client.generate_outreach_email({"first_name": "Ada"})

    assert subject == "Hello there"
    assert body == "This is the email body."


class FakeSocialOpenAIClient(OpenAIClient):
    def _complete(self, prompt: str, max_tokens: int = 400, system_message: str | None = None) -> str:
        return (
            "TITLE: Sharper Founder Positioning\n"
            "CAPTION: This trend is useful, but only if the signal is real for your market.\n"
            "CONTENT: Hook:\n"
            "Most trends are overvalued because teams copy attention instead of intent.\n"
            "Grounded insight:\n"
            "Operators are responding to practical examples more than generic inspiration.\n"
            "Critical take:\n"
            "If you cannot tie the trend back to a clear buyer pain point, skip it.\n"
            "Trustworthy advice:\n"
            "Test one specific angle, measure saves and replies, then double down only if quality engagement improves."
        )


def test_generate_social_post_parses_multiline_strategy_sections() -> None:
    client = FakeSocialOpenAIClient(api_key="test-key")

    title, caption, content = client.generate_social_post(
        topic="founder positioning",
        platform="linkedin",
        context="Platform signal: linkedin | Trend score: 8.7 | Trend summary: Audiences prefer operator-led examples.",
    )

    assert title == "Sharper Founder Positioning"
    assert "signal is real for your market" in caption
    assert "Grounded insight:" in content
    assert "Critical take:" in content
    assert "Trustworthy advice:" in content
