from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


from app.monitoring.schemas import AccessPointMetrics, InterfaceMetrics, MonitoringResponse


class SupportConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, from_attributes=True)
    guest_recovery_purpose: Literal["disabled", "expositor", "administracion", "marketing", "servicios"] = "disabled"
    credential_ref: str | None = Field(default=None, min_length=1, max_length=160)
    monitoring_interface_id: str | None = Field(default=None, min_length=1, max_length=160)
    unifi_site_id: str | None = Field(default=None, min_length=1, max_length=160)
    unifi_ap_ids: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def validate_ap_binding(self):
        if self.unifi_ap_ids and not self.unifi_site_id:
            raise ValueError('Indica el sitio UniFi para vincular AP.')
        if len(set(self.unifi_ap_ids))!=len(self.unifi_ap_ids) or any(not a or len(a)>160 for a in self.unifi_ap_ids):
            raise ValueError('Los identificadores de AP deben ser únicos y no vacíos.')
        return self


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
    qr_data_url: str | None = None


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


class NetworkTelemetry(BaseModel):
    network_id: int
    access_points: MonitoringResponse[list[AccessPointMetrics]]
    interfaces: MonitoringResponse[list[InterfaceMetrics]]
