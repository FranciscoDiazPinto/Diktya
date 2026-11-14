"""Criticidad de tickets: reglas configurables y tiempos máximos de atención."""

import json
from datetime import datetime, timedelta

from app.core.config import Settings

LEVELS = ("baja", "media", "alta", "critica")
DEFAULT_RULES = {
    "device_offline": "alta",
    "device_degraded": "media",
    "device_missing": "media",
    "source_unavailable": "critica",
    "source_degraded": "media",
    "ssid_missing": "media",
    "ssid_disabled": "media",
    "vlan_missing": "media",
    "vlan_disabled": "media",
    "verification_failed": "alta",
    "restart_failed": "alta",
    "agent_failed": "alta",
    "rollback_failed": "critica",
}
DEFAULT_ATTENTION_MINUTES = {"critica": 15, "alta": 30, "media": 120, "baja": 480}
_CORE_DEVICES = {"gateway", "firewall"}


def _load(raw: str | None, name: str) -> dict:
    if raw is None:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{name} no es JSON válido") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{name} debe ser un objeto JSON")
    return data


def criticality_rules(settings: Settings) -> dict[str, str]:
    overrides = _load(settings.ticket_criticality_rules_json, "TICKET_CRITICALITY_RULES_JSON")
    if any(level not in LEVELS for level in overrides.values()):
        raise ValueError("TICKET_CRITICALITY_RULES_JSON solo admite: " + ", ".join(LEVELS))
    return {**DEFAULT_RULES, **overrides}


def attention_minutes(settings: Settings) -> dict[str, float]:
    overrides = _load(settings.ticket_attention_minutes_json, "TICKET_ATTENTION_MINUTES_JSON")
    minutes = {**DEFAULT_ATTENTION_MINUTES, **overrides}
    if set(minutes) != set(LEVELS) or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0 for v in minutes.values()
    ):
        raise ValueError("TICKET_ATTENTION_MINUTES_JSON requiere minutos positivos por criticidad")
    return minutes


def attention_due(level: str, now: datetime, settings: Settings) -> datetime:
    return now + timedelta(minutes=attention_minutes(settings)[level])


def raised(level: str) -> str:
    return LEVELS[min(LEVELS.index(level) + 1, len(LEVELS) - 1)]


def classify(incident_type: str, *, device_type: str | None, affected: int, settings: Settings) -> tuple[str, bool]:
    """(criticidad, requiere revisión). Sin regla para el tipo, Media y revisión manual."""
    level = criticality_rules(settings).get(incident_type)
    if level is None:
        return "media", True
    if incident_type == "device_offline" and device_type in _CORE_DEVICES:
        return "critica", False  # sin gateway o firewall cae la red completa
    if affected >= settings.ticket_mass_incident_devices:
        return raised(level), False
    return level, False
