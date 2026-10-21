from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VlanReservationCreate(StrictModel):
    parent_interface: str = Field(min_length=1, max_length=64)
    tag: int = Field(ge=1, le=4094)
    event_name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=500)
    ssid: str = Field(min_length=1, max_length=64)


class VlanReservationRead(StrictModel):
    id: int
    parent_interface: str
    tag: int
    description: str | None
    interface_name: str
    event_name: str
    purpose: str
    ssid: str
    status: str
    requested_by_id: int
    created_at: datetime
    released_by_id: int | None
    released_at: datetime | None

    @classmethod
    def from_model(cls, row):
        return cls.model_validate({name: getattr(row, name) for name in cls.model_fields})


class AvailableVlan(StrictModel):
    parent_interface: str
    tag: int
    description: str | None
    interface_name: str
