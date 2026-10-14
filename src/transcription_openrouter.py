"""First-class OpenRouter speech-to-text provider."""

from typing import Optional

from src.config.constants import OPENROUTER_BASE_URL
from src.transcription_openai import OpenAITranscriber


class OpenRouterTranscriber(OpenAITranscriber):
    """Use multipart audio uploads and JSON responses with isolated credentials."""

    def __init__(
        self, api_key: Optional[str] = None, model: str = "openai/gpt-transcribe"
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=OPENROUTER_BASE_URL,
            provider_name="OpenRouter",
            response_format="json",
            key_environment="OPENROUTER_API_KEY",
        )
