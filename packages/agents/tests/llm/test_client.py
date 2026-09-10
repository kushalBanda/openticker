from dataclasses import dataclass
from typing import Any

import pytest
from agents.llm.client import LLMClient
from agents.llm.core.exceptions import LLMCallFailedError


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]


def _fake_response(content: str) -> _FakeResponse:
    return _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content=content))])


def test_complete_maps_content_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _fake_response("hello")

    monkeypatch.setattr("agents.llm.client.litellm.completion", fake_completion)

    client = LLMClient(model="anthropic/claude-sonnet-5", temperature=0.0)
    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "hello"
    assert result.model == "anthropic/claude-sonnet-5"
    assert captured["model"] == "anthropic/claude-sonnet-5"
    assert captured["temperature"] == 0.0
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert "api_key" not in captured
    assert "base_url" not in captured


def test_complete_passes_through_optional_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _fake_response("ok")

    monkeypatch.setattr("agents.llm.client.litellm.completion", fake_completion)

    client = LLMClient(
        model="ollama/qwen3:latest",
        api_key="unused",
        base_url="http://localhost:11434",
        timeout=5.0,
        max_retries=2,
    )
    client.complete([{"role": "user", "content": "hi"}])

    assert captured["api_key"] == "unused"
    assert captured["base_url"] == "http://localhost:11434"
    assert captured["timeout"] == 5.0
    assert captured["num_retries"] == 2


def test_complete_wraps_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_completion(**kwargs: Any) -> _FakeResponse:
        raise RuntimeError("rate limited")

    monkeypatch.setattr("agents.llm.client.litellm.completion", fake_completion)

    client = LLMClient(model="anthropic/claude-sonnet-5")
    with pytest.raises(LLMCallFailedError, match="rate limited"):
        client.complete([{"role": "user", "content": "hi"}])


async def test_acomplete_maps_content(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> _FakeResponse:
        return _fake_response("async hello")

    monkeypatch.setattr("agents.llm.client.litellm.acompletion", fake_acompletion)

    client = LLMClient(model="gemini/gemini-3.5-flash")
    result = await client.acomplete([{"role": "user", "content": "hi"}])

    assert result.content == "async hello"
    assert result.model == "gemini/gemini-3.5-flash"


async def test_acomplete_wraps_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: Any) -> _FakeResponse:
        raise RuntimeError("timeout")

    monkeypatch.setattr("agents.llm.client.litellm.acompletion", fake_acompletion)

    client = LLMClient(model="anthropic/claude-sonnet-5")
    with pytest.raises(LLMCallFailedError, match="timeout"):
        await client.acomplete([{"role": "user", "content": "hi"}])
