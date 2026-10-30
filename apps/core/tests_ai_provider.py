import json
from http.client import BadStatusLine, IncompleteRead
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase, override_settings
from openai import APIConnectionError, APITimeoutError, RateLimitError

from .services import ai_provider


class AIProviderTests(SimpleTestCase):
    def setUp(self):
        self.settings = override_settings(
            AI_PROVIDER="openai",
            OPENAI_API_KEY="test-key",
            OPENAI_MODEL="gpt-4.1-mini",
            OPENAI_TIMEOUT_SECONDS="9",
            OLLAMA_BASE_URL="http://127.0.0.1:11434",
            OLLAMA_MODEL="llama3.2:latest",
            OLLAMA_TIMEOUT_SECONDS="60",
        )
        self.settings.enable()
        self.addCleanup(self.settings.disable)

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_generates_response_using_environment_configuration(self, openai_client):
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="  Hello!  "))]
        openai_client.return_value.chat.completions.create.return_value = completion

        response = ai_provider.generate_response(
            [{"role": "user", "content": "Hello"}],
        )

        self.assertEqual(response, "Hello!")
        openai_client.assert_called_once_with(api_key="test-key", timeout=9.0)
        openai_client.return_value.chat.completions.create.assert_called_once_with(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": "Hello"}],
            max_completion_tokens=500,
        )

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_missing_api_key_fails_without_calling_provider(self, openai_client):
        with (
            override_settings(OPENAI_API_KEY=""),
            self.assertRaises(ai_provider.ProviderNotConfigured),
        ):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

        openai_client.assert_not_called()

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_timeout_is_reported_without_exposing_provider_details(self, openai_client):
        openai_client.return_value.chat.completions.create.side_effect = (
            APITimeoutError(request=MagicMock())
        )

        with self.assertRaisesRegex(ai_provider.ProviderTimeout, "timed out"):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_rate_limit_is_reported_as_a_safe_provider_error(self, openai_client):
        openai_client.return_value.chat.completions.create.side_effect = RateLimitError(
            "rate limited",
            response=MagicMock(),
            body=None,
        )

        with self.assertRaises(ai_provider.ProviderRateLimited):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_connection_failure_is_reported_without_raw_exception(self, openai_client):
        openai_client.return_value.chat.completions.create.side_effect = (
            APIConnectionError(request=MagicMock())
        )

        with self.assertRaisesRegex(ai_provider.ProviderError, "request failed"):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_empty_provider_response_is_rejected(self, openai_client):
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content=None))]
        openai_client.return_value.chat.completions.create.return_value = completion

        with self.assertRaisesRegex(ai_provider.ProviderError, "empty response"):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

    @patch("apps.core.services.ai_provider.OpenAI")
    def test_invalid_timeout_is_rejected_before_provider_call(self, openai_client):
        with (
            override_settings(OPENAI_TIMEOUT_SECONDS="not-a-number"),
            self.assertRaisesRegex(
                ai_provider.ProviderError,
                "timeout configuration is invalid",
            ),
        ):
            ai_provider.generate_response([{"role": "user", "content": "Hi"}])

        openai_client.assert_not_called()


class OllamaProviderTests(SimpleTestCase):
    def setUp(self):
        self.settings = override_settings(
            AI_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://127.0.0.1:11434/",
            OLLAMA_MODEL="llama3.2:latest",
            OLLAMA_TIMEOUT_SECONDS="60",
            OPENAI_API_KEY="",
        )
        self.settings.enable()
        self.addCleanup(self.settings.disable)

    def _response(self, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode("utf-8")
        return response

    @patch("apps.core.services.ai_provider.OpenAI")
    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_sends_chat_payload_and_returns_content(
        self,
        urlopen,
        openai_client,
    ):
        urlopen.return_value = self._response(
            {"message": {"role": "assistant", "content": "  Local answer  "}}
        )
        messages = [{"role": "user", "content": "Hello"}]

        answer = ai_provider.generate_response(messages)

        self.assertEqual(answer, "Local answer")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            json.loads(request.data),
            {
                "model": "llama3.2:latest",
                "messages": messages,
                "stream": False,
            },
        )
        urlopen.assert_called_once_with(request, timeout=60.0)
        openai_client.assert_not_called()

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_timeout_raises_safe_provider_timeout(self, urlopen):
        urlopen.side_effect = TimeoutError("internal timeout detail")

        with self.assertRaisesRegex(ai_provider.ProviderTimeout, "timed out"):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_connection_failure_raises_safe_provider_error(self, urlopen):
        urlopen.side_effect = URLError("internal connection detail")

        with self.assertRaisesRegex(
            ai_provider.ProviderError,
            "Could not connect",
        ) as error:
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

        self.assertNotIn("internal connection detail", str(error.exception))

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_http_error_raises_safe_provider_error(self, urlopen):
        urlopen.side_effect = HTTPError(
            "http://127.0.0.1:11434/api/chat",
            503,
            "service unavailable",
            hdrs=None,
            fp=None,
        )

        with self.assertRaisesRegex(ai_provider.ProviderError, "HTTP 503"):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_malformed_url_raises_safe_provider_error(self, urlopen):
        with (
            override_settings(OLLAMA_BASE_URL="http://[malformed"),
            self.assertRaisesRegex(
                ai_provider.ProviderError,
                "service URL configuration is invalid",
            ),
        ):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

        urlopen.assert_not_called()

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_bad_http_status_line_raises_safe_provider_error(self, urlopen):
        urlopen.side_effect = BadStatusLine("sensitive response detail")

        with self.assertRaisesRegex(
            ai_provider.ProviderError,
            "invalid HTTP response",
        ) as error:
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

        self.assertNotIn("sensitive response detail", str(error.exception))

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_incomplete_http_response_raises_safe_provider_error(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = IncompleteRead(
            b'{"message":',
            100,
        )
        urlopen.return_value = response

        with self.assertRaisesRegex(
            ai_provider.ProviderError,
            "invalid HTTP response",
        ):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_invalid_json_response_raises_safe_provider_error(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{invalid json"
        urlopen.return_value = response

        with self.assertRaisesRegex(ai_provider.ProviderError, "invalid response"):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_empty_assistant_content_raises_safe_provider_error(self, urlopen):
        urlopen.return_value = self._response(
            {"message": {"role": "assistant", "content": "  "}}
        )

        with self.assertRaisesRegex(ai_provider.ProviderError, "empty response"):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

    @patch("apps.core.services.ai_provider.OpenAI")
    @patch("apps.core.services.ai_provider.urlopen")
    def test_openai_selection_never_contacts_ollama(
        self,
        urlopen,
        openai_client,
    ):
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="OpenAI answer"))]
        openai_client.return_value.chat.completions.create.return_value = completion
        with override_settings(
            AI_PROVIDER="openai",
            OPENAI_API_KEY="test-key",
        ):
            answer = ai_provider.generate_response(
                [{"role": "user", "content": "Hello"}],
            )

        self.assertEqual(answer, "OpenAI answer")
        openai_client.assert_called_once()
        urlopen.assert_not_called()

    @patch("apps.core.services.ai_provider.OpenAI")
    @patch("apps.core.services.ai_provider.urlopen")
    def test_ollama_selection_never_falls_back_to_openai(
        self,
        urlopen,
        openai_client,
    ):
        urlopen.side_effect = URLError("Ollama unavailable")

        with self.assertRaises(ai_provider.ProviderError):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

        openai_client.assert_not_called()
        urlopen.assert_called_once()

    def test_unknown_provider_fails_without_contacting_either_provider(self):
        with (
            override_settings(AI_PROVIDER="unknown"),
            patch("apps.core.services.ai_provider.OpenAI") as openai_client,
            patch("apps.core.services.ai_provider.urlopen") as urlopen,
            self.assertRaisesRegex(ai_provider.ProviderError, "not supported"),
        ):
            ai_provider.generate_response([{"role": "user", "content": "Hello"}])

        openai_client.assert_not_called()
        urlopen.assert_not_called()
