"""Server-side AI provider clients for PregnaBot response generation."""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from openai import APIError, APITimeoutError, OpenAI, RateLimitError


class ProviderError(Exception):
    """Base class for safe-to-handle AI provider errors."""


class ProviderNotConfigured(ProviderError):
    """Raised when the provider API key is not configured."""


class ProviderTimeout(ProviderError):
    """Raised when the provider request times out."""


class ProviderRateLimited(ProviderError):
    """Raised when the provider rejects a request due to rate limits."""


def _openai_settings(api_key, model, timeout):
    api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
    model = model if model is not None else settings.OPENAI_MODEL
    timeout_value = timeout if timeout is not None else settings.OPENAI_TIMEOUT_SECONDS

    if not api_key.strip():
        raise ProviderNotConfigured("The AI provider is not configured.")
    if not model.strip():
        raise ProviderError("The AI provider model is not configured.")

    try:
        timeout_value = float(timeout_value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            "The AI provider timeout configuration is invalid."
        ) from exc
    if timeout_value <= 0:
        raise ProviderError("The AI provider timeout must be greater than zero.")

    return api_key, model, timeout_value


def _generate_openai_response(messages, *, api_key=None, model=None, timeout=None):
    api_key, model, timeout = _openai_settings(api_key, model, timeout)
    client = OpenAI(api_key=api_key, timeout=timeout)

    try:
        result = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=500,
        )
    except APITimeoutError as exc:
        raise ProviderTimeout("The AI provider request timed out.") from exc
    except RateLimitError as exc:
        raise ProviderRateLimited(
            "The AI provider is temporarily rate limited."
        ) from exc
    except APIError as exc:
        raise ProviderError("The AI provider request failed.") from exc

    if not result.choices or not result.choices[0].message.content:
        raise ProviderError("The AI provider returned an empty response.")
    return result.choices[0].message.content.strip()


def _generate_ollama_response(messages, *, model=None, timeout=None):
    model = model if model is not None else settings.OLLAMA_MODEL
    if not model.strip():
        raise ProviderError("The Ollama model is not configured.")

    timeout_value = timeout if timeout is not None else settings.OLLAMA_TIMEOUT_SECONDS
    try:
        timeout_value = float(timeout_value)
    except (TypeError, ValueError) as exc:
        raise ProviderError("The Ollama timeout configuration is invalid.") from exc
    if timeout_value <= 0:
        raise ProviderError("The Ollama timeout must be greater than zero.")

    base_url = settings.OLLAMA_BASE_URL.rstrip("/")
    try:
        parsed_url = urlsplit(base_url)
    except ValueError as exc:
        raise ProviderError("The Ollama service URL configuration is invalid.") from exc
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
    ):
        raise ProviderError("The Ollama service URL configuration is invalid.")

    try:
        request = Request(
            f"{base_url}/api/chat",
            data=json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    except ValueError as exc:
        raise ProviderError("The Ollama service URL configuration is invalid.") from exc

    try:
        with urlopen(request, timeout=timeout_value) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProviderError(f"Ollama returned HTTP {exc.code}.") from exc
    except HTTPException as exc:
        raise ProviderError("Ollama returned an invalid HTTP response.") from exc
    except TimeoutError as exc:
        raise ProviderTimeout("The Ollama request timed out.") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ProviderTimeout("The Ollama request timed out.") from exc
        raise ProviderError("Could not connect to the Ollama service.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Ollama returned an invalid response.") from exc
    except OSError as exc:
        raise ProviderError("The Ollama request failed.") from exc

    if not isinstance(payload, dict):
        raise ProviderError("Ollama returned an invalid response.")
    message = payload.get("message")
    if not isinstance(message, dict):
        raise ProviderError("Ollama returned an invalid response.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("Ollama returned an empty response.")
    return content.strip()


def generate_response(messages, *, api_key=None, model=None, timeout=None):
    """Generate one response using the explicitly configured AI provider."""
    provider = settings.AI_PROVIDER.strip().lower()
    if provider == "openai":
        return _generate_openai_response(
            messages,
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
    if provider == "ollama":
        return _generate_ollama_response(
            messages,
            model=model,
            timeout=timeout,
        )
    raise ProviderError("The configured AI provider is not supported.")
