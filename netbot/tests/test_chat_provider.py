import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.chat.provider import ChatProviderError, OpenRouterProvider


def make_settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_openrouter_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")

    settings = make_settings()

    assert settings.openrouter_api_key == SecretStr("test-key")
    assert settings.openrouter_model == "test/model"


def test_blank_openrouter_credentials_are_unconfigured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  ")
    monkeypatch.setenv("OPENROUTER_MODEL", "")

    settings = make_settings()

    assert settings.openrouter_api_key is None
    assert settings.openrouter_model is None


def test_chat_limits_have_bounded_defaults():
    settings = make_settings()

    assert settings.chat_max_message_chars == 2000
    assert settings.chat_max_history_chars == 8000
    assert settings.chat_max_history_turns == 8
    assert settings.chat_max_tool_rounds == 3
    assert settings.chat_max_output_tokens == 600


def provider_settings():
    return make_settings(openrouter_api_key="test-key", openrouter_model="test/model")


@pytest.mark.asyncio
async def test_provider_sends_chat_completion_request():
    seen = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "estado normal", "role": "assistant"}}]},
        )

    provider = OpenRouterProvider(
        provider_settings(), transport=httpx.MockTransport(respond)
    )
    result = await provider.complete(
        messages=[{"role": "user", "content": "¿Cómo está la red?"}],
        tools=[{"type": "function", "function": {"name": "get_system"}}],
    )

    import json

    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer test-key"
    assert seen["headers"]["content-type"].startswith("application/json")
    assert json.loads(seen["body"]) == {
        "model": "test/model",
        "messages": [{"role": "user", "content": "¿Cómo está la red?"}],
        "tools": [{"type": "function", "function": {"name": "get_system"}}],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_tokens": 600,
    }
    assert result.content == "estado normal"
    assert result.tool_calls == ()


@pytest.mark.asyncio
async def test_provider_parses_function_tool_calls():
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_firewall_events",
                                        "arguments": '{"limit": 5, "action": "block"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    provider = OpenRouterProvider(
        provider_settings(), transport=httpx.MockTransport(respond)
    )
    result = await provider.complete(messages=[], tools=[])

    assert result.content is None
    assert result.tool_calls[0].id == "call-1"
    assert result.tool_calls[0].name == "get_firewall_events"
    assert result.tool_calls[0].arguments == {"limit": 5, "action": "block"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "respond",
    [
        lambda _: httpx.Response(502, text="private upstream response"),
        lambda _: httpx.Response(200, json={"choices": []}),
        lambda _: (_ for _ in ()).throw(httpx.TimeoutException("secret timeout")),
    ],
)
async def test_provider_hides_upstream_errors(respond):
    provider = OpenRouterProvider(
        provider_settings(), transport=httpx.MockTransport(respond)
    )

    with pytest.raises(ChatProviderError) as error:
        await provider.complete(messages=[], tools=[])

    assert "test-key" not in str(error.value)
    assert "private upstream response" not in str(error.value)
    assert "secret timeout" not in str(error.value)

