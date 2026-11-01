"""Inventario de un sitio de UniFi Network: equipos, redes y Wi-Fi broadcasts.

Cada sección se recolecta por separado. La que falla queda en `None`, de modo que la
persistencia conserve su último dato conocido.
"""

import asyncio
from typing import ClassVar

from ...exceptions import ProviderConfigurationError, ProviderInvalidResponseError
from ...schemas import InventorySnapshot
from ..base import CollectionResult, InfrastructureSource, collect, issues_of
from .client import UnifiClient
from .mappers import map_broadcast, map_device, map_network, resolve_site_id


class UnifiSiteError(ProviderConfigurationError):
    public_message = "UNIFI_SITE no identifica un sitio de la consola."


class UnifiMonitoringProvider(InfrastructureSource):
    source: ClassVar[str] = "unifi"

    def __init__(self, client: UnifiClient, *, site: str | None = None) -> None:
        self._client = client
        self._site = site
        self._site_id: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _resolve_site(self) -> str:
        if self._site_id is None:
            sites = await self._client.get_all("/sites")
            try:
                self._site_id = resolve_site_id(sites, self._site)
            except ValueError as exc:
                raise UnifiSiteError(str(exc)) from exc
        return self._site_id

    async def _section(self, path: str, build):
        rows = await self._client.get_all(path)
        try:
            return rows, build(rows)
        except ValueError as exc:
            raise ProviderInvalidResponseError(f"{path}: {exc}") from exc

    async def collect_inventory(self) -> CollectionResult[InventorySnapshot]:
        site = await collect("unifi.site", self._resolve_site())
        if not site.ok:
            return CollectionResult(data=None, issues=issues_of(site))
        base = f"/sites/{site.value}"
        info, devices, networks, broadcasts = await asyncio.gather(
            collect("unifi.info", self._client.get_json("/info"), optional=True),
            collect("unifi.devices", self._section(f"{base}/devices", lambda rows: [map_device(r) for r in rows])),
            collect("unifi.networks", self._section(
                f"{base}/networks", lambda rows: [v for v in map(map_network, rows) if v])),
            collect("unifi.wifi", self._client.get_all(f"{base}/wifi/broadcasts")),
        )
        issues = issues_of(info, devices, networks, broadcasts)
        if not (devices.ok or networks.ok or broadcasts.ok):
            self._site_id = None  # el sitio pudo cambiar: se vuelve a resolver
            return CollectionResult(data=None, issues=issues)

        network_rows = networks.value[0] if networks.ok else None
        ssids = None
        if broadcasts.ok:
            async def build_ssids():
                try:
                    return [map_broadcast(row, network_rows) for row in broadcasts.value]
                except ValueError as exc:
                    raise ProviderInvalidResponseError(str(exc)) from exc
            parsed = await collect("unifi.wifi", build_ssids())
            ssids = parsed.value
            issues.extend(issues_of(parsed))
        version = info.value.get("applicationVersion") if isinstance(info.value, dict) else None
        return CollectionResult(
            data=InventorySnapshot(
                version=version if isinstance(version, str) else None,
                devices=devices.value[1] if devices.ok else None,
                vlans=networks.value[1] if networks.ok else None,
                ssids=ssids,
            ),
            issues=issues,
        )
