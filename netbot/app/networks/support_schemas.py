from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SupportConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)
    credential_ref: str | None = Field(default=None, min_length=1, max_length=160)
    monitoring_interface_id: str | None = Field(default=None, min_length=1, max_length=160)


class NetworkStatus(BaseModel):
    network_id: int
    state: Literal["unknown", "issue_detected", "partially_verified"] = "unknown"
    interface_status: Literal["up", "down", "unknown"] = "unknown"
    wifi_status: Literal["unverified"] = "unverified"
    internet_status: Literal["unverified"] = "unverified"
    source: str
    simulated: bool
    checked_at: datetime
    observed_at: datetime | None = None
    summary: str


class WifiCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site: str
    external_id: str
    ssid: str
    security: Literal["open", "wpa2-personal", "wpa3-personal"]
    passphrase: SecretStr | None = None


class WifiAccessRead(BaseModel):
    network_id: int
    ssid: str
    security: str
    passphrase: str | None


class WifiAccessAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network_id: int
    ssid: str


class SupportAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int
    network_id: int
    action: str
    created_at: datetime
