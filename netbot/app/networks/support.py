"""Diagnóstico acotado y entrega de acceso Wi-Fi sin pasar secretos al LLM."""
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from app.monitoring.schemas import MonitoringStatus
from .access import require_network
from .models import Network
from .support_models import NetworkSupportConfig, SupportAudit
from .support_schemas import NetworkStatus, WifiCredential, WifiAccessRead, WifiAccessAction


def authorize(db: Session, user: User, permission: Permission, network_id: int) -> Network:
    db.expire_all()
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario inactivo.")
    if permission not in effective_permissions(user):
        raise HTTPException(status_code=403, detail="Permiso insuficiente.")
    return require_network(db, user, network_id)


def credential_for(network: Network, config: NetworkSupportConfig | None, settings: Settings) -> WifiCredential:
    error = HTTPException(status_code=503, detail="El acceso Wi-Fi no está configurado para esta red. Contacta a soporte.")
    if not config or not config.credential_ref or not settings.wifi_access_credentials_json:
        raise error
    try:
        values = json.loads(settings.wifi_access_credentials_json.get_secret_value())
        credential = WifiCredential.model_validate(values[config.credential_ref])
    except (ValueError, TypeError, KeyError, ValidationError):
        # No propagar errores de validación que puedan contener secretos.
        raise error from None
    if (credential.site, credential.external_id, credential.ssid) != (network.site, network.external_id, network.ssid):
        raise error
    password = credential.passphrase.get_secret_value() if credential.passphrase else None
    if credential.security == "open":
        if password:
            raise error
    elif not password or not (
        8 <= len(password) <= 63 or
        (credential.security == "wpa2-personal" and re.fullmatch(r"[0-9a-fA-F]{64}", password))
    ):
        raise error
    return credential


def wifi_action(db: Session, user: User, network_id: int, settings: Settings) -> WifiAccessAction:
    network = authorize(db, user, Permission.WIFI_ACCESS_READ_OWN, network_id)
    credential_for(network, db.get(NetworkSupportConfig, network_id), settings)
    # Solo metadatos. Nunca incluir la clave ni la referencia del secreto en el chat.
    return WifiAccessAction(network_id=network_id, ssid=network.ssid)


def reveal_wifi(db: Session, user: User, network_id: int, settings: Settings) -> WifiAccessRead:
    network = authorize(db, user, Permission.WIFI_ACCESS_READ_OWN, network_id)
    credential = credential_for(network, db.get(NetworkSupportConfig, network_id), settings)
    db.add(SupportAudit(actor_id=user.id, network_id=network_id, action="wifi_access.revealed"))
    db.commit()
    return WifiAccessRead(network_id=network_id, ssid=credential.ssid, security=credential.security,
                          passphrase=credential.passphrase.get_secret_value() if credential.security != "open" and credential.passphrase else None)


async def network_status(db: Session, user: User, network_id: int,
                         monitoring: MonitoringService, settings: Settings) -> NetworkStatus:
    network = authorize(db, user, Permission.NETWORKS_READ_OWN, network_id)
    config = db.get(NetworkSupportConfig, network_id)
    base = dict(network_id=network_id, checked_at=datetime.now(timezone.utc),
                source=settings.monitoring_provider, simulated=settings.monitoring_provider == "mock")
    if not config or not config.monitoring_interface_id or not settings.monitoring_site_id:
        return NetworkStatus(**base, summary="Falta configurar la comprobación de esta red; no se conoce su disponibilidad.")
    if network.site != settings.monitoring_site_id:
        return NetworkStatus(**base, summary="La fuente de monitoreo no corresponde al sitio de esta red.")
    interface_id = config.monitoring_interface_id
    response = await monitoring.get_interfaces()
    # No devolver datos que hayan perdido autorización mientras se consultaba la fuente.
    network = authorize(db, user, Permission.NETWORKS_READ_OWN, network_id)
    config = db.get(NetworkSupportConfig, network_id)
    if not config or config.monitoring_interface_id != interface_id or network.site != settings.monitoring_site_id:
        return NetworkStatus(**base, summary="La configuración de monitoreo cambió; vuelve a consultar.")
    observed = response.collected_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    base.update(source=response.source, simulated=response.source == "mock", observed_at=observed)
    if response.source != settings.monitoring_provider or age < -5 or age > settings.network_status_max_age_seconds:
        return NetworkStatus(**base, summary="La telemetría no es vigente o no corresponde a la fuente configurada.")
    if response.status != MonitoringStatus.OK or response.data is None:
        return NetworkStatus(**base, summary="El monitoreo no está disponible o es incompleto; esto no demuestra que tu red esté caída.")
    matches = [interface for interface in response.data if interface.interface_id == interface_id]
    if len(matches) != 1:
        return NetworkStatus(**base, summary="No se encontró una interfaz inequívoca para esta red; solicita revisión técnica.")
    status = matches[0].status.value
    if status == "down":
        return NetworkStatus(**base, state="issue_detected", interface_status="down",
                             summary="La interfaz asociada a tu red aparece caída. Puedes abrir un ticket para revisión.")
    if status == "up":
        return NetworkStatus(**base, state="partially_verified", interface_status="up",
                             summary="La interfaz asociada está activa. Aún no se han verificado el Wi-Fi ni la salida a Internet.")
    return NetworkStatus(**base, summary="La fuente no informa un estado verificable de la interfaz de tu red.")
