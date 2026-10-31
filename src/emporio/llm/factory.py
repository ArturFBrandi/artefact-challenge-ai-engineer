"""Build the configured provider."""

from emporio.config import Settings
from emporio.llm.base import LLMProvider
from emporio.llm.fake import FakeLLMProvider
from emporio.llm.minimax import MiniMaxProvider


class ConfigurationError(Exception):
    pass


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        if settings.app_env != "test":
            raise ConfigurationError("LLM_PROVIDER=fake is only allowed with APP_ENV=test.")
        return FakeLLMProvider()
    if not settings.llm_api_key.get_secret_value():
        raise ConfigurationError(
            "LLM_API_KEY is not set. Create a key at https://platform.minimax.io and add it to .env"
        )
    return MiniMaxProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_completion_tokens=settings.llm_max_completion_tokens,
        thinking=settings.llm_thinking,
    )
