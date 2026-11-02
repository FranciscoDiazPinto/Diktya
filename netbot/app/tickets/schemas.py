from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.networks.support_schemas import NetworkStatus

TicketState = Literal["open", "in_progress", "resolved", "closed"]
Criticality = Literal["baja", "media", "alta", "critica"]


class TicketProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    network_id: int = Field(gt=0)
    summary: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=1, max_length=2000)


class TicketCreate(TicketProposal):
    request_key: UUID


class TicketManualCreate(BaseModel):
    """Ticket abierto por técnico o administrador; la red y el equipo son opcionales."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    criticality: Criticality = "media"
    network_id: int | None = Field(default=None, gt=0)
    device_id: int | None = Field(default=None, gt=0)
    request_key: UUID


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    network_id: int | None
    created_by_id: int | None
    summary: str
    description: str
    status: TicketState
    version: int
    network_snapshot: NetworkStatus | None
    source: str
    criticality: Criticality
    needs_review: bool
    incident_type: str | None
    alert_id: int | None
    device_id: int | None
    device_name: str | None
    evidence: dict | None
    assignee_id: int | None
    resolution: str | None
    attention_due_at: datetime | None
    escalations: int
    created_at: datetime
    updated_at: datetime


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: TicketState
    version: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)


class TicketAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)


class TicketComment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=1, max_length=1000)


class TicketCriticalityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    criticality: Criticality
    version: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)


class TicketEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: TicketState
    note: str
    created_at: datetime


class DeliveryRead(BaseModel):
    """Registro de envío visible para quien gestiona el ticket."""
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    channel: str
    event: str
    status: str
    attempts: int
    sent_at: datetime | None
    read_at: datetime | None


class TicketDetail(TicketRead):
    events: list[TicketEventRead]
    deliveries: list[DeliveryRead] = Field(default_factory=list)


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticket_id: int
    event: str
    criticality: Criticality
    highlighted: bool
    title: str
    body: str
    link: str
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    unread: int
