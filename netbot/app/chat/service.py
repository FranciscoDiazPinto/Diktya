"""Orquestación de respuestas y herramientas controladas del chatbot."""

from __future__ import annotations

import json
from typing import Any

from app.auth.permissions import Permission
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from app.changes.service import VlanReservationService

from .policy import policy_for_profile
from .support import CustomerSupport
from app.networks.support_schemas import WifiAccessAction
from app.tickets.schemas import TicketProposal
from .provider import (
    ChatProviderError,
    OpenRouterProvider,
    ProviderCompletion,
)
from .schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatTurn,
    normalize_chat_request,
    VlanReservationProposal,
)
from .tools import (
    ChatToolError,
    ChatToolPermissionError,
    invoke_tool,
    openrouter_tool_definitions,
)


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: OpenRouterProvider,
        monitoring_service: MonitoringService,
        reservation_service: VlanReservationService | None = None,
        customer_support: CustomerSupport | None = None,
    ) -> None:
        self._settings = settings
        self._provider = provider
        self._monitoring = monitoring_service
        self._reservations = reservation_service
        self._support = customer_support

    async def answer(
        self,
        *,
        message: str,
        history: list[ChatTurn],
        permissions: frozenset[Permission],
        networks: list[dict] | None = None,
        profile: str = "visor",
    ) -> ChatMessageResponse:
        request = normalize_chat_request(
            ChatMessageRequest(message=message, history=history), self._settings
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": policy_for_profile(profile)},
            *(
                {"role": turn.role, "content": turn.content}
                for turn in request.history
            ),
            {"role": "user", "content": request.message},
        ]
        tools = openrouter_tool_definitions(permissions)
        tools_used: list[str] = []
        proposal = None
        access_action = None
        ticket_proposal = None
        seen_call_ids: set[str] = set()
        tool_rounds = 0

        while True:
            completion = await self._provider.complete(messages=messages, tools=tools)
            if not completion.tool_calls:
                answer = (completion.content or "").strip()
                if not answer:
                    raise ChatProviderError("OpenRouter no devolvió una respuesta de texto.")
                return ChatMessageResponse(answer=answer, tools_used=tools_used,
                                           reservation_proposal=proposal, wifi_access_action=access_action,
                                           ticket_proposal=ticket_proposal)

            if tool_rounds >= self._settings.chat_max_tool_rounds:
                raise ChatProviderError("OpenRouter superó el límite de consultas de monitoreo.")

            for call in completion.tool_calls:
                if call.id in seen_call_ids:
                    raise ChatProviderError("OpenRouter devolvió una llamada de herramienta repetida.")
                seen_call_ids.add(call.id)

            messages.append(self._assistant_tool_message(completion))
            for call in completion.tool_calls:
                try:
                    result = await invoke_tool(
                        call.name,
                        call.arguments,
                        self._monitoring,
                        permissions,
                        self._reservations,
                        networks,
                        self._support,
                    )
                except ChatToolPermissionError:
                    raise
                except ChatToolError:
                    raise ChatProviderError(
                        "OpenRouter solicitó una herramienta o argumentos no permitidos."
                    ) from None
                if call.name not in tools_used:
                    tools_used.append(call.name)
                if call.name == "prepare_vlan_reservation":
                    proposal = VlanReservationProposal.model_validate(result)
                if call.name == "offer_wifi_access" and result.get("action"):
                    access_action = WifiAccessAction.model_validate(result["action"])
                if call.name == "prepare_support_ticket":
                    ticket_proposal = TicketProposal.model_validate(result["proposal"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                    }
                )
            tool_rounds += 1

    @staticmethod
    def _assistant_tool_message(completion: ProviderCompletion) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": completion.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments, ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                }
                for call in completion.tool_calls
            ],
        }
