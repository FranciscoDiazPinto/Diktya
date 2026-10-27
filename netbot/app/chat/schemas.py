"""Contratos y límites para mensajes conversacionales."""

from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.networks.support_schemas import WifiAccessAction
from app.tickets.schemas import TicketProposal


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class ChatSendRequest(BaseModel):
    """Contrato HTTP: el historial nunca se acepta desde el navegador."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1)
    conversation_id: UUID | None = None
    version: int | None = Field(default=None, ge=0)


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="Nueva conversación", min_length=1, max_length=100)
    network_id: int | None = Field(default=None, gt=0)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    network_id: int | None
    version: int
    created_at: datetime
    updated_at: datetime


class StoredMessageRead(ChatTurn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[StoredMessageRead]


class VlanReservationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_interface: str
    tag: int
    description: str | None
    interface_name: str
    event_name: str
    purpose: str
    ssid: str


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    tools_used: list[str] = Field(default_factory=list)
    reservation_proposal: VlanReservationProposal | None = None
    wifi_access_action: WifiAccessAction | None = None
    ticket_proposal: TicketProposal | None = None
    conversation_id: str | None = None
    version: int | None = None


class ChatInputError(ValueError):
    """Mensaje o historial excede los límites del chatbot."""


def normalize_chat_request(
    request: ChatMessageRequest, settings: Settings
) -> ChatMessageRequest:
    message = request.message.strip()
    if not message:
        raise ChatInputError("El mensaje no puede estar vacío.")
    if len(message) > settings.chat_max_message_chars:
        raise ChatInputError("El mensaje supera el largo máximo permitido.")

    history_limit = settings.chat_max_history_turns
    history = request.history[-history_limit:] if history_limit else []
    history_size = sum(len(turn.content) for turn in history)
    if history_size > settings.chat_max_history_chars:
        raise ChatInputError("El historial supera el largo máximo permitido.")

    return request.model_copy(update={"message": message, "history": history})
