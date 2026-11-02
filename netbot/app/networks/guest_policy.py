"""Política de autoatención: exposición explícita y exclusión de redes internas."""
import re
import unicodedata

RESTRICTED = {'admin', 'administracion', 'administration', 'management', 'marketing', 'servicio', 'servicios', 'services'}


def restricted_network(network, config) -> bool:
    purpose = config.guest_recovery_purpose if config else 'disabled'
    name = unicodedata.normalize('NFKD', network.name + ' ' + network.ssid)
    words = set(re.findall(r'[a-z]+', ''.join(c for c in name.lower() if not unicodedata.combining(c))))
    return purpose in {'administracion', 'marketing', 'servicios'} or bool(words & RESTRICTED)


def expositor_network(network, config) -> bool:
    return bool(config and config.guest_recovery_purpose == 'expositor' and not restricted_network(network, config))


def lock_recovery_networks(db, network_ids):
    from sqlalchemy import update
    from .models import Network
    if network_ids:
        db.execute(update(Network).where(Network.id.in_(sorted(network_ids))).values(name=Network.name))
        db.expire_all()
