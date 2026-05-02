"""Pluggable LLM provider factory.

Default is Anthropic (project owner has Anthropic credits, not OpenAI).
Swap providers by changing LLM_PROVIDER in .env — call sites stay untouched.
"""

from langchain_core.language_models.chat_models import BaseChatModel

from .config import settings


def get_chat_model(temperature: float = 0.0, **kwargs) -> BaseChatModel:
    provider = settings.llm_provider.lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key or None,
            temperature=temperature,
            **kwargs,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key or None,
            temperature=temperature,
            **kwargs,
        )

    if provider == "ollama":
        from langchain_community.chat_models import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            **kwargs,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
