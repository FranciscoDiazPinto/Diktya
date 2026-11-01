"""Conversión de payloads de UniFi a los modelos internos. Único módulo que conoce su forma.

Lo que la API no permite resolver queda desconocido: una referencia de red rota no cae
en la VLAN por defecto y un equipo sin `features` no se clasifica por su modelo.
"""

from typing import Any

from ...schemas import (
    DeviceState,
    DeviceType,
    InventoryDevice,
    InventorySsid,
    InventoryVlan,
    normalize_mac,
)

_STATES = {
    "ONLINE": DeviceState.ONLINE,
    "OFFLINE": DeviceState.OFFLINE,
    "CONNECTION_INTERRUPTED": DeviceState.DEGRADED,
    "ISOLATED": DeviceState.DEGRADED,
    "PENDING_ADOPTION": DeviceState.MAINTENANCE,
    "ADOPTING": DeviceState.MAINTENANCE,
    "GETTING_READY": DeviceState.MAINTENANCE,
    "UPDATING": DeviceState.MAINTENANCE,
    "DELETING": DeviceState.MAINTENANCE,
}


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _identifier(row: dict[str, Any]) -> str:
    identifier = _text(row.get("id"))
    if identifier is None:
        raise ValueError("Recurso de UniFi sin id")
    return identifier


def _mac(value: Any) -> str | None:
    try:
        return normalize_mac(value) if isinstance(value, str) else None
    except ValueError:
        return None


def resolve_site_id(sites: list[dict[str, Any]], wanted: str | None) -> str:
    """Selecciona por UUID o `internalReference`, nunca por el nombre visible."""
    if wanted is None:
        if len(sites) == 1:
            return _identifier(sites[0])
        raise ValueError("UNIFI_SITE es obligatorio cuando la consola tiene varios sitios")
    for site in sites:
        if wanted in (site.get("id"), site.get("internalReference")):
            return _identifier(site)
    raise ValueError("UNIFI_SITE no coincide con ningún sitio de la consola")


def map_device(row: dict[str, Any]) -> InventoryDevice:
    identifier = _identifier(row)
    features = row.get("features")
    features = set(features) if isinstance(features, list) else set()
    if "gateway" in features:
        device_type = DeviceType.GATEWAY
    elif "accessPoint" in features:
        device_type = DeviceType.ACCESS_POINT
    elif "switching" in features:
        device_type = DeviceType.SWITCH
    else:
        device_type = DeviceType.UNKNOWN
    return InventoryDevice(
        external_id=identifier,
        name=_text(row.get("name")) or _text(row.get("model")) or identifier,
        device_type=device_type,
        model=_text(row.get("model")),
        mac_address=_mac(row.get("macAddress")),
        ip_address=_text(row.get("ipAddress")),
        state=_STATES.get(str(row.get("state")), DeviceState.UNKNOWN),
    )


def map_network(row: dict[str, Any]) -> InventoryVlan | None:
    tag = row.get("vlanId")
    if isinstance(tag, bool) or not isinstance(tag, int) or not 1 <= tag <= 4094:
        return None
    enabled = row.get("enabled")
    return InventoryVlan(external_id=_identifier(row), name=_text(row.get("name")), tag=tag,
                         enabled=enabled if isinstance(enabled, bool) else None)


def _vlan_tag(reference: Any, networks: list[dict[str, Any]] | None) -> int | None:
    """Ausente o NATIVE usan la red por defecto; SPECIFIC exige encontrar la red."""
    if networks is None:
        return None
    if isinstance(reference, dict) and reference.get("type") == "SPECIFIC":
        match = next((n for n in networks if n.get("id") == reference.get("networkId")), None)
    else:
        match = next((n for n in networks if n.get("default") is True), None)
    tag = match.get("vlanId") if match else None
    return tag if isinstance(tag, int) and not isinstance(tag, bool) else None


def map_broadcast(row: dict[str, Any], networks: list[dict[str, Any]] | None) -> InventorySsid:
    security = row.get("securityConfiguration")
    return InventorySsid(
        external_id=_identifier(row),
        name=_text(row.get("name")) or _identifier(row),
        enabled=row.get("enabled") is True,
        security=_text(security.get("type")) if isinstance(security, dict) else None,
        vlan_tag=_vlan_tag(row.get("network"), networks),
    )
