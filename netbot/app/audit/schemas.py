from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

Source = Literal["auth", "support", "tickets", "reservations", "csv", "ssid"]


class AuditFilters(BaseModel):
    actor_id: int | None = Field(None, ge=1)
    source: Source | None = None
    action: str | None = Field(None, min_length=1, max_length=80)
    outcome: str | None = Field(None, min_length=1, max_length=32)
    since: datetime | None = None
    until: datetime | None = None

    @field_validator("since", "until")
    @classmethod
    def require_timezone(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("La fecha requiere zona horaria.")
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode="after")
    def chronological(self):
        if self.since and self.until and self.since > self.until:
            raise ValueError("La fecha inicial no puede superar la final.")
        return self


class AuditEntry(BaseModel):
    source: Source
    event_id: str
    occurred_at: datetime
    actor_id: int | None
    action: str
    outcome: str
    resource_type: str
    resource_id: str | None
    snapshot: bool

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int
