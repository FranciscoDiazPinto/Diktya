"""Contrato común de proveedores LLM y adaptador de OpenRouter.

El proveedor se elige por configuración (LLM_PROVIDER). Los agentes y el chat solo
conocen `ChatProvider`: cambiar de proveedor no modifica su código.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"

# Motivos públicos: nunca incluyen el cuerpo, la clave ni cabeceras del proveedor.
REASONS = {
    "not_configured": "El chatbot no está configurado.",
    "unauthorized": "El proveedor de IA rechazó la credencial configurada. Avisa al administrador.",
    "rate_limited": "El proveedor de IA alcanzó su límite de uso. Inténtalo en unos minutos.",
    "timeout": "El proveedor de IA tardó demasiado en responder. Inténtalo nuevamente.",
    "refused": "El asistente no puede responder esa solicitud.",
    "unavailable": "El chatbot no pudo completar la consulta. Inténtalo nuevamente.",
}


class ChatProviderError(RuntimeError):
    """Error de proveedor seguro para exponer a la API de Netbot."""

    reason = "unavailable"

    def __init__(self, message: str = "", *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason

    @property
    def public_message(self) -> str:
        return REASONS.get(self.reason, REASONS["unavailable"])


class ChatProviderNotConfigured(ChatProviderError):
    """Falta configurar la clave o el modelo del proveedor."""

    reason = "not_configured"


class ChatProviderUnavailable(ChatProviderError):
    """El proveedor no respondió con una respuesta válida."""


@dataclass(frozen=True, slots=True)
class ProviderToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    content: str | None
    tool_calls: tuple[ProviderToolCall, ...] = ()
    # Turno del asistente en el formato nativo del proveedor, cuando debe reenviarse
    # íntegro en la ronda siguiente (p. ej. bloques de razonamiento junto a tool_use).
    raw_content: Any = None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    model: str | None
    status: str  # ok | not_configured | unauthorized | rate_limited | timeout | unavailable

    @property
    def detail(self) -> str:
        return "Conexión verificada." if self.status == "ok" else REASONS.get(self.status, REASONS["unavailable"])


class ChatProvider(Protocol):
    name: str

    async def complete(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderCompletion: ...

    async def health(self) -> ProviderHealth: ...


def http_failure(exc: Exception) -> ChatProviderUnavailable:
    """Clasifica un fallo HTTP sin conservar la respuesta del proveedor."""
    reason = "unavailable"
    if isinstance(exc, httpx.TimeoutException):
        reason = "timeout"
    elif isinstance(exc, httpx.HTTPStatusError):
        reason = {401: "unauthorized", 403: "unauthorized", 429: "rate_limited"}.get(exc.response.status_code, reason)
    return ChatProviderUnavailable("El proveedor no pudo completar la solicitud.", reason=reason)


class OpenRouterProvider:
    name = "openrouter"

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
            "max_tokens": self._settings.chat_max_output_tokens,
            # Solo proveedores que no retienen ni entrenan con el contenido.
            "provider": {"data_collection": self._settings.openrouter_data_collection},
        }
        if tools:
            payload.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
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
        except httpx.HTTPError as exc:
            raise http_failure(exc) from None
        except (ValueError, TypeError, KeyError, IndexError):
            raise ChatProviderUnavailable("OpenRouter no pudo completar la solicitud.") from None

    async def health(self) -> ProviderHealth:
        """Comprueba la credencial sin consumir tokens del modelo."""
        api_key, model = self._settings.openrouter_api_key, self._settings.openrouter_model
        if api_key is None or not api_key.get_secret_value().strip() or not model:
            return ProviderHealth(self.name, model, "not_configured")
        try:
            async with httpx.AsyncClient(transport=self._transport,
                                         timeout=self._settings.openrouter_timeout_seconds) as client:
                response = await client.get(OPENROUTER_KEY_URL, headers={
                    "Authorization": f"Bearer {api_key.get_secret_value()}", "Accept": "application/json"})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(self.name, model, http_failure(exc).reason)
        return ProviderHealth(self.name, model, "ok")

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


def build_provider(settings: Settings) -> ChatProvider:
    """Selecciona el adaptador por configuración; los consumidores solo ven `ChatProvider`."""
    if settings.llm_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(settings)
    return OpenRouterProvider(settings)
