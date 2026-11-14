"""Reinicio confirmado de equipos (HU011).

Proponer y confirmar no tocan la red. Ejecutar es exclusivo del worker: reautoriza, toma
una exclusión durable por equipo, abre una ventana de mantenimiento, envía un único
reinicio y espera el retorno. Un reinicio no se deshace: si el equipo no vuelve se abre
un incidente; nunca se reintenta a ciegas.
"""
import asyncio
import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.access import require_user_permission
from app.auth.audit import queue_denial, record_event
from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.auth.service import execution_actor
from app.core.config import Settings
from app.core.errors import AccessDenied, ApplicationError, Conflict, NotFound, ServiceUnavailable
from app.monitoring import maintenance

from .csv_service import as_utc, utc_now
from .models import DeviceRestartPlan, WifiWriteLease
from .execution import PlanBusy, exclusive_plan
from .ssid_executor import UniFiSsidWriter, WriteUncertain
from .ssid_schemas import DeviceRestartProposal, PlanRevision
from .ssid_service import authorized_scope, digest

ACTIVE = ('confirmed', 'executing', 'uncertain')
UNIFI_SOURCE = 'unifi'  # fuente del inventario de monitoreo que observa estos equipos
MAINTENANCE_GRACE_SECONDS = 60


class DeviceRestartService:
    def __init__(self, db: Session, settings: Settings, writer=None, incidents=None,
                 sleep=asyncio.sleep, monotonic=time.monotonic):
        self.db, self.settings = db, settings
        self.writer = writer or UniFiSsidWriter(settings)
        self.incidents = incidents
        self._sleep, self._monotonic = sleep, monotonic

    # ------------------------------------------------------------ autorización
    def _authorize(self, actor: User, scope_id: int, device_id: str, access_point: bool | None, permission):
        """Técnico: solo AP de su ámbito. Equipos críticos o no clasificados: solo administrador."""
        scope = authorized_scope(self.db, actor, scope_id, permission)
        admin = Permission.NETWORKS_MANAGE in effective_permissions(actor)
        if not admin and device_id not in scope.resources.get('ap_ids', []):
            queue_denial(actor.id, permission, reason='device_scope')
            raise NotFound('Dispositivo no autorizado en este ámbito.')
        if access_point is False and not admin:
            queue_denial(actor.id, permission, reason='critical_device')
            raise AccessDenied('El reinicio de gateway, firewall u otros equipos críticos está reservado al Administrador de Red.')
        return scope

    def _owned(self, actor: User, plan_id: str, permission=Permission.CHANGES_REQUEST) -> DeviceRestartPlan:
        require_user_permission(self.db, actor, permission)
        plan = self.db.scalar(select(DeviceRestartPlan).where(
            DeviceRestartPlan.id == plan_id, DeviceRestartPlan.owner_id == actor.id))
        if plan is None:
            raise NotFound('Plan de reinicio no encontrado.')
        self._authorize(actor, plan.scope_id, plan.device_id, plan.access_point, permission)
        return plan

    def _busy(self, site_id: str, device_id: str, excluding: str | None = None) -> bool:
        statement = select(DeviceRestartPlan.id).where(
            DeviceRestartPlan.site_id == site_id, DeviceRestartPlan.device_id == device_id,
            DeviceRestartPlan.status.in_(ACTIVE))
        if excluding:
            statement = statement.where(DeviceRestartPlan.id != excluding)
        return self.db.scalar(statement) is not None

    # ------------------------------------------------------ propuesta y confirmación
    def check(self, actor: User, proposal: DeviceRestartProposal):
        """Para el chat: autoriza el equipo solicitado sin consultar la red ni guardar nada."""
        self._authorize(actor, proposal.scope_id, proposal.device_id, None, Permission.CHANGES_REQUEST)
        return {'proposal': proposal.model_dump(), 'status': 'awaiting_confirmation',
                'message': 'Propuesta de reinicio. El panel mostrará el impacto y pedirá confirmación; '
                           'todavía no se reinició nada.'}

    async def propose(self, actor: User, proposal: DeviceRestartProposal):
        scope = self._authorize(actor, proposal.scope_id, proposal.device_id, None, Permission.CHANGES_REQUEST)
        if self.settings.unifi_inventory_mode != 'api':
            raise Conflict('El reinicio requiere el inventario UniFi real; no se simula sobre equipos.')
        site_id = scope.site_id
        device = await self.writer.device(site_id, proposal.device_id)
        clients = await self.writer.connected_clients(site_id, proposal.device_id)
        # Reautorizar después de las esperas de red, ahora con la clasificación del equipo.
        scope = self._authorize(actor, proposal.scope_id, proposal.device_id, device['access_point'],
                                Permission.CHANGES_REQUEST)
        if scope.site_id != site_id:
            raise Conflict('El ámbito cambió durante la consulta. Intenta nuevamente.')
        if self._busy(site_id, proposal.device_id):
            raise Conflict('Ya existe un reinicio aprobado o en curso para este dispositivo.')
        now = utc_now()
        plan = DeviceRestartPlan(
            id=str(uuid4()), owner_id=actor.id, scope_id=proposal.scope_id, site_id=site_id,
            device_id=proposal.device_id, device_name=device['name'], access_point=device['access_point'],
            connected_clients=clients, purpose=proposal.purpose, status='preview',
            revision=digest([proposal.model_dump(), site_id, device['name'], device['access_point'], clients]),
            execution_results=[], created_at=now,
            expires_at=now + timedelta(seconds=self.settings.csv_preview_ttl_seconds))
        self.db.add(plan)
        record_event(self.db, 'device.restart.requested', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan.id, 'scope_id': plan.scope_id, 'device_id': plan.device_id})
        self.db.commit()
        return self.read(plan, state=device['state'])

    def confirm(self, actor: User, plan_id: str, payload: PlanRevision):
        plan = self._owned(actor, plan_id, Permission.CHANGES_APPROVE)
        if plan.revision != payload.revision:
            raise Conflict('La revisión no coincide con el plan mostrado.')
        if plan.status == 'confirmed':
            return self.read(plan)
        if plan.status != 'preview' or as_utc(plan.expires_at) <= utc_now():
            raise Conflict('El plan ya no puede confirmarse o está vencido.')
        if self._busy(plan.site_id, plan.device_id, excluding=plan.id):
            raise Conflict('Ya existe un reinicio aprobado o en curso para este dispositivo.')
        result = self.db.execute(update(DeviceRestartPlan).where(
            DeviceRestartPlan.id == plan.id, DeviceRestartPlan.status == 'preview',
            DeviceRestartPlan.revision == payload.revision, DeviceRestartPlan.expires_at > utc_now())
            .values(status='confirmed', confirmed_at=utc_now()), execution_options={'synchronize_session': False})
        if result.rowcount != 1:
            self.db.rollback()
            raise Conflict('El plan fue modificado por otra solicitud.')
        record_event(self.db, 'device.restart.confirmed', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan.id, 'revision': payload.revision})
        self.db.commit()
        self.db.refresh(plan)
        return self.read(plan)

    def cancel(self, actor: User, plan_id: str):
        plan = self._owned(actor, plan_id)
        result = self.db.execute(update(DeviceRestartPlan).where(
            DeviceRestartPlan.id == plan.id, DeviceRestartPlan.status.in_(('preview', 'confirmed')))
            .values(status='cancelled'), execution_options={'synchronize_session': False})
        if result.rowcount != 1:
            self.db.rollback()
            raise Conflict('El reinicio ya fue tomado por el ejecutor o está finalizado.')
        record_event(self.db, 'device.restart.cancelled', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan.id})
        self.db.commit()
        self.db.refresh(plan)
        return self.read(plan)

    def get(self, actor: User, plan_id: str):
        return self.read(self._owned(actor, plan_id))

    def list(self, actor: User):
        require_user_permission(self.db, actor, Permission.CHANGES_REQUEST)
        result = []
        for plan in self.db.scalars(select(DeviceRestartPlan).where(DeviceRestartPlan.owner_id == actor.id)
                                    .order_by(DeviceRestartPlan.created_at.desc()).limit(100)):
            try:
                self._authorize(actor, plan.scope_id, plan.device_id, plan.access_point, Permission.CHANGES_REQUEST)
            except ApplicationError:
                continue
            result.append(self.read(plan))
        return result

    def read(self, plan: DeviceRestartPlan, state: str | None = None):
        status = 'expired' if plan.status == 'preview' and as_utc(plan.expires_at) <= utc_now() else plan.status
        clients = plan.connected_clients
        impact = ('No se pudo determinar cuántos clientes están conectados.' if clients is None
                  else f'{clients} cliente(s) conectados se desconectarán durante el reinicio.')
        if not plan.access_point:
            impact += ' Es un equipo crítico o no clasificado: puede interrumpir toda la red.'
        data = {'id': plan.id, 'scope_id': plan.scope_id, 'device_id': plan.device_id, 'device_name': plan.device_name,
                'access_point': plan.access_point, 'connected_clients': clients, 'impact': impact,
                'purpose': plan.purpose, 'status': status, 'revision': plan.revision,
                'expires_at': as_utc(plan.expires_at).isoformat(),
                'confirmed_at': as_utc(plan.confirmed_at).isoformat() if plan.confirmed_at else None,
                'requires_confirmation': status == 'preview',
                'needs_reconciliation': status in ('executing', 'uncertain'),
                'execution_results': plan.execution_results or []}
        if state is not None:
            data['device_state'] = state
        return data

    # ------------------------------------------------------------------ ejecución
    @exclusive_plan('restart')
    async def execute(self, plan_id: str):
        """Worker interno. No se expone por HTTP ni al LLM."""
        plan = self.db.get(DeviceRestartPlan, plan_id, populate_existing=True)
        if plan is None:
            raise NotFound('Plan de reinicio no encontrado.')
        actor = execution_actor(self.db, plan.owner_id)
        site_id, device_id, access_point = plan.site_id, plan.device_id, plan.access_point

        def reauthorize():
            scope = self._authorize(actor, plan.scope_id, device_id, access_point, Permission.CHANGES_EXECUTE)
            if scope.site_id != site_id:
                raise Conflict('El sitio del ámbito cambió.')

        reauthorize()
        if plan.status != 'confirmed' or as_utc(plan.expires_at) <= utc_now():
            raise Conflict('El reinicio no está confirmado o la aprobación venció.')
        if (not self.settings.unifi_write_enabled or self.settings.unifi_api_contract != '10.6.106'
                or self.settings.unifi_inventory_mode != 'api'):
            raise ServiceUnavailable('Ejecución de reinicios deshabilitada o contrato no autorizado.')
        before = await self.writer.device(site_id, device_id)
        reauthorize()

        resource_key = digest([site_id, 'device', device_id])
        try:
            self.db.add(WifiWriteLease(resource_key=resource_key, restart_plan_id=plan.id))
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise PlanBusy('El dispositivo tiene un reinicio en curso o pendiente de conciliación.') from None
        claim = self.db.execute(update(DeviceRestartPlan).where(
            DeviceRestartPlan.id == plan.id, DeviceRestartPlan.status == 'confirmed',
            DeviceRestartPlan.expires_at > utc_now()).values(status='executing', execution_started_at=utc_now(),
                                                          uptime_before=before.get('uptime_seconds')),
            execution_options={'synchronize_session': False})
        if claim.rowcount != 1:
            self.db.rollback()
            raise Conflict('El reinicio ya fue tomado por otro ejecutor.')
        timeout = self.settings.device_restart_timeout_seconds
        now = utc_now()
        maintenance.open_window(self.db, source=UNIFI_SOURCE, external_id=device_id, now=now,
                                until=now + timedelta(seconds=timeout + MAINTENANCE_GRACE_SECONDS),
                                reason='Reinicio confirmado desde Netbot')
        record_event(self.db, 'device.restart.started', actor_id=actor.id, target_id=actor.id, source='worker',
                     details={'plan_id': plan.id, 'device_id': device_id})
        self.db.commit()
        self.db.refresh(plan)

        try:
            await self.writer.restart(site_id, device_id, authorize=reauthorize)
        except WriteUncertain:
            return self._finish(plan_id, actor.id, resource_key, 'uncertain', 'restart_unconfirmed')
        except Exception:
            # Rechazo anterior al envío: el equipo no recibió la orden.
            self.db.rollback()
            return self._finish(plan_id, actor.id, resource_key, 'failed', 'not_sent')
        outcome, detail = await self._await_return(site_id, device_id, before.get('uptime_seconds'), timeout)
        return self._finish(plan_id, actor.id, resource_key, outcome, detail)

    async def _await_return(self, site_id, device_id, uptime_before, timeout):
        """Espera acotada. «En línea» solo acredita el reinicio si se observó la caída o un uptime menor."""
        deadline = self._monotonic() + timeout
        seen_down, state = False, None
        while self._monotonic() < deadline:
            await self._sleep(self.settings.device_restart_poll_seconds)
            try:
                device = await self.writer.device(site_id, device_id)
            except Exception:
                state = None  # un error de consulta no demuestra que el equipo cayó
                continue
            state, uptime = device['state'], device.get('uptime_seconds')
            if state == 'OFFLINE':
                seen_down = True
            elif state == 'ONLINE' and (seen_down or (
                    uptime is not None and uptime_before is not None and uptime < uptime_before)):
                return 'completed', 'returned_online'
        if state == 'ONLINE':
            # Sigue en línea pero no se pudo acreditar el reinicio: se informa tal cual.
            return 'uncertain', 'online_restart_unconfirmed'
        return 'failed', 'did_not_return'

    def _finish(self, plan_id, actor_id, resource_key, outcome, detail):
        plan = self.db.get(DeviceRestartPlan, plan_id)
        plan.status = outcome
        plan.execution_results = [{'status': detail, 'device_id': plan.device_id}]
        maintenance.close_window(self.db, source=UNIFI_SOURCE, external_id=plan.device_id, now=utc_now())
        if outcome != 'uncertain':
            self.db.execute(delete(WifiWriteLease).where(
                WifiWriteLease.resource_key == resource_key, WifiWriteLease.restart_plan_id == plan.id))
        record_event(self.db, f'device.restart.{outcome}', actor_id=actor_id, target_id=actor_id, source='worker',
                     outcome={'completed': 'success', 'uncertain': 'uncertain'}.get(outcome, 'failure'),
                     details={'plan_id': plan.id, 'device_id': plan.device_id, 'result': detail})
        if self.incidents is not None and detail in ('did_not_return', 'restart_unconfirmed', 'online_restart_unconfirmed'):
            message = (f'{plan.device_name} no volvió en línea tras el reinicio solicitado.' if detail == 'did_not_return'
                       else f'El reinicio de {plan.device_name} quedó en estado incierto. Requiere conciliación.')
            self.incidents(self.db, 'restart_failed', f'change:restart:{plan.id}', message)
        self.db.commit()
        return self.read(plan)

    @exclusive_plan('restart')
    async def reconcile(self, plan_id: str):
        """Resuelve un reinicio detenido consultando el equipo. No envía órdenes."""
        plan = self.db.get(DeviceRestartPlan, plan_id, populate_existing=True)
        if plan is None:
            raise NotFound('Plan de reinicio no encontrado.')
        if plan.status not in ('executing', 'uncertain'):
            raise Conflict('El reinicio no requiere conciliación.')
        device = await self.writer.device(plan.site_id, plan.device_id)
        if device['state'] != 'ONLINE':
            raise Conflict('El dispositivo todavía no está en línea. Revísalo antes de conciliar.')
        resource_key = digest([plan.site_id, 'device', plan.device_id])
        plan = self.db.get(DeviceRestartPlan, plan_id)
        uptime = device.get('uptime_seconds')
        verified = uptime is not None and plan.uptime_before is not None and uptime < plan.uptime_before
        plan.status = 'completed' if verified else 'unverified'
        result = 'reconciled_restart_verified' if verified else 'reconciled_online_restart_unconfirmed'
        plan.execution_results = [{'status': result, 'device_id': plan.device_id}]
        maintenance.close_window(self.db, source=UNIFI_SOURCE, external_id=plan.device_id, now=utc_now())
        self.db.execute(delete(WifiWriteLease).where(
            WifiWriteLease.resource_key == resource_key, WifiWriteLease.restart_plan_id == plan.id))
        record_event(self.db, 'device.restart.reconciled', actor_id=plan.owner_id, target_id=plan.owner_id,
                     source='worker', outcome='success' if verified else 'uncertain',
                     details={'plan_id': plan.id, 'device_id': plan.device_id, 'result': result})
        self.db.commit()
        return self.read(plan)
