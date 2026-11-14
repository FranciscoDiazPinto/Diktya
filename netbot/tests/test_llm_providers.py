"""HU019: proveedor seleccionable, adaptador Claude, health check y errores claros."""
import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import pytest

from app.chat.anthropic_provider import AnthropicProvider, to_anthropic_messages, to_anthropic_tool
from app.chat.provider import (ChatProviderError, ChatProviderNotConfigured, ChatProviderUnavailable,
                               OpenRouterProvider, ProviderToolCall, build_provider)
from app.chat.service import ChatService
from app.core.config import Settings

TOOL = {"type": "function", "function": {"name": "get_system", "description": "Métricas",
                                         "parameters": {"type": "object", "properties": {}}}}


def settings(**extra):
    return Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="test-only-key", **extra)


def block(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


class FakeMessages:
    def __init__(self, responses, calls):
        self.responses, self.calls = responses, calls

    async def create(self, **params):
        self.calls.append(params)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    """Sustituye al SDK: registra las solicitudes y nunca abre una conexión."""

    def __init__(self, responses=(), model_error=None):
        self.calls, self.beta_calls, self.model_error = [], [], model_error
        queue = list(responses)
        self.messages = FakeMessages(queue, self.calls)
        self.beta = SimpleNamespace(messages=FakeMessages(queue, self.beta_calls))
        self.models = SimpleNamespace(retrieve=self.retrieve)

    async def retrieve(self, model):
        if self.model_error:
            raise self.model_error
        return SimpleNamespace(id=model)


def api_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("cuerpo privado del proveedor", response=httpx2.Response(status, request=request), body=None)


def test_provider_is_selected_by_configuration_without_touching_consumers():
    assert isinstance(build_provider(Settings(_env_file=None)), OpenRouterProvider)
    provider = build_provider(settings())
    assert isinstance(provider, AnthropicProvider) and provider.name == "anthropic"
    assert Settings(_env_file=None).anthropic_model == "claude-opus-5-5"


def test_messages_and_tools_are_translated_to_the_messages_api():
    system, messages = to_anthropic_messages([
        {"role": "system", "content": "Política"},
        {"role": "user", "content": "¿Estado?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "get_system", "arguments": "{}"}},
            {"id": "t2", "type": "function", "function": {"name": "get_clients", "arguments": "{\"limit\":5}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "{\"status\":\"ok\"}"},
        {"role": "tool", "tool_call_id": "t2", "content": "{\"data\":[]}"},
    ])
    assert system == [{"type": "text", "text": "Política", "cache_control": {"type": "ephemeral"}}]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"][1] == {"type": "tool_use", "id": "t2", "name": "get_clients", "input": {"limit": 5}}
    # Todos los resultados de una ronda viajan en un único turno de usuario.
    assert [b["tool_use_id"] for b in messages[2]["content"]] == ["t1", "t2"]
    assert to_anthropic_tool(TOOL) == {"name": "get_system", "description": "Métricas",
                                       "input_schema": {"type": "object", "properties": {}}}


def test_tool_round_trip_returns_reasoning_blocks_unchanged():
    thinking = block("thinking", thinking="", signature="sig")
    call = block("tool_use", id="toolu_1", name="get_system", input={})
    first = SimpleNamespace(stop_reason="tool_use", content=[thinking, call])
    final = SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Todo operativo.")])
    client = FakeClient([first, final])
    provider = AnthropicProvider(settings(anthropic_refusal_fallback=False), client=client)

    completion = asyncio.run(provider.complete(messages=[{"role": "user", "content": "¿Estado?"}], tools=[TOOL]))
    assert completion.tool_calls == (ProviderToolCall("toolu_1", "get_system", {}),)
    follow_up = [{"role": "user", "content": "¿Estado?"}, ChatService._assistant_tool_message(completion),
                 {"role": "tool", "tool_call_id": "toolu_1", "content": "{}"}]
    answer = asyncio.run(provider.complete(messages=follow_up, tools=[TOOL]))
    assert answer.content == "Todo operativo." and answer.raw_content is None
    sent = client.calls[1]
    assert sent["messages"][1]["content"] == [thinking, call]
    assert sent["model"] == "claude-opus-5-5" and sent["output_config"] == {"effort": "medium"}
    assert "temperature" not in sent and "thinking" not in sent


def test_server_side_fallback_is_requested_by_default():
    client = FakeClient([SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Hola")])])
    asyncio.run(AnthropicProvider(settings(), client=client).complete(messages=[{"role": "user", "content": "x"}], tools=[]))
    assert client.calls == []
    assert client.beta_calls[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert client.beta_calls[0]["fallbacks"] == "default" and "tools" not in client.beta_calls[0]


@pytest.mark.parametrize("error,reason", [
    (api_error(anthropic.AuthenticationError, 401), "unauthorized"),
    (api_error(anthropic.RateLimitError, 429), "rate_limited"),
    (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com")), "timeout"),
    (api_error(anthropic.InternalServerError, 500), "unavailable"),
])
def test_provider_errors_are_classified_without_leaking_the_body(error, reason):
    provider = AnthropicProvider(settings(), client=FakeClient([error]))
    with pytest.raises(ChatProviderUnavailable) as caught:
        asyncio.run(provider.complete(messages=[{"role": "user", "content": "x"}], tools=[]))
    assert caught.value.reason == reason
    assert "privado" not in str(caught.value) and "privado" not in caught.value.public_message


def test_refusal_and_truncation_never_become_an_answer():
    refused = SimpleNamespace(stop_reason="refusal", content=[])
    truncated = SimpleNamespace(stop_reason="max_tokens", content=[block("thinking", thinking="", signature="s")])
    provider = AnthropicProvider(settings(), client=FakeClient([refused, truncated]))
    with pytest.raises(ChatProviderError) as caught:
        asyncio.run(provider.complete(messages=[{"role": "user", "content": "x"}], tools=[]))
    assert caught.value.reason == "refused"
    with pytest.raises(ChatProviderUnavailable):
        asyncio.run(provider.complete(messages=[{"role": "user", "content": "x"}], tools=[]))


def test_missing_key_is_reported_before_any_call():
    provider = AnthropicProvider(Settings(_env_file=None, llm_provider="anthropic"), client=FakeClient())
    with pytest.raises(ChatProviderNotConfigured):
        asyncio.run(provider.complete(messages=[{"role": "user", "content": "x"}], tools=[]))
    assert asyncio.run(provider.health()).status == "not_configured"


def test_anthropic_health_checks_credential_and_model_without_tokens():
    assert asyncio.run(AnthropicProvider(settings(), client=FakeClient()).health()).status == "ok"
    denied = FakeClient(model_error=api_error(anthropic.AuthenticationError, 401))
    assert asyncio.run(AnthropicProvider(settings(), client=denied).health()).status == "unauthorized"
    missing = FakeClient(model_error=api_error(anthropic.NotFoundError, 404))
    health = asyncio.run(AnthropicProvider(settings(), client=missing).health())
    assert health.status == "unavailable" and denied.calls == [] and denied.beta_calls == []


@pytest.mark.parametrize("status,expected", [(200, "ok"), (401, "unauthorized"), (429, "rate_limited"), (500, "unavailable")])
def test_openrouter_health_uses_the_key_endpoint(status, expected):
    seen = []

    def respond(request):
        seen.append((request.method, str(request.url), request.headers["authorization"]))
        return httpx.Response(status, json={"data": {}})
    config = Settings(_env_file=None, openrouter_api_key="test-only-key", openrouter_model="vendor/model")
    health = asyncio.run(OpenRouterProvider(config, transport=httpx.MockTransport(respond)).health())
    assert health.status == expected and health.provider == "openrouter" and health.model == "vendor/model"
    assert seen == [("GET", "https://openrouter.ai/api/v1/key", "Bearer test-only-key")]
    assert "test-only-key" not in health.detail


def test_openrouter_timeout_has_its_own_message():
    def respond(request):
        raise httpx.ReadTimeout("lento", request=request)
    config = Settings(_env_file=None, openrouter_api_key="test-only-key", openrouter_model="vendor/model")
    provider = OpenRouterProvider(config, transport=httpx.MockTransport(respond))
    with pytest.raises(ChatProviderUnavailable) as caught:
        asyncio.run(provider.complete(messages=[{"role": "user", "content": "x"}], tools=[]))
    assert caught.value.reason == "timeout" and "tardó demasiado" in caught.value.public_message


def test_health_endpoint_requires_monitoring_permission_and_hides_secrets(client, admin_user, viewer_user, login):
    assert client.get("/api/v1/chat/health").status_code == 401
    _, headers = login("viewer@example.com", "viewer-password")
    response = client.get("/api/v1/chat/health", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"provider": "openrouter", "model": None, "status": "not_configured",
                               "detail": "El chatbot no está configurado."}
