"""Fuente real sin credenciales: no inventa datos ni impide arrancar la API.

Cada lectura responde "sin datos" e indica qué variables faltan. Nunca recurre al mock.
"""

from ..schemas import CollectionIssue, IssueKind
from .base import CollectionResult, NetworkMonitoringProvider


class UnconfiguredProvider(NetworkMonitoringProvider):
    def __init__(self, source: str, missing: list[str]) -> None:
        self.source = source
        self._message = "Falta configurar: " + ", ".join(missing)

    def _nothing(self) -> CollectionResult:
        return CollectionResult(data=None, issues=[CollectionIssue(
            component=self.source, kind=IssueKind.NOT_CONFIGURED, message=self._message)])

    async def collect_inventory(self):
        return self._nothing()

    async def get_system_metrics(self):
        return self._nothing()

    async def get_interface_metrics(self):
        return self._nothing()

    async def get_clients(self):
        return self._nothing()

    async def get_vlan_inventory(self):
        return self._nothing()

    async def get_firewall_statistics(self):
        return self._nothing()

    async def get_firewall_events(self, limit: int):
        return self._nothing()
