"""Adaptador directo de Claude (API de Anthropic) para el contrato `ChatProvider`.

El chat construye mensajes y herramientas en el formato de chat completions; este
adaptador los traduce a la Messages API y normaliza la respuesta. La clave permanece en
el backend y ningún error conserva el cuerpo del proveedor.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.core.config import Settings

from .provider import (
    ChatProviderError,
    ChatProviderNotConfigured,
    ChatProviderUnavailable,
    ProviderCompletion,
    ProviderHealth,
    ProviderToolCall,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool["function"]
    return {"name": function["name"], "description": function.get("description", ""),
            "input_schema": function["parameters"]}


def to_anthropic_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(system, messages). Los resultados de herramientas de una ronda van en un solo turno de usuario."""
    system: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            system.append(message["content"])
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}
            previous = converted[-1] if converted else None
            if previous and previous["role"] == "user" and isinstance(previous["content"], list):
                previous["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        elif role == "assistant" and message.get("tool_calls"):
            # El turno original incluye bloques de razonamiento que deben volver intactos.
            content = message.get("_provider_content")
            if content is None:
                content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
                content += [{"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                             "input": json.loads(call["function"]["arguments"])} for call in message["tool_calls"]]
            converted.append({"role": "assistant", "content": content})
        else:
            converted.append({"role": role, "content": message["content"]})
    # La política es estable entre solicitudes: se marca para reutilizar el prefijo en caché.
    blocks = [{"type": "text", "text": "\n".join(system), "cache_control": {"type": "ephemeral"}}] if system else []
    return blocks, converted


def _failure(exc: Exception) -> ChatProviderUnavailable:
    reason = "unavailable"
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        reason = "unauthorized"
    elif isinstance(exc, anthropic.RateLimitError):
        reason = "rate_limited"
    elif isinstance(exc, anthropic.APITimeoutError):
        reason = "timeout"
    return ChatProviderUnavailable("Claude no pudo completar la solicitud.", reason=reason)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings, *, client: Any = None) -> None:
        self._settings = settings
        self._injected = client

    def _client(self):
        api_key, model = self._settings.anthropic_api_key, self._settings.anthropic_model
        if api_key is None or not api_key.get_secret_value().strip() or not model:
            raise ChatProviderNotConfigured("El proveedor de chat no está configurado.")
        if self._injected is not None:
            return self._injected
        return anthropic.AsyncAnthropic(api_key=api_key.get_secret_value(), max_retries=1,
                                        timeout=self._settings.anthropic_timeout_seconds)

    async def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderCompletion:
        client = self._client()
        system, converted = to_anthropic_messages(messages)
        params: dict[str, Any] = {
            "model": self._settings.anthropic_model,
            "max_tokens": self._settings.anthropic_max_tokens,
            "messages": converted,
            "output_config": {"effort": self._settings.anthropic_effort},
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [to_anthropic_tool(tool) for tool in tools]
        try:
            if self._settings.anthropic_refusal_fallback:
                # Ante un rechazo de los clasificadores, la API reintenta en el modelo de respaldo.
                response = await client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
            else:
                response = await client.messages.create(**params)
        except anthropic.APIError as exc:
            raise _failure(exc) from None
        return self._parse(response)

    @staticmethod
    def _parse(response: Any) -> ProviderCompletion:
        if response.stop_reason == "refusal":
            raise ChatProviderError("Claude rechazó la solicitud.", reason="refused")
        text: list[str] = []
        calls: list[ProviderToolCall] = []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                if not isinstance(block.input, dict) or not block.id or not block.name:
                    raise ChatProviderUnavailable("Claude devolvió una llamada de herramienta inválida.")
                calls.append(ProviderToolCall(id=block.id, name=block.name, arguments=block.input))
        if response.stop_reason == "max_tokens" and not calls:
            raise ChatProviderUnavailable("Claude agotó el límite de salida antes de responder.")
        content = "".join(text) or None
        return ProviderCompletion(content=content, tool_calls=tuple(calls),
                                  raw_content=list(response.content) if calls else None)

    async def health(self) -> ProviderHealth:
        """Verifica credencial y modelo sin generar tokens."""
        model = self._settings.anthropic_model
        try:
            client = self._client()
        except ChatProviderNotConfigured:
            return ProviderHealth(self.name, model, "not_configured")
        try:
            await client.models.retrieve(model)
        except anthropic.NotFoundError:
            return ProviderHealth(self.name, model, "unavailable")
        except anthropic.APIError as exc:
            return ProviderHealth(self.name, model, _failure(exc).reason)
        return ProviderHealth(self.name, model, "ok")
