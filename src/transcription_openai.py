import os
from loguru import logger
import time
from typing import Optional
from openai import OpenAI, APIError as OpenAIAPIError

from src.transcription_base import TranscriberBase
from src.utils import validate_audio_file_exists, validate_audio_duration
from src.exceptions import TranscriptionError, APIError


class OpenAITranscriber(TranscriberBase):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        *,
        base_url: Optional[str] = None,
        provider_name: str = "OpenAI",
        response_format: str = "text",
        key_environment: str = "OPENAI_API_KEY",
    ):
        """
        Initialize the transcriber with OpenAI API.

        Args:
            api_key: OpenAI API key. If None, will use OPENAI_API_KEY environment variable
            model: STT Model to use (default: whisper-1)
            base_url: Optional OpenAI-compatible endpoint; fixed for the OpenRouter provider
            provider_name: Provider label for credential validation and errors
            response_format: OpenAI text or OpenRouter JSON transcription response
            key_environment: Provider-specific environment variable for a missing key
        """
        api_key = api_key or os.getenv(key_environment)
        super().__init__(api_key, provider_name)

        self.model = model
        self.provider_name = provider_name
        self.response_format = response_format
        if base_url:
            self.client = OpenAI(api_key=self.api_key, base_url=base_url, timeout=30.0)
        else:
            self.client = OpenAI(api_key=self.api_key)

    def transcribe_audio(
        self, audio_file_path: str, language: Optional[str] = None
    ) -> Optional[str]:
        """
        Transcribe audio file to text using OpenAI API.

        Args:
            audio_file_path: Path to the audio file
            language: Language code (optional, auto-detect if None)

        Returns:
            Transcribed text or None if transcription failed
        """
        # Validate file exists
        if not validate_audio_file_exists(audio_file_path):
            return None

        # Validate audio duration
        if not validate_audio_duration(audio_file_path):
            return None

        try:
            start_time = time.time()
            logger.debug(f"Starting transcription for: {audio_file_path}")

            # Build optional prompt from glossary terms
            prompt = ", ".join(self.glossary) if self.glossary else None

            with open(audio_file_path, "rb") as audio_file:
                request = {
                    "model": self.model,
                    "file": audio_file,
                    "language": language,
                    "response_format": self.response_format,
                }
                # OpenRouter accepts multipart uploads, but rejects the legacy
                # 'text' format and ignores the OpenAI glossary prompt field.
                if self.provider_name != "OpenRouter":
                    request["prompt"] = prompt
                response = self.client.audio.transcriptions.create(**request)

            # Handle both string and object responses
            if hasattr(response, "text"):
                transcribed_text = response.text
            elif isinstance(response, str):
                transcribed_text = response
            else:
                # Fallback to string representation
                logger.warning(
                    "Unknown transcription response format, using string representation"
                )
                transcribed_text = str(response)

            transcribed_text = transcribed_text.strip()
            transcription_time = time.time() - start_time

            logger.info(
                f"Transcription successful: {len(transcribed_text)} characters in {transcription_time:.2f}s"
            )
            return transcribed_text if transcribed_text else None

        except OpenAIAPIError as e:
            logger.error(f"{self.provider_name} API error during transcription: {e}")
            raise APIError(
                f"{self.provider_name} transcription API failed: {e}",
                provider=self.provider_name,
                status_code=getattr(e, "status_code", None),
            ) from e
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Failed to transcribe audio: {e}") from e
