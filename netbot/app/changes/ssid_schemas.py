from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class NetworkBinding(Strict):
    id: str = Field(min_length=1, max_length=160)
    parent_interface: str = Field(min_length=1, max_length=64)
    tag: int = Field(ge=1, le=4094)


class ScopeWrite(Strict):
    name: str = Field(min_length=1, max_length=160)
    site_id: str = Field(min_length=1, max_length=160)
    event_name: str = Field(min_length=1, max_length=160)
    monitoring_site_id: str | None = Field(default=None, min_length=1, max_length=160)
    ap_ids: list[str] = Field(min_length=1, max_length=100)
    networks: list[NetworkBinding] = Field(min_length=1, max_length=500)
    security_profiles: list[str] = Field(min_length=1, max_length=100)
    user_ids: list[int] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def unique_resources(self):
        if (len(set(self.ap_ids)) != len(self.ap_ids) or len(set(self.security_profiles)) != len(self.security_profiles)
                or len({(n.parent_interface, n.tag) for n in self.networks}) != len(self.networks)
                or len({n.id for n in self.networks}) != len(self.networks)):
            raise ValueError('Los recursos del ámbito deben ser únicos.')
        if any(not v or len(v) > 160 for v in self.ap_ids + self.security_profiles):
            raise ValueError('Identificador de recurso inválido.')
        return self


class SsidProposal(Strict):
    scope_id: int = Field(gt=0)
    ssid: str = Field(min_length=1, max_length=32)
    network_id: str = Field(min_length=1, max_length=160)
    ap_ids: list[str] = Field(min_length=1, max_length=100)
    security_profile: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=500)

    @field_validator('ssid')
    @classmethod
    def utf8_ssid(cls, value):
        if len(value.encode('utf-8')) > 32 or any(ord(c) < 32 for c in value):
            raise ValueError('El SSID admite hasta 32 bytes UTF-8 y no admite caracteres de control.')
        return value

    @field_validator('ap_ids')
    @classmethod
    def unique_aps(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('No repitas AP.')
        return sorted(value)


class SsidCsv(Strict):
    _unique_aps = field_validator("ap_ids")(classmethod(SsidProposal.unique_aps.__func__))

    scope_id: int = Field(gt=0)
    ap_ids: list[str] = Field(min_length=1, max_length=100)
    security_profile: str = Field(min_length=1, max_length=160)
    csv_text: str = Field(min_length=1, max_length=1048576)


class SsidConfirm(Strict):
    revision: str = Field(min_length=64, max_length=64)
    row_numbers: list[int] = Field(min_length=1, max_length=500)

    @field_validator('row_numbers')
    @classmethod
    def unique_numbers(cls, value):
        if min(value) < 1 or len(set(value)) != len(value):
            raise ValueError('Selecciona filas únicas válidas.')
        return sorted(value)


class SsidPlanRead(Strict):
    id: str
    scope_id: int
    status: str
    source: str
    simulated: bool
    revision: str
    rows: list[dict]
    selection: list[int]
    expires_at: datetime
    execution_status: str
    execution_results: list[dict] = Field(default_factory=list)
