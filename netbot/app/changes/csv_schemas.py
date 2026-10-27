from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from .schemas import VlanReservationCreate, VlanReservationRead


class CsvRow(BaseModel):
    row_number: int
    data: VlanReservationCreate | None = None
    errors: list[str] = Field(default_factory=list)


class CsvLimits(BaseModel):
    max_bytes: int
    max_rows: int
    ttl_seconds: int


class CsvResult(BaseModel):
    row_number: int
    reservation: VlanReservationRead


class CsvImportRead(BaseModel):
    id: str
    filename: str
    status: Literal["preview", "confirmed", "cancelled", "expired"]
    source: str
    simulated: bool
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None
    rows: list[CsvRow]
    valid_count: int
    invalid_count: int
    results: list[CsvResult]


class CsvImportSummary(BaseModel):
    id: str
    filename: str
    status: Literal["preview", "confirmed", "cancelled", "expired"]
    created_at: datetime


class CsvConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_numbers: list[int] = Field(min_length=1, max_length=1000)

    @field_validator("row_numbers")
    @classmethod
    def unique_positive_rows(cls, rows):
        if any(row < 2 for row in rows) or len(rows) != len(set(rows)):
            raise ValueError("Selecciona filas de datos distintas.")
        return sorted(rows)
