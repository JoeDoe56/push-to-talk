"""OpenRouter text refinement using the same key as speech-to-text."""

from typing import Optional

from src.config.constants import OPENROUTER_BASE_URL
from src.text_refiner_openai import TextRefinerOpenAI


class OpenRouterTextRefiner(TextRefinerOpenAI):
    def __init__(
        self, api_key: Optional[str] = None, model: str = "openai/gpt-4.1-mini"
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=OPENROUTER_BASE_URL,
            provider_name="OpenRouter",
            key_environment="OPENROUTER_API_KEY",
        )
