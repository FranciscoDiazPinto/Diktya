"""Cliente HTTP de chat completions de OpenRouter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class ChatProviderError(RuntimeError):
    """Error de proveedor seguro para exponer a la API de Netbot."""


class ChatProviderNotConfigured(ChatProviderError):
    """Falta configurar la clave o el modelo de OpenRouter."""


class ChatProviderUnavailable(ChatProviderError):
    """OpenRouter no respondió con una respuesta válida."""


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    content: str | None
    tool_calls: tuple[ProviderToolCall, ...] = ()


class ChatProvider(Protocol):
    async def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderCompletion: ...


class OpenRouterProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderCompletion:
        api_key = self._settings.openrouter_api_key
        model = self._settings.openrouter_model
        if api_key is None or not api_key.get_secret_value().strip() or not model:
            raise ChatProviderNotConfigured("El proveedor de chat no está configurado.")

        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": self._settings.chat_max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._settings.openrouter_timeout_seconds,
            ) as client:
                response = await client.post(OPENROUTER_CHAT_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            return self._parse_completion(data)
        except ChatProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise ChatProviderUnavailable("OpenRouter no pudo completar la solicitud.") from None

    @staticmethod
    def _parse_completion(data: Any) -> ProviderCompletion:
        try:
            message = data["choices"][0]["message"]
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise TypeError

            raw_calls = message.get("tool_calls") or []
            if not isinstance(raw_calls, list):
                raise TypeError

            calls: list[ProviderToolCall] = []
            for raw_call in raw_calls:
                function = raw_call["function"]
                arguments = function.get("arguments", "{}")
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise TypeError
                call_id = raw_call["id"]
                name = function["name"]
                if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                    raise TypeError
                calls.append(ProviderToolCall(id=call_id, name=name, arguments=arguments))
            return ProviderCompletion(content=content, tool_calls=tuple(calls))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            raise ChatProviderUnavailable("OpenRouter devolvió una respuesta inválida.") from None
