"""Proveedores de concesiones DHCP de OPNsense: Dnsmasq y Kea (DHCPv4)."""

import logging
from datetime import datetime, timezone
from typing import Any

from ...schemas import DhcpLease
from ..base import DhcpLeaseProvider
from .client import OPNsenseClient
from .mappers import extract_rows, parse_dhcp_lease

logger = logging.getLogger("netbot.monitoring.opnsense.dhcp")

# Los endpoints de búsqueda de OPNsense paginan; se pide una página grande.
_SEARCH_PARAMS = {"current": 1, "rowCount": 9999}


class _OPNsenseLeaseProvider(DhcpLeaseProvider):
    path: str
    kea: bool = False

    def __init__(self, client: OPNsenseClient) -> None:
        self._client = client

    async def get_leases(self) -> list[DhcpLease]:
        payload: Any = await self._client.get_json(self.path, params=_SEARCH_PARAMS)
        now = datetime.now(timezone.utc)
        rows = extract_rows(payload)
        leases = [
            lease
            for row in rows
            if (lease := parse_dhcp_lease(row, now=now, kea=self.kea)) is not None
        ]
        if len(leases) != len(rows):
            logger.debug("Concesiones omitidas por datos inválidos: %d", len(rows) - len(leases))
        return leases


class DnsmasqLeaseProvider(_OPNsenseLeaseProvider):
    path = "/api/dnsmasq/leases/search"


class KeaLeaseProvider(_OPNsenseLeaseProvider):
    path = "/api/kea/leases4/search"
    kea = True
