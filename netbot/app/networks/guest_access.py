"""Acceso público explícito. Nunca hereda asignaciones o permisos de usuarios."""
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.core.errors import NotFound, ServiceUnavailable
from .recipients import matching_networks
from .models import Network
from .support_models import NetworkSupportConfig
from .credentials import credential_for
from .wifi_qr import wifi_qr_data_url


class GuestNetwork(BaseModel):
    id: int
    name: str
    ssid: str


class GuestWifiQr(BaseModel):
    ssid: str
    qr_data_url: str


def list_guest_networks(db: Session, settings: Settings) -> list[GuestNetwork]:
    # El acceso anónimo solo publica redes ABIERTAS (p. ej. portal cautivo).
    rows = db.scalars(select(Network).where(Network.id.in_(settings.guest_wifi_network_ids)).order_by(Network.id))
    public = []
    for network in rows:
        try:
            credential = credential_for(network, db.get(NetworkSupportConfig, network.id), settings)
        except ServiceUnavailable:
            continue
        if credential.security == 'open':
            public.append(GuestNetwork(id=network.id, name=network.name, ssid=network.ssid))
    return public


def client_networks(db: Session, contact: tuple[str, str]) -> list[GuestNetwork]:
    return [GuestNetwork(id=n.id, name=n.name, ssid=n.ssid) for n in matching_networks(db, contact)]


def guest_wifi_qr(db: Session, settings: Settings, network_id: int, contact: tuple[str, str] | None = None) -> GuestWifiQr:
    authorized = contact is not None and any(n.id == network_id for n in matching_networks(db, contact))
    network = db.get(Network, network_id)
    if network is None or (not authorized and network_id not in settings.guest_wifi_network_ids):
        raise NotFound('No se pudo habilitar ese acceso. Revisa tus datos o solicita ayuda al equipo.')
    credential = credential_for(network, db.get(NetworkSupportConfig, network_id), settings)
    if not authorized and credential.security != 'open':
        raise NotFound('No se pudo habilitar ese acceso. Revisa tus datos o solicita ayuda al equipo.')
    return GuestWifiQr(ssid=credential.ssid, qr_data_url=wifi_qr_data_url(credential))
