"""Inventario persistido: colector periódico y lecturas para la API.

El colector atiende cada fuente por separado, de modo que una caída no detiene a las
demás ni al backend. Tras un fallo reintenta con espera progresiva. Una sección que no se
obtuvo conserva sus datos, que se marcan como desactualizados por antigüedad. Es una
tarea en memoria de una instancia, no una cola durable.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFound

from .alerts import AlertCondition, device_conditions, sync_alerts
from .models import (
    DeviceAvailability,
    MonitoredDevice,
    MonitoredSsid,
    MonitoredVlan,
    MonitoringAlert,
    SourceState,
)
from .providers.base import CollectionResult, InfrastructureSource
from .schemas import (
    AlertRead,
    AlertSeverity,
    CollectionIssue,
    DeviceDetail,
    DeviceRead,
    DeviceState,
    DeviceType,
    InventorySnapshot,
    InventorySummary,
    IssueKind,
    MonitoringStatus,
    Page,
    SourceHealth,
    SsidRead,
    VlanRead,
)

logger = logging.getLogger("netbot.monitoring.inventory")

_MAX_OBSERVATION_GAPS = 3  # más allá de esto hubo un silencio, no una observación continua
_AVAILABILITY_RETENTION = timedelta(days=35)
_STATE_ORDER = {"offline": 0, "degraded": 1, "unknown": 2, "maintenance": 3, "online": 4}


def configured_sources(settings: Settings) -> list[str]:
    """Fuentes vigentes: datos de una configuración anterior no se mezclan con los actuales."""
    return [settings.monitoring_provider, *(["unifi"] if settings.unifi_enabled else [])]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_stale(seen_at: datetime | None, now: datetime, settings: Settings) -> bool:
    return seen_at is None or (now - seen_at).total_seconds() > settings.monitoring_inventory_max_age_seconds


def _clip(value: str | None, size: int) -> str | None:
    return value[:size] if value else value


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #


def _sync(db: Session, model: Any, source: str, items: list[Any], apply: Callable[[Any, Any], None],
          now: datetime) -> list[Any]:
    existing = {row.external_id: row for row in db.scalars(select(model).where(model.source == source))}
    seen = set()
    for item in items:
        seen.add(item.external_id)
        row = existing.get(item.external_id)
        if row is None:
            row = existing[item.external_id] = model(source=source, external_id=item.external_id)
            db.add(row)
        apply(row, item)
        row.last_seen_at = now
        row.missing_since = None
    for identity, row in existing.items():
        if identity not in seen and row.missing_since is None:
            row.missing_since = now
    return list(existing.values())


def _record_availability(db: Session, previous: dict[str, datetime], rows: list[MonitoredDevice],
                         now: datetime, interval: float) -> None:
    bucket = now.replace(minute=0, second=0, microsecond=0)
    for row in rows:
        last = previous.get(row.external_id)
        if last is None or row.missing_since is not None or row.state not in {"online", "degraded", "offline"}:
            continue
        seconds = (now - last).total_seconds()
        if not 0 < seconds <= interval * _MAX_OBSERVATION_GAPS:
            continue
        entry = db.scalar(select(DeviceAvailability).where(
            DeviceAvailability.device_id == row.id, DeviceAvailability.bucket_start == bucket))
        if entry is None:
            entry = DeviceAvailability(device_id=row.id, bucket_start=bucket, online_seconds=0.0, observed_seconds=0.0)
            db.add(entry)
        entry.observed_seconds += seconds
        if row.state == "online":
            entry.online_seconds += seconds


def persist_snapshot(db: Session, source: str, snapshot: InventorySnapshot, now: datetime, interval: float) -> None:
    if snapshot.devices is not None:
        previous = dict(db.execute(select(MonitoredDevice.external_id, MonitoredDevice.last_seen_at)
                                   .where(MonitoredDevice.source == source)).all())

        def apply_device(row: MonitoredDevice, item: Any) -> None:
            row.name = _clip(item.name, 255)
            row.device_type = item.device_type.value
            row.model = _clip(item.model, 120)
            row.mac_address = item.mac_address
            row.ip_address = _clip(item.ip_address, 64)
            row.state = item.state.value
            if item.state == DeviceState.ONLINE:
                row.last_online_at = now

        rows = _sync(db, MonitoredDevice, source, snapshot.devices, apply_device, now)
        db.flush()
        _record_availability(db, previous, rows, now, interval)
    if snapshot.vlans is not None:
        def apply_vlan(row: MonitoredVlan, item: Any) -> None:
            row.name, row.tag, row.enabled = _clip(item.name, 255), item.tag, item.enabled

        _sync(db, MonitoredVlan, source, snapshot.vlans, apply_vlan, now)
    if snapshot.ssids is not None:
        def apply_ssid(row: MonitoredSsid, item: Any) -> None:
            row.name, row.enabled = _clip(item.name, 255), item.enabled
            row.security, row.vlan_tag = _clip(item.security, 40), item.vlan_tag

        _sync(db, MonitoredSsid, source, snapshot.ssids, apply_ssid, now)
    db.flush()


class InventoryCollector:
    def __init__(self, sources: Sequence[InfrastructureSource], session_factory: Callable[[], Session],
                 settings: Settings, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._sources = list(sources)
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._next_attempt: dict[str, datetime] = {}

    def retry_delay(self, failures: int) -> float:
        interval = self._settings.monitoring_inventory_interval_seconds
        return min(interval * 2 ** min(failures - 1, 16), self._settings.monitoring_retry_max_seconds)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_cycle()
            except Exception:  # el backend sigue aunque falle un ciclo completo
                logger.exception("Falló un ciclo de recolección de inventario")
            await asyncio.sleep(1.0)

    async def run_cycle(self) -> None:
        now = self._clock()
        due = [s for s in self._sources if self._next_attempt.get(s.source, now) <= now]
        await asyncio.gather(*(self._run_source(source) for source in due))

    async def _run_source(self, source: InfrastructureSource) -> None:
        try:
            result = await source.collect_inventory()
        except Exception:
            logger.exception("El proveedor %s falló de forma inesperada", source.source)
            result = CollectionResult(data=None, issues=[CollectionIssue(
                component="inventory", kind=IssueKind.UNKNOWN, message="Error interno en la recolección.")])
        now = self._clock()
        with self._session_factory() as db:
            state = db.get(SourceState, source.source)
            if state is None:
                state = SourceState(source=source.source, consecutive_failures=0)
                db.add(state)
            state.last_attempt_at = now
            if result.data is None:
                self._record_failure(db, state, result, now)
            else:
                self._record_success(db, state, result, now)
            db.commit()
            self._next_attempt[source.source] = state.next_attempt_at

    def _record_failure(self, db: Session, state: SourceState, result: CollectionResult, now: datetime) -> None:
        issue = next((i for i in result.issues if not i.optional), None)
        state.status = MonitoringStatus.UNAVAILABLE.value
        state.consecutive_failures += 1
        state.last_error_kind = issue.kind.value if issue else IssueKind.UNKNOWN.value
        state.last_error_message = (issue.message if issue else "La fuente no entregó datos.")[:255]
        delay = self.retry_delay(state.consecutive_failures)
        state.next_attempt_at = now + timedelta(seconds=delay)
        unconfigured = state.last_error_kind == IssueKind.NOT_CONFIGURED.value
        logger.log(logging.DEBUG if unconfigured else logging.WARNING,
                   "Fuente %s no disponible (%s, intento %d); reintento en %.0f s", state.source,
                   state.last_error_kind, state.consecutive_failures, delay)
        conditions = []
        # Una integración sin credenciales nunca estuvo conectada: no hay conexión perdida.
        if not unconfigured and state.consecutive_failures >= self._settings.monitoring_source_failure_threshold:
            conditions.append(AlertCondition(f"source:{state.source}:unavailable", "source", AlertSeverity.CRITICAL,
                                             f"Se perdió la conexión con {state.source}: {state.last_error_message}"))
        sync_alerts(db, source=state.source, categories={"source"}, conditions=conditions, now=now)

    def _record_success(self, db: Session, state: SourceState, result: CollectionResult, now: datetime) -> None:
        snapshot = result.data
        interval = self._settings.monitoring_inventory_interval_seconds
        persist_snapshot(db, state.source, snapshot, now, interval)
        db.query(DeviceAvailability).filter(DeviceAvailability.bucket_start < now - _AVAILABILITY_RETENTION).delete()
        problems = [issue for issue in result.issues if not issue.optional]
        state.status = (MonitoringStatus.DEGRADED if problems else MonitoringStatus.OK).value
        state.version = _clip(snapshot.version, 120) or state.version
        state.last_success_at = now
        state.consecutive_failures = 0
        state.next_attempt_at = now + timedelta(seconds=interval)
        state.last_error_kind = problems[0].kind.value if problems else None
        state.last_error_message = problems[0].message[:255] if problems else None
        categories = {"source"}
        conditions: list[AlertCondition] = []
        if snapshot.devices is not None:
            categories.add("device")
            conditions += device_conditions(db, state.source)
        if problems:
            parts = ", ".join(sorted({issue.component for issue in problems}))
            conditions.append(AlertCondition(f"source:{state.source}:degraded", "source", AlertSeverity.WARNING,
                                             f"Datos parciales de {state.source}: falló {parts}."))
        sync_alerts(db, source=state.source, categories=categories, conditions=conditions, now=now)


# --------------------------------------------------------------------------- #
# Lecturas
# --------------------------------------------------------------------------- #


def _page(db: Session, stmt: Any, limit: int, offset: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return list(db.scalars(stmt.limit(limit).offset(offset))), total


def _fresh(schema: Any, row: Any, now: datetime, settings: Settings) -> Any:
    return schema.model_validate(row).model_copy(update={"stale": _is_stale(row.last_seen_at, now, settings)})


def list_devices(db: Session, settings: Settings, *, state: DeviceState | None = None,
                 device_type: DeviceType | None = None, limit: int = 50, offset: int = 0) -> Page[DeviceRead]:
    stmt = select(MonitoredDevice).where(MonitoredDevice.source.in_(configured_sources(settings))) \
        .order_by(case(_STATE_ORDER, value=MonitoredDevice.state, else_=5), MonitoredDevice.name, MonitoredDevice.id)
    if state:
        stmt = stmt.where(MonitoredDevice.state == state.value)
    if device_type:
        stmt = stmt.where(MonitoredDevice.device_type == device_type.value)
    rows, total = _page(db, stmt, limit, offset)
    now = _utcnow()
    return Page(items=[_fresh(DeviceRead, row, now, settings) for row in rows], total=total, limit=limit, offset=offset)


def get_device(db: Session, settings: Settings, device_id: int) -> DeviceDetail:
    row = db.get(MonitoredDevice, device_id)
    if row is None or row.source not in configured_sources(settings):
        raise NotFound("Dispositivo no encontrado.")
    alerts = db.scalars(select(MonitoringAlert).where(
        MonitoringAlert.device_id == row.id, MonitoringAlert.resolved_at.is_(None))
        .order_by(MonitoringAlert.severity_rank, MonitoringAlert.detected_at.desc()))
    base = _fresh(DeviceRead, row, _utcnow(), settings).model_dump()
    return DeviceDetail(**base, alerts=[AlertRead.model_validate(alert) for alert in alerts])


def list_vlans(db: Session, settings: Settings, *, limit: int = 100, offset: int = 0) -> Page[VlanRead]:
    stmt = select(MonitoredVlan).where(MonitoredVlan.source.in_(configured_sources(settings)),
                                       MonitoredVlan.missing_since.is_(None)) \
        .order_by(MonitoredVlan.tag, MonitoredVlan.source)
    rows, total = _page(db, stmt, limit, offset)
    now = _utcnow()
    return Page(items=[_fresh(VlanRead, row, now, settings) for row in rows], total=total, limit=limit, offset=offset)


def list_ssids(db: Session, settings: Settings, *, limit: int = 100, offset: int = 0) -> Page[SsidRead]:
    stmt = select(MonitoredSsid).where(MonitoredSsid.source.in_(configured_sources(settings)),
                                       MonitoredSsid.missing_since.is_(None)) \
        .order_by(MonitoredSsid.name, MonitoredSsid.id)
    rows, total = _page(db, stmt, limit, offset)
    now = _utcnow()
    return Page(items=[_fresh(SsidRead, row, now, settings) for row in rows], total=total, limit=limit, offset=offset)


def list_alerts(db: Session, settings: Settings, *, active: bool = True, limit: int = 50,
                offset: int = 0) -> Page[AlertRead]:
    """Mayor severidad primero."""
    stmt = select(MonitoringAlert).where(
        MonitoringAlert.source.in_(configured_sources(settings)),
        MonitoringAlert.resolved_at.is_(None) if active else MonitoringAlert.resolved_at.isnot(None),
    ).order_by(MonitoringAlert.severity_rank, MonitoringAlert.detected_at.desc(), MonitoringAlert.id.desc())
    rows, total = _page(db, stmt, limit, offset)
    return Page(items=[AlertRead.model_validate(row) for row in rows], total=total, limit=limit, offset=offset)


def source_health(db: Session, settings: Settings) -> list[SourceHealth]:
    now = _utcnow()
    wanted = configured_sources(settings)
    rows = {row.source: row for row in db.scalars(select(SourceState).where(SourceState.source.in_(wanted)))}
    health = []
    for name in wanted:
        row = rows.get(name)
        if row is None:  # sin ciclo todavía: se informa, no se oculta
            health.append(SourceHealth(source=name, status=MonitoringStatus.UNAVAILABLE, stale=True))
        else:
            health.append(SourceHealth.model_validate(row).model_copy(
                update={"stale": _is_stale(row.last_success_at, now, settings)}))
    return health


def summary(db: Session, settings: Settings) -> InventorySummary:
    now = _utcnow()
    sources = configured_sources(settings)
    states = list(db.scalars(select(MonitoredDevice.state).where(
        MonitoredDevice.source.in_(sources), MonitoredDevice.device_type == DeviceType.ACCESS_POINT.value,
        MonitoredDevice.missing_since.is_(None))))
    vlans = db.scalar(select(func.count(func.distinct(MonitoredVlan.tag))).where(
        MonitoredVlan.source.in_(sources), MonitoredVlan.missing_since.is_(None),
        or_(MonitoredVlan.enabled.is_(None), MonitoredVlan.enabled.is_(True)))) or 0
    ssids = db.scalar(select(func.count()).select_from(MonitoredSsid).where(
        MonitoredSsid.source.in_(sources), MonitoredSsid.missing_since.is_(None),
        MonitoredSsid.enabled.is_(True))) or 0
    since = now - timedelta(hours=settings.monitoring_availability_window_hours)
    online, observed = db.execute(
        select(func.sum(DeviceAvailability.online_seconds), func.sum(DeviceAvailability.observed_seconds))
        .join(MonitoredDevice, MonitoredDevice.id == DeviceAvailability.device_id)
        .where(DeviceAvailability.bucket_start >= since, MonitoredDevice.source.in_(sources))).one()
    alerts = db.scalar(select(func.count()).select_from(MonitoringAlert).where(
        MonitoringAlert.source.in_(sources), MonitoringAlert.resolved_at.is_(None))) or 0
    health = source_health(db, settings)
    updates = [s.last_success_at for s in health if s.last_success_at]
    return InventorySummary(
        access_points_total=len(states),
        access_points_online=states.count("online"),
        access_points_offline=states.count("offline"),
        vlans_active=vlans,
        ssids_active=ssids,
        availability_percent=round(online / observed * 100, 2) if observed else None,
        availability_window_hours=settings.monitoring_availability_window_hours,
        active_alerts=alerts,
        last_update_at=max(updates) if updates else None,
        stale=any(s.stale for s in health),
        sources=health,
    )
