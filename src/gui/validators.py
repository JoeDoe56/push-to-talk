"""Validation logic for PushToTalk configuration."""

import urllib.request
import urllib.error
import os
from src.push_to_talk import PushToTalkConfig
from src.config.constants import OPENROUTER_BASE_URL


def validate_configuration(config: PushToTalkConfig) -> tuple[bool, str | None]:
    """
    Validate a configuration object.

    Args:
        config: Configuration object to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    # Check API key based on selected provider
    if config.stt_provider == "openai":
        if not config.openai_api_key.strip():
            return (
                False,
                "OpenAI API key is required when using OpenAI provider!\n\n"
                "Please enter your OpenAI API key or switch to Deepgram provider.",
            )
    elif config.stt_provider == "openrouter":
        if not (
            config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        ).strip():
            return (
                False,
                "Paste your OpenRouter API key into the OpenRouter API Key field.",
            )
    elif config.stt_provider == "deepgram":
        if not config.deepgram_api_key.strip():
            return (
                False,
                "Deepgram API key is required when using Deepgram provider!\n\n"
                "Please enter your Deepgram API key or switch to OpenAI provider.",
            )
    else:
        return False, f"Unknown provider: {config.stt_provider}"

    if config.enable_text_refinement and config.refinement_provider == "openrouter":
        if not (
            config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        ).strip():
            return (
                False,
                "OpenRouter text refinement needs the OpenRouter API Key field or OPENROUTER_API_KEY.",
            )

    # Check hotkeys are different
    if config.hotkey == config.toggle_hotkey:
        return False, "Push-to-talk and toggle hotkeys must be different!"

    return True, None


def validate_openrouter_api_key(api_key: str) -> bool:
    """Validate OpenRouter credentials without sending audio or creating a paid generation."""
    request = urllib.request.Request(
        f"{OPENROUTER_BASE_URL}/key",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError("INVALID - Incorrect OpenRouter API key") from exc
        raise ValueError(f"OpenRouter returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(
            "Could not reach OpenRouter; check the network connection."
        ) from exc


def validate_openai_api_key(api_key: str) -> bool:
    """
    Validate OpenAI API key by making a test request.

    Args:
        api_key: OpenAI API key to validate

    Returns:
        True if valid, False otherwise

    Raises:
        Exception: With descriptive error message
    """
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        # Test the API key by listing models (lightweight operation)
        _ = client.models.list()
        return True
    except Exception as e:
        error_msg = str(e)
        # Extract the most relevant error message
        if "401" in error_msg or "Incorrect API key" in error_msg:
            raise Exception("INVALID - Incorrect API key")
        elif "404" in error_msg:
            raise Exception("INVALID - API endpoint not found")
        elif "timeout" in error_msg.lower():
            raise Exception("TIMEOUT - Network issue")
        else:
            raise Exception(f"ERROR - {error_msg[:60]}...")


def validate_deepgram_api_key(api_key: str) -> bool:
    """
    Validate Deepgram API key by making a direct request to the auth endpoint.

    Args:
        api_key: Deepgram API key to validate

    Returns:
        True if valid, False otherwise

    Raises:
        Exception: With error message containing HTTP error codes (401, 404) or timeout
    """
    url = "https://api.deepgram.com/v1/auth/token"
    headers = {"Authorization": f"Token {api_key}"}

    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10):
            # If we get here, the API key is valid
            return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Exception("401 - Incorrect API key")
        elif e.code == 404:
            raise Exception("404 - API endpoint not found")
        else:
            raise Exception(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise Exception(f"timeout - Network error: {e.reason}")


def validate_cerebras_api_key(api_key: str) -> bool:
    """
    Validate Cerebras API key by making a test request.

    Args:
        api_key: Cerebras API key to validate

    Returns:
        True if valid, False otherwise

    Raises:
        Exception: With descriptive error message
    """
    try:
        from cerebras.cloud.sdk import Cerebras

        client = Cerebras(api_key=api_key)
        # Test the API key by making a simple models list request
        try:
            _ = client.models.list()
        except AttributeError:
            # If models.list() doesn't exist, try a minimal completion request
            _ = client.chat.completions.create(
                messages=[{"role": "user", "content": "test"}],
                model="llama3.1-8b",
                max_completion_tokens=1,
            )
        return True
    except Exception as e:
        error_msg = str(e)
        # Extract the most relevant error message
        if (
            "401" in error_msg
            or "Unauthorized" in error_msg
            or "Invalid API key" in error_msg
        ):
            raise Exception("INVALID - Incorrect API key")
        elif "403" in error_msg or "Forbidden" in error_msg:
            raise Exception("INVALID - Access forbidden")
        elif "404" in error_msg:
            raise Exception("INVALID - API endpoint not found")
        elif "timeout" in error_msg.lower():
            raise Exception("TIMEOUT - Network issue")
        else:
            raise Exception(f"ERROR - {error_msg[:60]}...")


def validate_gemini_api_key(api_key: str) -> bool:
    """
    Validate Google Gemini API key by making a test request.

    Args:
        api_key: Google Gemini API key to validate

    Returns:
        True if valid, False otherwise

    Raises:
        Exception: With descriptive error message
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        # Test the API key by listing models (lightweight operation)
        _ = list(client.models.list())
        return True
    except Exception as e:
        error_msg = str(e)
        # Extract the most relevant error message
        if (
            "401" in error_msg
            or "INVALID_ARGUMENT" in error_msg
            or "API key not valid" in error_msg
        ):
            raise Exception("INVALID - Incorrect API key")
        elif "403" in error_msg or "PERMISSION_DENIED" in error_msg:
            raise Exception("INVALID - Access forbidden")
        elif "404" in error_msg:
            raise Exception("INVALID - API endpoint not found")
        elif "timeout" in error_msg.lower():
            raise Exception("TIMEOUT - Network issue")
        else:
            raise Exception(f"ERROR - {error_msg[:60]}...")
