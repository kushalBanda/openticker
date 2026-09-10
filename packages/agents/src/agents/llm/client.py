from typing import Any

import litellm

from agents.llm.core.exceptions import LLMCallFailedError
from agents.llm.core.interfaces import LLMResponse, Message


def _to_llm_response(response: Any, model: str) -> LLMResponse:
    content = response.choices[0].message.content
    return LLMResponse(content=content, model=model, raw=response)


class LLMClient:
    """Thin wrapper over `litellm.completion`/`litellm.acompletion`.

    `model` follows litellm's `<provider>/<model-id>` convention, e.g.
    `"anthropic/claude-sonnet-5"`, `"gemini/gemini-3.5-flash"`,
    `"bedrock/us.anthropic.claude-opus-5-v1:0"`, `"ollama/qwen3:latest"`.
    litellm resolves the provider, base URL, and API-key env var from that
    prefix, so no per-provider client class is needed here — swapping
    providers is a config string change, not a code change.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 0,
        temperature: float | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature

    def _call_kwargs(
        self, messages: list[Message], response_format: Any | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "num_retries": self.max_retries,
        }
        if self.api_key is not None:
            kwargs["api_key"] = self.api_key
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        return kwargs

    def complete(
        self, messages: list[Message], response_format: Any | None = None
    ) -> LLMResponse:
        """Synchronous chat completion.

        `response_format` accepts litellm's structured-output shapes: a
        Pydantic model class, or `{"type": "json_schema", "json_schema": {...}}`.
        """
        try:
            response = litellm.completion(**self._call_kwargs(messages, response_format))
        except Exception as exc:
            raise LLMCallFailedError(
                f"litellm call failed for model {self.model!r}: {exc}"
            ) from exc
        return _to_llm_response(response, self.model)

    async def acomplete(
        self, messages: list[Message], response_format: Any | None = None
    ) -> LLMResponse:
        """Async chat completion. Same contract as `complete`."""
        try:
            response = await litellm.acompletion(**self._call_kwargs(messages, response_format))
        except Exception as exc:
            raise LLMCallFailedError(
                f"litellm call failed for model {self.model!r}: {exc}"
            ) from exc
        return _to_llm_response(response, self.model)
