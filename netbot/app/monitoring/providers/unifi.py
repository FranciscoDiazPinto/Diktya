"""Lecturas UniFi Integration API; implementación propia del contrato 10.6.106.

Inventario paginado y estadísticas opcionales, sin credenciales en DTO o logs.
No usa login clásico, fallback cloud ni operaciones de escritura.
"""
import asyncio
import ssl
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import Settings
from .base import CollectionResult
from ..schemas import AccessPointMetrics, AccessPointState, CollectionIssue, IssueKind


class _Overview(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=256)
    features: list[str]
    state: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=160)
    firmwareVersion: str | None = Field(default=None, max_length=160)


class _Statistics(BaseModel):
    uptimeSec: int | None = Field(default=None, ge=0, strict=True)
    lastHeartbeatAt: datetime | None = None
    cpuUtilizationPct: float | None = Field(default=None, ge=0, le=100, strict=True)
    memoryUtilizationPct: float | None = Field(default=None, ge=0, le=100, strict=True)

    @field_validator('lastHeartbeatAt')
    @classmethod
    def aware_timestamp(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Heartbeat sin zona horaria')
        return value


class _ReadFailure(Exception):
    def __init__(self, kind):
        self.kind = kind


_MESSAGES = {
    IssueKind.CONFIGURATION: 'Configura el monitoreo UniFi, sitio, API key y TLS/CA en el servidor.',
    IssueKind.AUTHENTICATION: 'UniFi rechazó la API key (401).',
    IssueKind.PERMISSION: 'La API key UniFi no permite consultar este recurso (403).',
    IssueKind.NOT_SUPPORTED: 'La ruta UniFi no existe o no está soportada (404).',
    IssueKind.RATE_LIMITED: 'UniFi limitó las consultas; se reintentará en el siguiente ciclo.',
    IssueKind.TIMEOUT: 'Se agotó el tiempo de lectura de UniFi.',
    IssueKind.TLS: 'No se pudo verificar el certificado de UniFi; revisa la CA configurada.',
    IssueKind.CONNECTION: 'No se pudo conectar con UniFi.',
    IssueKind.SERVER_ERROR: 'UniFi no pudo completar la consulta.',
    IssueKind.INVALID_RESPONSE: 'UniFi devolvió un inventario o telemetría no conforme al contrato.',
}


def _issue(kind, *, component='unifi', optional=False):
    return CollectionIssue(component=component, kind=kind, message=_MESSAGES[kind], optional=optional)


def _state(value):
    if value == 'ONLINE':
        return AccessPointState.ONLINE
    if value == 'OFFLINE':
        return AccessPointState.OFFLINE
    if value in {'PENDING_ADOPTION','UPDATING','GETTING_READY','ADOPTING','DELETING'}:
        return AccessPointState.TRANSITIONING
    # ISOLATED/CONNECTION_INTERRUPTED no se convierten en una caída física confirmada.
    return AccessPointState.UNKNOWN


class UniFiAccessPointProvider:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport
        self.source = 'mock' if settings.unifi_monitoring_mode == 'mock' else 'unifi'

    async def aclose(self):
        pass  # El cliente y las tareas viven solo durante una recolección.

    async def _json(self, client, path, **kwargs):
        try:
            response = await client.get(path, **kwargs)
            if response.status_code != 200:
                kind = {401:IssueKind.AUTHENTICATION,403:IssueKind.PERMISSION,
                        404:IssueKind.NOT_SUPPORTED,429:IssueKind.RATE_LIMITED}.get(response.status_code,
                        IssueKind.SERVER_ERROR if response.status_code >= 500 else IssueKind.INVALID_RESPONSE)
                raise _ReadFailure(kind)
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except httpx.TimeoutException:
            raise _ReadFailure(IssueKind.TIMEOUT) from None
        except httpx.HTTPError as exc:
            tls = isinstance(exc.__cause__, ssl.SSLError) or 'certificate' in str(exc).lower()
            raise _ReadFailure(IssueKind.TLS if tls else IssueKind.CONNECTION) from None
        except (ValueError, TypeError):
            raise _ReadFailure(IssueKind.INVALID_RESPONSE) from None

    async def _devices(self, client, site):
        items, seen, expected = [], set(), None
        for _ in range(50):
            page = await self._json(client, f'sites/{site}/devices', params={'offset':len(items),'limit':200})
            rows, total = page.get('data'), page.get('totalCount')
            if not isinstance(rows,list) or type(total) is not int or total < 0:
                raise _ReadFailure(IssueKind.INVALID_RESPONSE)
            if expected is not None and total != expected:
                raise _ReadFailure(IssueKind.INVALID_RESPONSE)
            if page.get('offset',len(items)) != len(items) or page.get('count',len(rows)) != len(rows):
                raise _ReadFailure(IssueKind.INVALID_RESPONSE)
            expected = total
            for row in rows:
                try:
                    item = _Overview.model_validate(row)
                except ValidationError:
                    raise _ReadFailure(IssueKind.INVALID_RESPONSE) from None
                if item.id in seen:
                    raise _ReadFailure(IssueKind.INVALID_RESPONSE)
                seen.add(item.id);items.append(item)
            if len(items) > total or (not rows and len(items) < total):
                raise _ReadFailure(IssueKind.INVALID_RESPONSE)
            if len(items) == total:
                return [item for item in items if 'accessPoint' in item.features]
        raise _ReadFailure(IssueKind.INVALID_RESPONSE)

    async def _statistics(self, client, site, ap_id, semaphore):
        async with semaphore:
            try:
                raw = await self._json(client, f'sites/{site}/devices/{quote(ap_id,safe="")}/statistics/latest')
                stats = _Statistics.model_validate(raw)
                # Un objeto de otro contrato no es una lectura vacía válida.
                if not set(raw) & {'uptimeSec','lastHeartbeatAt','cpuUtilizationPct','memoryUtilizationPct','interfaces'}:
                    raise ValueError()
                return stats, None
            except _ReadFailure as exc:
                return None, _issue(exc.kind,component='unifi.telemetry',optional=True)
            except (ValidationError, ValueError):
                return None, _issue(IssueKind.INVALID_RESPONSE,component='unifi.telemetry',optional=True)

    async def collect(self):
        s = self.settings
        if s.unifi_monitoring_mode == 'mock':
            if s.monitoring_mock_scenario == 'outage':
                return CollectionResult(None,[_issue(IssueKind.CONNECTION)])
            site = s.unifi_monitoring_site_id or 'demo-site'
            aps = [AccessPointMetrics(id=f'demo-ap-{i}',site_id=site,name=f'AP demostración {i}',model='Demo',
                state=AccessPointState.OFFLINE if i==3 and s.monitoring_mock_scenario=='degraded' else AccessPointState.ONLINE,
                controller_state='OFFLINE' if i==3 and s.monitoring_mock_scenario=='degraded' else 'ONLINE',
                telemetry_available=True,uptime_seconds=3600*i,
                last_heartbeat_at=datetime.now(timezone.utc)-timedelta(seconds=5)) for i in range(1,4)]
            return CollectionResult(aps)
        try:
            base = urlsplit(s.unifi_api_base_url or '')
        except ValueError:
            return CollectionResult(None,[_issue(IssueKind.CONFIGURATION)])
        if (s.unifi_monitoring_mode!='api' or not s.unifi_monitoring_site_id or not s.unifi_api_key
                or not s.unifi_api_key.get_secret_value().strip() or base.scheme!='https' or not base.hostname
                or base.username or base.password or base.query or base.fragment):
            return CollectionResult(None,[_issue(IssueKind.CONFIGURATION)])
        try:
            verify = ssl.create_default_context(cafile=s.unifi_ca_bundle) if s.unifi_ca_bundle else True
        except (OSError,ssl.SSLError):
            return CollectionResult(None,[_issue(IssueKind.TLS)])
        try:
            async with httpx.AsyncClient(base_url=s.unifi_api_base_url.rstrip('/')+'/',
                headers={'X-API-Key':s.unifi_api_key.get_secret_value(),'Accept':'application/json'},
                verify=verify,timeout=s.unifi_timeout_seconds,follow_redirects=False,transport=self.transport) as client:
                site = quote(s.unifi_monitoring_site_id,safe='')
                async with asyncio.timeout(30):
                    info = await self._json(client,'info')
                    if not isinstance(info.get('applicationVersion'),str) or not info['applicationVersion']:
                        raise _ReadFailure(IssueKind.INVALID_RESPONSE)
                    devices = await self._devices(client,site)
                if len(devices)>s.unifi_monitoring_max_aps:
                    return CollectionResult(None,[CollectionIssue(component='unifi.capacity',kind=IssueKind.INVALID_RESPONSE,
                        message='El inventario supera el límite de AP configurado; no se presenta una lista truncada.')])
                aps = [AccessPointMetrics(id=d.id,site_id=s.unifi_monitoring_site_id,name=d.name,model=d.model,
                    firmware_version=d.firmwareVersion,state=_state(d.state),controller_state=d.state) for d in devices]
                if not aps:
                    return CollectionResult([])
                semaphore = asyncio.Semaphore(5)
                tasks = [asyncio.create_task(self._statistics(client,site,ap.id,semaphore)) for ap in aps]
                try:
                    _, pending = await asyncio.wait(tasks,timeout=s.unifi_monitoring_statistics_budget_seconds)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending,return_exceptions=True)
                    issues = []
                    for index, task in enumerate(tasks):
                        if task.cancelled():
                            issues.append(_issue(IssueKind.TIMEOUT,component='unifi.telemetry',optional=True));continue
                        stats, issue = task.result()
                        if issue:
                            issues.append(issue);continue
                        aps[index] = aps[index].model_copy(update={'telemetry_available':any(v is not None for v in (stats.uptimeSec,stats.lastHeartbeatAt,stats.cpuUtilizationPct,stats.memoryUtilizationPct)),'uptime_seconds':stats.uptimeSec,
                            'last_heartbeat_at':stats.lastHeartbeatAt,'cpu_percent':stats.cpuUtilizationPct,
                            'memory_percent':stats.memoryUtilizationPct})
                    unique = list({(i.kind,i.component):i for i in issues}.values())
                    return CollectionResult(aps,unique)
                finally:
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
        except _ReadFailure as exc:
            return CollectionResult(None,[_issue(exc.kind)])
        except TimeoutError:
            return CollectionResult(None,[_issue(IssueKind.TIMEOUT)])
