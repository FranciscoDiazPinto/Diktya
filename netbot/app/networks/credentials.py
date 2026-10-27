"""Entrega de secretos Wi-Fi, fuera de las herramientas del LLM."""
import json
import re
from sqlalchemy.orm import Session
from pydantic import ValidationError
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings
from app.core.errors import ServiceUnavailable
from .access import authorize
from .models import Network
from .support_models import NetworkSupportConfig
from .support_schemas import WifiCredential, WifiAccessRead, WifiAccessAction
from .audit import record_audit

def credential_for(network: Network, config: NetworkSupportConfig | None, settings: Settings) -> WifiCredential:
    error = ServiceUnavailable("El acceso Wi-Fi no está configurado para esta red. Contacta a soporte.")
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
    record_audit(db, user.id, network_id, "wifi_access.revealed")
    db.commit()
    return WifiAccessRead(network_id=network_id, ssid=credential.ssid, security=credential.security,
                          passphrase=credential.passphrase.get_secret_value() if credential.security != "open" and credential.passphrase else None)
