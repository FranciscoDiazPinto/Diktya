"""Agente de cambios: ejecuta trabajos aprobados y persistidos.

La cola es la base de datos: un reinicio del proceso no pierde aprobaciones. Cada trabajo
se toma con una transición condicional y una exclusión durable, de modo que dos workers
no lo ejecutan dos veces. Un trabajo interrumpido queda `executing`: no se reintenta; se
concilia leyendo el controlador.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.changes.queue import KINDS, confirmed_ids, interrupted_ids
from app.changes.restart_service import DeviceRestartService
from app.changes.service import expire_due
from app.changes.ssid_service import SsidPlanService
from app.core.config import Settings
from app.core.errors import ApplicationError

from .events import Event, record
from .incidents import incident_reporter

logger = logging.getLogger("netbot.agents.changes")
BATCH = 20


class ChangeWorker:
    def __init__(self, session_factory, settings: Settings, monitoring, *, writer=None, inventory=None) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._monitoring = monitoring
        self._writer, self._inventory = writer, inventory
        self._report = incident_reporter(settings, "changes")

    def _services(self, db: Session):
        plans = SsidPlanService(db, self._settings, self._monitoring, inventory=self._inventory,
                                writer=self._writer, incidents=self._report)
        restarts = DeviceRestartService(db, self._settings, writer=plans.writer, incidents=self._report)
        return plans, restarts

    def _runner(self, kind: str, plans, restarts, *, reconcile: bool = False):
        return {("ssid", False): plans.execute, ("vlan", False): plans.execute_vlan_change,
                ("restart", False): restarts.execute, ("ssid", True): plans.reconcile,
                ("vlan", True): plans.reconcile_vlan_change, ("restart", True): restarts.reconcile}[kind, reconcile]

    @staticmethod
    def _status(result) -> str:
        return result["status"] if isinstance(result, dict) else result.status

    def _trace(self, db: Session, kind: str, plan_id: str, action: str, outcome: str, detail: str | None) -> None:
        record(db, Event(agent_id="changes", event_type=f"change.{kind}.{action}", correlation_id=f"change:{kind}:{plan_id}",
                         outcome=outcome, resource_type=f"{kind}_plan", resource_id=plan_id, detail=detail))
        db.commit()

    async def _run(self, db: Session, kind: str, plan_id: str, *, reconcile: bool = False) -> str | None:
        plans, restarts = self._services(db)
        action = "reconciled" if reconcile else "executed"
        try:
            status = self._status(await self._runner(kind, plans, restarts, reconcile=reconcile)(plan_id))
        except ApplicationError as exc:
            # Rechazo previo a cualquier escritura (permiso revocado, inventario cambiado, vencido).
            db.rollback()
            self._trace(db, kind, plan_id, "rejected", "failure", exc.detail)
            logger.info("Trabajo %s %s rechazado: %s", kind, plan_id, exc.detail)
            return None
        self._trace(db, kind, plan_id, action, "success" if status == "completed" else "failure", status)
        logger.info("Trabajo %s %s: %s", kind, plan_id, status)
        return status

    async def run_cycle(self) -> None:
        """Una pasada: libera reservas vencidas, concilia interrupciones y ejecuta lo aprobado."""
        now = datetime.now(timezone.utc)
        with self._session_factory() as db:
            if expire_due(db, now):
                db.commit()
            if not self._settings.unifi_write_enabled:
                return  # sin habilitación explícita las aprobaciones esperan; nada se descarta
            # Recuperación tras una caída: solo lectura sobre la red.
            stale = now - timedelta(seconds=self._settings.device_restart_timeout_seconds * 2)
            for kind in KINDS:
                for plan_id in interrupted_ids(db, kind, stale, BATCH):
                    await self._run(db, kind, plan_id, reconcile=True)
            for kind in KINDS:
                for plan_id in confirmed_ids(db, kind, BATCH):
                    await self._run(db, kind, plan_id)

    async def reconcile(self, kind: str, plan_id: str) -> str | None:
        with self._session_factory() as db:
            return await self._run(db, kind, plan_id, reconcile=True)
