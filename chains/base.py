from __future__ import annotations

from backend.app.config import get_settings
from backend.services import ServiceConfigurationError

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - handled at runtime when deps are absent
    ChatOpenAI = None


class LangChainDependencyError(RuntimeError):
    pass


def resolve_openai_config(model: str | None = None, api_key: str | None = None) -> tuple[str, str]:
    settings = get_settings()
    resolved_model = model or settings.OPENAI_MODEL
    resolved_api_key = api_key or settings.OPENAI_API_KEY

    if not resolved_api_key:
        raise ServiceConfigurationError("OPENAI_API_KEY is not configured")

    return resolved_model, resolved_api_key


def build_chat_model(
    *,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.4,
):
    if ChatOpenAI is None:
        raise LangChainDependencyError("langchain-openai is not installed")

    resolved_model, resolved_api_key = resolve_openai_config(model=model, api_key=api_key)
    return ChatOpenAI(
        model=resolved_model,
        api_key=resolved_api_key,
        temperature=temperature,
    )
