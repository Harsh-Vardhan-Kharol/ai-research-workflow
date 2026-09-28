"""Provider boundary and a configurable OpenAI-compatible hosted adapter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """A safe, provider-independent failure category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class ProviderAdapter(Protocol):
    def structured_complete(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]: ...


class HostedAPIAdapter:
    """Calls a configured chat-completions endpoint with JSON-schema mode."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def structured_complete(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        settings = self.settings
        if (
            not settings.ai_api_key
            or not settings.ai_model_name
            or not settings.ai_base_url
        ):
            raise ProviderError(
                "configuration_error",
                "Hosted AI requires AI_API_KEY, AI_MODEL_NAME, and AI_BASE_URL.",
            )

        repair_note = ""
        for attempt in range(settings.max_ai_retries + 1):
            body = {
                "model": settings.ai_model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt + repair_note,
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "paper_extraction",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            }
            request = Request(
                settings.ai_base_url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {settings.ai_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=settings.ai_timeout_seconds) as response:
                    response_data = json.loads(response.read().decode("utf-8"))
                content = response_data["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ProviderError(
                        "empty_response", "Provider returned no content."
                    )
                try:
                    result = json.loads(content)
                except json.JSONDecodeError as exc:
                    if attempt >= settings.max_ai_retries:
                        raise ProviderError(
                            "malformed_response", "Provider returned invalid JSON."
                        ) from exc
                    repair_note = (
                        "\nThe previous response was invalid JSON: "
                        f"{exc.msg} at line {exc.lineno}, column {exc.colno}. "
                        "Repair the response and return only one valid JSON "
                        "object matching the required schema."
                    )
                    logger.warning(
                        "AI_STRUCTURED_RESPONSE_REPAIR",
                        extra={"attempt": attempt + 1},
                    )
                    continue
                if not isinstance(result, dict):
                    raise ProviderError(
                        "unexpected_response",
                        "Provider returned a non-object JSON value.",
                    )
                return result
            except HTTPError as exc:
                if exc.code == 429:
                    category = "rate_limited"
                elif exc.code >= 500:
                    category = "provider_unavailable"
                else:
                    raise ProviderError(
                        "provider_error",
                        f"Provider rejected the request (HTTP {exc.code}).",
                    ) from exc
                if attempt >= settings.max_ai_retries:
                    raise ProviderError(
                        category, "Hosted provider request failed."
                    ) from exc
                time.sleep(min(2**attempt, 8))
            except TimeoutError as exc:
                if attempt >= settings.max_ai_retries:
                    raise ProviderError(
                        "timeout", "Hosted provider request timed out."
                    ) from exc
                time.sleep(min(2**attempt, 8))
            except URLError as exc:
                if attempt >= settings.max_ai_retries:
                    raise ProviderError(
                        "provider_unavailable", "Hosted provider is unavailable."
                    ) from exc
                time.sleep(min(2**attempt, 8))
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise ProviderError(
                    "unexpected_response",
                    "Provider returned an unexpected response shape.",
                ) from exc
        raise ProviderError("provider_error", "Provider request exhausted retries.")


class MockProvider:
    """Deterministic null-valued output for local processing without an API."""

    def structured_complete(
        self, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> dict[str, Any]:
        del system_prompt, user_prompt
        return _empty_for_schema(json_schema)


def _empty_for_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a schema-shaped all-unknown object for the explicit mock mode."""
    output: dict[str, Any] = {}
    properties = schema.get("properties", {})
    for name, definition in properties.items():
        if definition.get("type") == "array":
            output[name] = []
        else:
            output[name] = {
                "value": None,
                "source_text": None,
                "page": None,
                "section": None,
            }
    return output


def create_provider(settings: Settings) -> ProviderAdapter:
    if settings.ai_provider == "mock":
        return MockProvider()
    return HostedAPIAdapter(settings)
