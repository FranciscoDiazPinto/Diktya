"""Vista mínima de AP sobre el proveedor de inventario UniFi compartido.

No implementa otro cliente ni vuelve a interpretar payloads de UniFi. Las métricas
que el inventario no recolecta permanecen desconocidas.
"""
from ..schemas import AccessPointMetrics, AccessPointState, CollectionIssue, DeviceType, IssueKind
from .base import CollectionResult, InfrastructureSource


class AccessPointAdapter:
    source = 'unifi'

    def __init__(self, provider: InfrastructureSource | None):
        self._provider = provider

    async def aclose(self):
        if self._provider is not None:
            await self._provider.aclose()

    async def collect(self):
        if self._provider is None:
            return CollectionResult(None, [CollectionIssue(component='unifi', kind=IssueKind.NOT_CONFIGURED,
                message='La integración UniFi está deshabilitada.')])
        result = await self._provider.collect_inventory()
        if result.data is None or result.data.devices is None:
            return CollectionResult(None, result.issues)
        site = result.data.site_id
        if not site:
            return CollectionResult(None, [*result.issues, CollectionIssue(component='unifi.site',
                kind=IssueKind.INVALID_RESPONSE, message='El inventario no identifica el sitio de los AP.')])
        states = {'online': AccessPointState.ONLINE, 'offline': AccessPointState.OFFLINE,
                  'maintenance': AccessPointState.TRANSITIONING}
        return CollectionResult([
            AccessPointMetrics(id=device.external_id, site_id=site, name=device.name, model=device.model,
                state=states.get(device.state.value, AccessPointState.UNKNOWN), controller_state=device.state.value)
            for device in result.data.devices if device.device_type == DeviceType.ACCESS_POINT
        ], result.issues)
