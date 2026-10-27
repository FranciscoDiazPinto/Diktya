from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.networks.support_schemas import NetworkStatus

TicketState = Literal["open", "in_progress", "resolved", "closed"]


class TicketProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    network_id: int = Field(gt=0)
    summary: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=1, max_length=2000)


class TicketCreate(TicketProposal):
    request_key: UUID


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    network_id: int
    created_by_id: int
    summary: str
    description: str
    status: TicketState
    version: int
    network_snapshot: NetworkStatus
    created_at: datetime
    updated_at: datetime


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: TicketState
    version: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)


class TicketEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: TicketState
    note: str
    created_at: datetime


class TicketDetail(TicketRead):
    events: list[TicketEventRead]
