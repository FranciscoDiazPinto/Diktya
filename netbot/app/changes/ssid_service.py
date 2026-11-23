"""Planes SSID privados compartidos por CSV y chat. Confirmar no ejecuta UniFi."""
from base64 import b64decode
from binascii import Error as Base64Error
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.auth.models import User
from app.auth.audit import queue_denial, record_event
from app.auth.permissions import Permission
from app.auth.access import require_user_permission
from app.auth.roles import effective_permissions
from app.auth.service import user_exists, execution_actor
from app.core.errors import ApplicationError, NotFound, Conflict, InvalidInput, ServiceUnavailable
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from .models import (
    WifiScope,
    WifiScopeGrant,
    SsidPlan,
    WifiWriteLease,
    SsidVlanChangePlan,
    SsidVlanBatchPlan,
)
from .ssid_schemas import (
    ScopeWrite,
    SsidProposal,
    SsidCsv,
    SsidWorkbook,
    SsidConfirm,
    SsidPlanRead,
    SsidVlanChangeProposal,
    SsidVlanBatch,
    SsidVlanChangeConfirm,
)
from .wifi_inventory import WifiInventory
from .csv_parser import parse_csv
from .event_workbook import parse_event_workbook
from .csv_service import as_utc, utc_now
from .service import clear_reservation_hold, find_reserved_vlan, hold_reservation, mark_assigned
from .execution import PlanBusy, exclusive_plan
from .fair_closure import require_open_scope


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def authorized_scope(db: Session, actor: User, scope_id: int, permission=Permission.CHANGES_REQUEST) -> WifiScope:
    """Ámbito de aprovisionamiento vigente del actor. La ausencia de concesión deniega."""
    require_user_permission(db, actor, permission)
    scope = db.get(WifiScope, scope_id)
    admin = Permission.NETWORKS_MANAGE in effective_permissions(actor)
    if scope is None or (not admin and not db.get(WifiScopeGrant, (scope_id, actor.id))):
        queue_denial(actor.id, permission, reason='wifi_scope')
        raise NotFound('Ámbito de aprovisionamiento no encontrado.')
    return scope


class SsidPlanService:
    def __init__(self, db: Session, settings: Settings, monitoring: MonitoringService, inventory=None, writer=None,
                 incidents=None):
        self.db, self.settings, self.monitoring = db, settings, monitoring
        self.inventory = inventory or WifiInventory(settings)
        from .ssid_executor import UniFiSsidWriter
        self.writer = writer or UniFiSsidWriter(settings)
        # Puerto inyectado por la composición (agentes): (db, tipo, clave, mensaje) -> None.
        self.incidents = incidents

    def _incident(self, incident_type: str, key: str, message: str) -> None:
        """Escala un fallo de verificación o rollback. Sin puerto, queda solo la auditoría."""
        if self.incidents is not None:
            self.incidents(self.db, incident_type, key, message)

    def scope(self, actor: User, scope_id: int, permission=Permission.CHANGES_REQUEST):
        return authorized_scope(self.db, actor, scope_id, permission)

    async def scope_ssids(self, actor, scope_id):
        """SSID existentes del sitio del ámbito: solo identificador y nombre."""
        _, existing, _ = await self.options(actor, scope_id)
        return [{'id': b['id'], 'ssid': b['ssid']} for b in existing]

    def scopes(self, actor):
        require_user_permission(self.db, actor, Permission.CHANGES_REQUEST)
        statement = select(WifiScope).order_by(WifiScope.id)
        if Permission.NETWORKS_MANAGE not in effective_permissions(actor):
            statement = statement.join(WifiScopeGrant).where(WifiScopeGrant.user_id == actor.id)
        return [{'id':s.id,'name':s.name,'site_id':s.site_id} for s in self.db.scalars(statement)]

    def save_scope(self, actor, payload: ScopeWrite, scope_id=None):
        require_user_permission(self.db, actor, Permission.NETWORKS_MANAGE)
        if any(not user_exists(self.db, i) for i in payload.user_ids):
            raise InvalidInput('Uno de los usuarios no existe.')
        scope = self.db.get(WifiScope, scope_id) if scope_id else WifiScope()
        if scope is None: raise NotFound('Ámbito no encontrado.')
        scope.name, scope.site_id = payload.name, payload.site_id
        scope.resources = payload.model_dump(exclude={'name','site_id','user_ids'})
        self.db.add(scope); self.db.flush()
        self.db.execute(delete(WifiScopeGrant).where(WifiScopeGrant.scope_id == scope.id))
        self.db.add_all([WifiScopeGrant(scope_id=scope.id, user_id=i) for i in sorted(set(payload.user_ids))])
        record_event(self.db, 'wifi.scope.saved', actor_id=actor.id,
                     details={'scope_id': scope.id, 'site_id': scope.site_id, 'user_ids': sorted(set(payload.user_ids))})
        self.db.commit()
        return {'id':scope.id, **payload.model_dump()}

    async def options(self, actor, scope_id):
        scope = self.scope(actor, scope_id)
        resources = scope.resources
        site_id = scope.site_id
        if self.settings.monitoring_provider != 'mock' and (not self.settings.monitoring_site_id
                or resources.get('monitoring_site_id') != self.settings.monitoring_site_id):
            raise Conflict('El ámbito no coincide con el sitio OPNsense configurado.')
        remote = await self.inventory.read(site_id)
        response = await self.monitoring.get_vlan_inventory()
        scope = self.scope(actor, scope_id)  # revocación durante esperas
        if scope.resources != resources or scope.site_id != site_id:
            raise Conflict('Cambió el ámbito. Vuelve a consultar.')
        if (response.data is None or response.status.value != 'ok' or response.stale
                or response.source != self.settings.monitoring_provider
                or not -5 <= (utc_now()-as_utc(response.collected_at)).total_seconds() <= self.settings.csv_inventory_max_age_seconds):
            raise ServiceUnavailable('El inventario VLAN no está disponible o vigente.')
        vlan_keys={(v.parent_interface,v.tag) for v in response.data}
        remote_networks={n['id']:n for n in remote['networks']}
        bindings=[n for n in resources['networks'] if n['id'] in remote_networks
                  and remote_networks[n['id']]['tag']==n['tag'] and (n['parent_interface'],n['tag']) in vlan_keys]
        safe={'scope_id':scope.id,'name':scope.name,'site_id':scope.site_id,'event_name':resources['event_name'],'source':remote['source'],
              'application_version':remote.get('application_version'),
              'simulated':remote['simulated'] or response.source=='mock',
              'aps':[a for a in remote['aps'] if a['id'] in resources['ap_ids']],
              'networks':bindings,'security_profiles':resources['security_profiles']}
        profile_revision = digest(self.settings.ssid_security_profiles_json.get_secret_value()) if self.settings.ssid_security_profiles_json else None
        fingerprint=digest([safe,resources,remote['ssids'],self.settings.unifi_api_base_url,self.settings.monitoring_site_id,profile_revision])
        return {**safe, 'accepts_changes': scope.accepts_changes}, remote['ssids'], fingerprint

    @staticmethod
    def _validate_broadcast_aps(ap_ids, options):
        available = {ap['id']: ap for ap in options['aps']}
        if not set(ap_ids) <= available.keys():
            raise Conflict('Selecciona únicamente AP autorizados y presentes en el inventario.')
        if any(available[ap_id].get('state') != 'ONLINE' for ap_id in ap_ids):
            raise Conflict('Los AP seleccionados deben estar en línea y con estado confirmado.')

    def validate(self, proposal: SsidProposal, options, existing):
        self._validate_broadcast_aps(proposal.ap_ids, options)
        if proposal.network_id not in {n['id'] for n in options['networks']}:
            raise Conflict('La red/VLAN no está autorizada o no coincide con el inventario existente.')
        if proposal.security_profile not in options['security_profiles']:
            raise Conflict('Perfil de seguridad no autorizado.')
        if any(b['ssid'].casefold()==proposal.ssid.casefold() for b in existing):
            raise Conflict('El SSID ya existe. No se sobrescribe mediante una creación.')

    async def _vlan_change_context(self, actor: User, proposal: SsidVlanChangeProposal, context=None):
        """Validación común de H10 contra el inventario vigente. Solo lectura."""
        options, existing, fingerprint = (context if context is not None
                                          else await self.options(actor, proposal.scope_id))

        if options["simulated"]:
            raise Conflict("H10 requiere inventarios reales para preparar cambios.")

        target_network = next(
            (n for n in options["networks"] if n["id"] == proposal.network_id),
            None,
        )
        if target_network is None:
            raise Conflict("La red solicitada no existe o no está autorizada.")

        target = next(
            (s for s in existing if s["id"] == proposal.broadcast_id),
            None,
        )
        if target is None:
            raise Conflict("El SSID solicitado no existe en el inventario.")

        scope = self.scope(actor, proposal.scope_id)
        site_id = scope.site_id
        resources = json.loads(json.dumps(scope.resources))
        current = await self.inventory.read_broadcast(site_id, proposal.broadcast_id)

        # Comprobar de nuevo permisos y ámbito después de la espera de red.
        scope = self.scope(actor, proposal.scope_id)
        if scope.site_id != site_id or scope.resources != resources:
            raise Conflict("El ámbito cambió durante la consulta. Intenta nuevamente.")
        if current["id"] != proposal.broadcast_id:
            raise Conflict("El identificador del SSID no coincide.")
        if current["ssid"] != target["ssid"]:
            raise Conflict("La información del SSID cambió durante la consulta.")
        if current["network_id"] == proposal.network_id:
            raise Conflict("El SSID ya utiliza la red solicitada.")
        fingerprint = self._vlan_target_fingerprint(fingerprint, current, options)
        return options, fingerprint, target_network, current, site_id

    def _vlan_target_fingerprint(self, fingerprint, broadcast, options):
        ap_ids = broadcast.get('ap_ids')
        if ap_ids is not None:
            self._validate_broadcast_aps(ap_ids, options)
        return digest([fingerprint, ap_ids])

    async def check_vlan_change(self, actor: User, proposal: SsidVlanChangeProposal):
        """Para el chat: valida la propuesta sin guardarla ni confirmarla."""
        _, _, target_network, current, _ = await self._vlan_change_context(actor, proposal)
        return {"proposal": proposal.model_dump(), "ssid": current["ssid"], "target_vlan": target_network["tag"],
                "status": "awaiting_confirmation",
                "message": "Propuesta de cambio de VLAN. Revísala y confírmala en el panel; todavía no se modificó nada."}

    async def preview_vlan_batch(self, actor: User, batch: SsidVlanBatch) -> dict:
        proposals = [
            (number, SsidVlanChangeProposal(scope_id=batch.scope_id, **row.model_dump()))
            for number, row in enumerate(batch.rows, 1)
        ]
        rows = await self._preview_vlan_batch_rows(actor, batch.scope_id, proposals)
        plan = self._store_vlan_batch(actor, batch.scope_id, rows)
        self.db.commit()
        return self._read_vlan_batch(plan)

    async def _preview_vlan_batch_rows(self, actor: User, scope_id: int, proposals):
        scope = self.scope(actor, scope_id)
        if not scope.accepts_changes:
            raise Conflict('El ámbito de feria ya no acepta cambios.')
        baseline = digest([scope.site_id, scope.resources])
        options, existing, fingerprint = await self.options(actor, scope_id)
        rows = []
        for number, proposal in proposals:
            try:
                plan, preview = await self._build_vlan_change(actor, proposal, (options, existing, fingerprint))
            except Conflict as error:
                rows.append({'row_number': number, 'errors': [error.detail]})
            else:
                rows.append({'row_number': number, 'proposal': proposal.model_dump(),
                             'ssid': plan.ssid, 'current_vlan': preview['current_vlan'],
                             'target_vlan': preview['target_vlan'], 'impact': preview['impact'],
                             'revision': plan.revision, 'errors': []})
        scope = self.scope(actor, scope_id)
        if not scope.accepts_changes or digest([scope.site_id, scope.resources]) != baseline:
            raise Conflict('El ámbito cambió durante la revisión del lote.')
        return rows

    def _store_vlan_batch(self, actor: User, scope_id: int, rows):
        require_open_scope(self.db, scope_id)
        plan = SsidVlanBatchPlan(
            id=str(uuid4()), owner_id=actor.id, scope_id=scope_id, status='preview',
            revision=digest([scope_id, rows]), rows=rows, selection=[],
            expires_at=utc_now() + timedelta(seconds=self.settings.csv_preview_ttl_seconds),
        )
        self.db.add(plan)
        return plan

    def _owned_vlan_batch(self, actor: User, batch_id: str, permission=Permission.CHANGES_REQUEST):
        require_user_permission(self.db, actor, permission)
        batch = self.db.get(SsidVlanBatchPlan, batch_id, populate_existing=True)
        if batch is None or batch.owner_id != actor.id:
            raise NotFound('Lote de cambios de VLAN no encontrado.')
        self.scope(actor, batch.scope_id, permission)
        return batch

    def _vlan_batch_children(self, batch_id: str):
        return list(self.db.scalars(select(SsidVlanChangePlan).where(
            SsidVlanChangePlan.batch_id == batch_id,
        ).order_by(SsidVlanChangePlan.batch_row).execution_options(populate_existing=True)))

    def _pending_vlan_batch_rows(self, children):
        pending = [child for child in children if child.status != 'completed']
        if not pending or any(child.status in {'executing', 'uncertain', 'rollback_failed'} for child in pending):
            return []
        first = pending[0]
        if first.status not in {'failed', 'rolled_back', 'expired', 'rejected', 'cancelled'}:
            if first.status != 'confirmed' or as_utc(first.expires_at) > utc_now():
                return []
        return pending

    @staticmethod
    def _vlan_batch_execution_status(batch, states, now):
        if batch.status == 'preview':
            return 'expired' if as_utc(batch.expires_at) <= now else 'preview'
        if batch.status != 'confirmed':
            return batch.status
        if states and states == {'completed'}:
            return 'completed'
        if states & {'uncertain', 'rollback_failed'}:
            return 'needs_reconciliation'
        if 'executing' in states:
            return 'executing'
        if states - {'confirmed', 'completed'} or as_utc(batch.expires_at) <= now:
            return 'stopped'
        return 'queued'

    def _read_vlan_batch(self, batch):
        children = self._vlan_batch_children(batch.id)
        return {'id': batch.id, 'scope_id': batch.scope_id, 'status': batch.status,
                'execution_status': self._vlan_batch_execution_status(
                    batch, {child.status for child in children}, utc_now(),
                ),
                'revision': batch.revision, 'rows': batch.rows, 'selection': batch.selection,
                'expires_at': as_utc(batch.expires_at),
                'can_retry': batch.status == 'confirmed' and bool(self._pending_vlan_batch_rows(children)),
                'results': [{'row_number': child.batch_row, 'plan_id': child.id, 'status': child.status}
                            for child in children]}

    async def retry_vlan_batch(self, actor: User, batch_id: str):
        batch = self._owned_vlan_batch(actor, batch_id)
        pending = self._pending_vlan_batch_rows(self._vlan_batch_children(batch_id))
        if batch.status != 'confirmed' or not pending:
            raise Conflict('El lote aún está activo, requiere conciliación o ya no tiene filas pendientes.')
        original = {row['row_number']: row for row in batch.rows}
        proposals = [(child.batch_row, SsidVlanChangeProposal.model_validate(
            original[child.batch_row]['proposal'],
        )) for child in pending]
        rows = await self._preview_vlan_batch_rows(actor, batch.scope_id, proposals)
        invalid = next((row for row in rows if row['errors']), None)
        if invalid:
            raise Conflict(
                f"Fila {invalid['row_number']}: {invalid['errors'][0]} Prepara un listado nuevo con las filas pendientes."
            )
        batch = self._owned_vlan_batch(actor, batch_id)
        require_open_scope(self.db, batch.scope_id)
        self.db.refresh(batch)
        current = self._pending_vlan_batch_rows(self._vlan_batch_children(batch_id))
        if batch.status != 'confirmed' or [row.batch_row for row in current] != [number for number, _ in proposals]:
            self.db.rollback()
            raise Conflict('El resultado del lote cambió. Recarga su estado antes de retomarlo.')
        batch.status = 'superseded'
        for child in current:
            if child.status == 'confirmed':
                child.status = 'cancelled'
        retry = self._store_vlan_batch(actor, batch.scope_id, rows)
        record_event(self.db, 'wifi.vlan_batch.retried', actor_id=actor.id,
                     details={'batch_id': retry.id, 'retry_of': batch_id,
                              'rows': [row['row_number'] for row in rows]})
        self.db.commit()
        return self._read_vlan_batch(retry)

    def list_vlan_batches(self, actor: User, scope_id: int, limit: int, offset: int):
        self.scope(actor, scope_id)
        batches = list(self.db.scalars(select(SsidVlanBatchPlan).where(
            SsidVlanBatchPlan.owner_id == actor.id, SsidVlanBatchPlan.scope_id == scope_id,
        ).order_by(SsidVlanBatchPlan.expires_at.desc(), SsidVlanBatchPlan.id).limit(limit).offset(offset)))
        if not batches:
            return []
        states = {batch.id: set() for batch in batches}
        for batch_id, status in self.db.execute(select(
            SsidVlanChangePlan.batch_id, SsidVlanChangePlan.status,
        ).where(SsidVlanChangePlan.batch_id.in_(states))):
            states[batch_id].add(status)
        now = utc_now()
        return [{'id': batch.id, 'status': batch.status, 'row_count': len(batch.rows),
                 'execution_status': self._vlan_batch_execution_status(batch, states[batch.id], now),
                 'expires_at': as_utc(batch.expires_at)} for batch in batches]

    def get_vlan_batch(self, actor: User, batch_id: str):
        return self._read_vlan_batch(self._owned_vlan_batch(actor, batch_id))

    async def confirm_vlan_batch(self, actor: User, batch_id: str, payload: SsidConfirm):
        batch = self._owned_vlan_batch(actor, batch_id, Permission.CHANGES_APPROVE)
        if batch.revision != payload.revision:
            raise Conflict('La revisión del lote no coincide.')
        if batch.status == 'confirmed' and batch.selection == payload.row_numbers:
            return self._read_vlan_batch(batch)
        if batch.status != 'preview' or as_utc(batch.expires_at) <= utc_now():
            raise Conflict('El lote ya no admite confirmación.')
        rows = {row['row_number']: row for row in batch.rows}
        if any(number not in rows or rows[number]['errors'] for number in payload.row_numbers):
            raise Conflict('Selecciona únicamente filas válidas.')
        context = await self.options(actor, batch.scope_id)
        children = []
        for number in payload.row_numbers:
            proposal = SsidVlanChangeProposal.model_validate(rows[number]['proposal'])
            child, _ = await self._build_vlan_change(actor, proposal, context)
            if child.revision != rows[number]['revision']:
                raise Conflict(f'Cambió el inventario de la fila {number}. Prepara otra vista previa.')
            children.append((number, child))
        batch = self._owned_vlan_batch(actor, batch_id, Permission.CHANGES_APPROVE)
        require_open_scope(self.db, batch.scope_id)
        now = utc_now()
        claimed = self.db.execute(update(SsidVlanBatchPlan).where(
            SsidVlanBatchPlan.id == batch_id, SsidVlanBatchPlan.status == 'preview',
            SsidVlanBatchPlan.revision == payload.revision, SsidVlanBatchPlan.expires_at > now,
        ).values(status='confirmed', selection=payload.row_numbers),
            execution_options={'synchronize_session': False})
        if claimed.rowcount != 1:
            self.db.rollback()
            raise Conflict('Otro proceso modificó el lote. Recarga su estado.')
        options = context[0]
        bindings = {network['id']: network for network in options['networks']}
        predecessor_id = None
        for number, child in children:
            child.batch_id = batch_id
            child.batch_row = number
            child.predecessor_id = predecessor_id
            child.status = 'confirmed'
            child.confirmed_at = now
            child.expires_at = batch.expires_at
            child.reservation_id = self._reservation_for(
                actor.id, options, bindings, child.target_network_id, child.ssid, now, lock=True,
            )
            self.db.add(child)
            self.db.flush()
            predecessor_id = child.id
        record_event(self.db, 'wifi.vlan_batch.confirmed', actor_id=actor.id,
                     details={'batch_id': batch_id, 'revision': payload.revision, 'rows': payload.row_numbers})
        self.db.commit()
        return self.get_vlan_batch(actor, batch_id)

    async def propose_vlan_change(
        self,
        actor: User,
        proposal: SsidVlanChangeProposal,
    ):
        """Valida y guarda una vista previa H10."""
        plan, preview = await self._build_vlan_change(actor, proposal)
        require_open_scope(self.db, plan.scope_id)
        self.db.add(plan)
        record_event(self.db, 'wifi.ssid_vlan_change.requested', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan.id, 'scope_id': plan.scope_id, 'broadcast_id': plan.broadcast_id})
        self.db.commit()
        return preview

    async def _build_vlan_change(self, actor: User, proposal: SsidVlanChangeProposal, context=None):
        options, fingerprint, target_network, current, site_id = await self._vlan_change_context(
            actor, proposal, context,
        )

        revision = digest([
            proposal.model_dump(), fingerprint, site_id,
            current["id"], current["ssid"], current["network_id"],
            proposal.network_id,
        ])
        now = utc_now()
        plan = SsidVlanChangePlan(
            id=str(uuid4()),
            owner_id=actor.id,
            scope_id=proposal.scope_id,
            broadcast_id=proposal.broadcast_id,
            site_id=site_id,
            ssid=current["ssid"],
            current_network_id=current["network_id"],
            target_network_id=proposal.network_id,
            purpose=proposal.purpose,
            status="preview",
            fingerprint=fingerprint,
            revision=revision,
            execution_results=[],
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.csv_preview_ttl_seconds),
            confirmed_at=None,
        )
        current_vlan = next((n["tag"] for n in options["networks"] if n["id"] == current["network_id"]), None)

        return plan, {
            "id": plan.id,
            "status": plan.status,
            "scope_id": plan.scope_id,
            "broadcast_id": plan.broadcast_id,
            "ssid": plan.ssid,
            "current_network_id": plan.current_network_id,
            "target_network_id": plan.target_network_id,
            # None: la red actual está fuera del ámbito y su etiqueta no se informa.
            "current_vlan": current_vlan,
            "target_vlan": target_network["tag"],
            "impact": (f"Los clientes conectados a «{plan.ssid}» se desconectarán brevemente y "
                       f"pasarán a la VLAN {target_network['tag']}. No cambia la clave ni los AP. "
                       "La conectividad de extremo a extremo requiere una prueba con un cliente."
                       + (" UniFi no identificó AP explícitos para esta señal."
                          if current.get('ap_ids') is None else "")),
            "purpose": plan.purpose,
            "fingerprint": plan.fingerprint,
            "revision": plan.revision,
            "expires_at": plan.expires_at.isoformat(),
            "requires_confirmation": True,
            "executed": False,
        }

    async def confirm_vlan_change(
        self,
        actor: User,
        plan_id: str,
        payload: SsidVlanChangeConfirm,
    ):
        """Confirma H10 tras revalidar el inventario. No escribe en UniFi."""
        require_user_permission(self.db, actor, Permission.CHANGES_APPROVE)
        plan = self.db.scalar(
            select(SsidVlanChangePlan).where(
                SsidVlanChangePlan.id == plan_id,
                SsidVlanChangePlan.owner_id == actor.id,
            )
        )
        if plan is None:
            raise NotFound("Plan de cambio de VLAN no encontrado.")

        self.scope(actor, plan.scope_id, Permission.CHANGES_APPROVE)
        if plan.revision != payload.revision:
            raise Conflict("La revisión no coincide con el plan mostrado.")
        if plan.status == "confirmed":
            return self.read_vlan_change_plan(plan)
        if plan.status != "preview" or as_utc(plan.expires_at) <= utc_now():
            raise Conflict("El plan ya no puede confirmarse o está vencido.")

        site_id = plan.site_id
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_APPROVE)
        scope_revision = digest([scope.site_id, scope.resources])
        if scope.site_id != site_id:
            raise Conflict("Cambió el sitio del ámbito. Prepara otra propuesta.")

        options, existing, fingerprint = await self.options(actor, plan.scope_id)
        current = await self.inventory.read_broadcast(site_id, plan.broadcast_id)

        # Reautorizar después de todas las esperas de red.
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_APPROVE)
        if digest([scope.site_id, scope.resources]) != scope_revision:
            raise Conflict("Cambió el ámbito. Prepara otra propuesta.")
        if options["simulated"] or self._vlan_target_fingerprint(fingerprint, current, options) != plan.fingerprint:
            raise Conflict("Cambió el inventario. Prepara otra propuesta.")
        if plan.target_network_id not in {n["id"] for n in options["networks"]}:
            raise Conflict("La VLAN de destino ya no está autorizada.")
        target = next((s for s in existing if s["id"] == plan.broadcast_id), None)
        if target is None or target["ssid"] != plan.ssid:
            raise Conflict("El SSID ya no coincide con el inventario.")
        if (
            current["id"] != plan.broadcast_id
            or current["ssid"] != plan.ssid
            or current["network_id"] != plan.current_network_id
        ):
            raise Conflict("La configuración del SSID cambió. Prepara otra propuesta.")

        require_open_scope(self.db, plan.scope_id)
        bindings = {network['id']: network for network in options['networks']}
        reservation_id = self._reservation_for(
            actor.id, options, bindings, plan.target_network_id, plan.ssid, utc_now(), lock=True,
        )
        result = self.db.execute(
            update(SsidVlanChangePlan)
            .where(
                SsidVlanChangePlan.id == plan_id,
                SsidVlanChangePlan.owner_id == actor.id,
                SsidVlanChangePlan.status == "preview",
                SsidVlanChangePlan.revision == payload.revision,
                SsidVlanChangePlan.expires_at > utc_now(),
            )
            .values(status="confirmed", confirmed_at=utc_now(), reservation_id=reservation_id),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise Conflict("El plan fue modificado por otra solicitud.")
        record_event(self.db, 'wifi.ssid_vlan_change.confirmed', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan_id, 'revision': payload.revision, 'reservation_id': reservation_id})
        self.db.commit()
        self.db.refresh(plan)
        return self.read_vlan_change_plan(plan)

    def _owned_vlan_change(self, actor: User, plan_id: str) -> SsidVlanChangePlan:
        require_user_permission(self.db, actor, Permission.CHANGES_REQUEST)
        plan = self.db.scalar(select(SsidVlanChangePlan).where(
            SsidVlanChangePlan.id == plan_id, SsidVlanChangePlan.owner_id == actor.id))
        if plan is None:
            raise NotFound("Plan de cambio de VLAN no encontrado.")
        self.scope(actor, plan.scope_id)
        return plan

    def get_vlan_change(self, actor: User, plan_id: str):
        return self.read_vlan_change_plan(self._owned_vlan_change(actor, plan_id))

    def list_vlan_changes(self, actor: User):
        require_user_permission(self.db, actor, Permission.CHANGES_REQUEST)
        result = []
        for plan in self.db.scalars(select(SsidVlanChangePlan).where(SsidVlanChangePlan.owner_id == actor.id)
                                    .order_by(SsidVlanChangePlan.created_at.desc()).limit(100)):
            try:
                self.scope(actor, plan.scope_id)
            except NotFound:
                continue
            result.append(self.read_vlan_change_plan(plan))
        return result

    def cancel_vlan_change(self, actor: User, plan_id: str):
        """Cancela una vista previa o una aprobación aún no tomada por el ejecutor."""
        plan = self._owned_vlan_change(actor, plan_id)
        result = self.db.execute(update(SsidVlanChangePlan).where(
            SsidVlanChangePlan.id == plan.id, SsidVlanChangePlan.status.in_(("preview", "confirmed")))
            .values(status="cancelled"), execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            self.db.rollback()
            raise Conflict("El plan ya fue tomado por el ejecutor o está finalizado.")
        record_event(self.db, 'wifi.ssid_vlan_change.cancelled', actor_id=actor.id, target_id=actor.id,
                     details={'plan_id': plan.id})
        self.db.commit()
        self.db.refresh(plan)
        return self.read_vlan_change_plan(plan)

    def read_vlan_change_plan(self, plan: SsidVlanChangePlan):
        """Representación segura del estado H10; no contiene secretos."""
        status = (
            "expired"
            if plan.status == "preview" and as_utc(plan.expires_at) <= utc_now()
            else plan.status
        )
        return {
            "id": plan.id,
            "scope_id": plan.scope_id,
            "broadcast_id": plan.broadcast_id,
            "ssid": plan.ssid,
            "current_network_id": plan.current_network_id,
            "target_network_id": plan.target_network_id,
            "purpose": plan.purpose,
            "status": status,
            "revision": plan.revision,
            "expires_at": as_utc(plan.expires_at).isoformat(),
            "confirmed_at": (
                as_utc(plan.confirmed_at).isoformat()
                if plan.confirmed_at is not None else None
            ),
            "requires_confirmation": status == "preview",
            "executed": status == "completed",
            # El lease se conserva hasta conciliar: nadie más puede tocar ese SSID.
            "needs_reconciliation": status in ("executing", "uncertain", "rollback_failed"),
            "execution_results": plan.execution_results or [],
        }

    @exclusive_plan('vlan')
    async def execute_vlan_change(self, plan_id: str):
        """Worker interno H10. No se expone por HTTP ni al LLM.

        El estado executing/uncertain y su lease son durables: no hay reintento
        automático tras una interrupción o respuesta ambigua del controlador.
        """
        plan = self.db.get(SsidVlanChangePlan, plan_id, populate_existing=True)
        if plan is None:
            raise NotFound('Plan H10 no encontrado.')
        actor = execution_actor(self.db, plan.owner_id)
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_EXECUTE)
        if plan.status != 'confirmed' or as_utc(plan.expires_at) <= utc_now():
            raise Conflict('El plan no está confirmado o ya venció.')
        if plan.predecessor_id is not None:
            predecessor = self.db.get(SsidVlanChangePlan, plan.predecessor_id, populate_existing=True)
            if predecessor is None or predecessor.status != 'completed':
                raise PlanBusy('La fila anterior del lote aún no se ha verificado.')
        if scope.site_id != plan.site_id:
            raise Conflict('El sitio del ámbito cambió.')
        if (not self.settings.unifi_write_enabled or self.settings.unifi_api_contract != '10.6.106'
                or self.settings.unifi_inventory_mode != 'api'):
            raise ServiceUnavailable('Ejecución H10 deshabilitada o contrato no autorizado.')

        scope_revision = digest([scope.site_id, scope.resources])
        options, existing, fingerprint = await self.options(actor, plan.scope_id)
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_EXECUTE)
        if digest([scope.site_id, scope.resources]) != scope_revision:
            raise Conflict('Cambió el ámbito o se revocó la autorización.')
        if options['simulated']:
            raise Conflict('El inventario simulado no permite ejecutar el cambio.')
        if plan.target_network_id not in {n['id'] for n in options['networks']}:
            raise Conflict('La red destino ya no está autorizada.')
        if not any(b['id'] == plan.broadcast_id and b['ssid'] == plan.ssid for b in existing):
            raise Conflict('El SSID ya no coincide con el inventario.')
        current = await self.inventory.read_broadcast(plan.site_id, plan.broadcast_id)
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_EXECUTE)
        if digest([scope.site_id, scope.resources]) != scope_revision:
            raise Conflict('Cambió el ámbito o se revocó la autorización.')
        if (current['id'] != plan.broadcast_id or current['ssid'] != plan.ssid
                or current['network_id'] != plan.current_network_id):
            raise Conflict('Cambió la VLAN original; prepara otro plan.')
        if self._vlan_target_fingerprint(fingerprint, current, options) != plan.fingerprint:
            raise Conflict('Cambió el inventario desde la confirmación.')

        bindings = {network['id']: network for network in options['networks']}

        def check_reservation():
            if plan.reservation_id is not None and self._reservation_for(
                actor.id, options, bindings, plan.target_network_id, plan.ssid, utc_now(),
            ) != plan.reservation_id:
                raise Conflict('La reserva confirmada ya no está vigente para este cambio.')

        check_reservation()
        require_open_scope(self.db, plan.scope_id)
        # PK compartida con la creación: bloqueo durable por sitio + nombre de SSID.
        resource_key = digest([plan.site_id, plan.ssid.casefold()])
        try:
            self.db.add(WifiWriteLease(resource_key=resource_key, vlan_plan_id=plan.id))
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise PlanBusy('El SSID está bloqueado por otra operación o conciliación pendiente.') from None
        if plan.reservation_id is not None:
            hold_reservation(self.db, plan.reservation_id, plan.id, utc_now())
        claim = self.db.execute(
            update(SsidVlanChangePlan).where(
                SsidVlanChangePlan.id == plan.id,
                SsidVlanChangePlan.status == 'confirmed',
                SsidVlanChangePlan.expires_at > utc_now(),
            ).values(status='executing', execution_started_at=utc_now()),
            execution_options={'synchronize_session': False},
        )
        if claim.rowcount != 1:
            self.db.rollback()
            raise Conflict('El plan ya fue tomado por otro ejecutor.')
        record_event(self.db, 'wifi.ssid_vlan_change.started', actor_id=actor.id,
                     target_id=actor.id, details={'plan_id': plan.id, 'scope_id': plan.scope_id,
                     'broadcast_id': plan.broadcast_id})
        self.db.commit()
        self.db.refresh(plan)

        def reauthorize():
            active = self.scope(actor, plan.scope_id, Permission.CHANGES_EXECUTE)
            if digest([active.site_id, active.resources]) != scope_revision:
                raise Conflict('Cambió el ámbito durante la ejecución.')

        # Desde executing nunca se repite la escritura original: se verifica y, si no se
        # puede acreditar el resultado, se concilia leyendo el controlador.
        write_returned = False
        try:
            reauthorize()
            await self.writer.update_vlan(
                plan.site_id, plan.broadcast_id, plan.current_network_id,
                plan.target_network_id, authorize=reauthorize,
            )
            write_returned = True
            plan.execution_results = [{'status': 'verifying', 'broadcast_id': plan.broadcast_id}]
            self.db.commit()
            verified = await self.writer.verify_vlan(
                plan.site_id, plan.broadcast_id, plan.ssid, plan.target_network_id,
            ) is True
        except ApplicationError:
            # El adaptador solo produce errores de aplicación antes del PUT.
            # Una respuesta ambigua del PUT usa WriteUncertain y sí requiere recuperación.
            self.db.rollback()
            if not write_returned:
                return self._finish_vlan_change(plan_id, actor.id, resource_key, 'failed')
            verified = False
        except Exception:
            # No guardar respuestas, excepciones ni credenciales del proveedor.
            self.db.rollback()
            verified = False
        outcome = 'completed' if verified else await self._recover_vlan_change(plan_id)
        return self._finish_vlan_change(plan_id, actor.id, resource_key, outcome)

    async def _recover_vlan_change(self, plan_id: str) -> str:
        """Concilia y restaura el estado previo. Solo revierte lo que este trabajo aplicó."""
        plan = self.db.get(SsidVlanChangePlan, plan_id)
        try:
            observed = await self.writer.read_network(plan.site_id, plan.broadcast_id)
        except Exception:
            return 'uncertain'
        if observed == plan.current_network_id:
            return 'failed'  # el controlador no aplicó el cambio: no hay nada que restaurar
        if observed != plan.target_network_id:
            return 'uncertain'  # otro actor cambió la red: no se sobrescribe su configuración
        try:
            # Convergencia tardía o escritura ambigua que sí se aplicó: no es un fallo.
            if await self.writer.verify_vlan(plan.site_id, plan.broadcast_id, plan.ssid,
                                             plan.target_network_id) is True:
                return 'completed'
        except Exception:
            pass
        try:
            # La restauración vuelve al estado aprobado como previo: no requiere otra aprobación.
            await self.writer.update_vlan(plan.site_id, plan.broadcast_id, plan.target_network_id,
                                          plan.current_network_id, authorize=lambda: None)
            restored = await self.writer.verify_vlan(plan.site_id, plan.broadcast_id, plan.ssid,
                                                     plan.current_network_id) is True
        except Exception:
            restored = False
        return 'rolled_back' if restored else 'rollback_failed'

    def _finish_vlan_change(self, plan_id: str, actor_id: int, resource_key: str, outcome: str):
        """Persiste el resultado, la auditoría y el escalamiento en una sola transacción."""
        plan = self.db.get(SsidVlanChangePlan, plan_id)
        plan.status = outcome
        if plan.reservation_id is not None:
            if outcome == 'completed':
                mark_assigned(self.db, plan.reservation_id, utc_now(), plan_id=plan.id)
            elif outcome in {'failed', 'rolled_back'}:
                clear_reservation_hold(self.db, plan.reservation_id, plan.id)
        result = 'verified_configuration' if outcome == 'completed' else outcome
        plan.execution_results = [{'status': result, 'broadcast_id': plan.broadcast_id}]
        record_event(self.db, f'wifi.ssid_vlan_change.{outcome}', actor_id=actor_id, target_id=actor_id,
                     source='worker', outcome={'completed': 'success', 'uncertain': 'uncertain'}.get(outcome, 'failure'),
                     details={'plan_id': plan.id, 'scope_id': plan.scope_id, 'broadcast_id': plan.broadcast_id})
        if outcome in ('completed', 'failed', 'rolled_back'):
            self.db.execute(delete(WifiWriteLease).where(
                WifiWriteLease.resource_key == resource_key, WifiWriteLease.vlan_plan_id == plan.id))
        # uncertain / rollback_failed conservan el lease hasta la conciliación.
        key = f'change:vlan:{plan.id}'
        if outcome == 'rolled_back':
            self._incident('verification_failed', key,
                           f'El cambio de VLAN de «{plan.ssid}» no se verificó; se restauró la red anterior.')
        elif outcome == 'rollback_failed':
            self._incident('rollback_failed', key,
                           f'No se pudo restaurar la VLAN anterior de «{plan.ssid}». Requiere conciliación manual.')
        elif outcome == 'uncertain':
            self._incident('verification_failed', key,
                           f'El cambio de VLAN de «{plan.ssid}» quedó en estado incierto. Requiere conciliación.')
        self.db.commit()
        return self.read_vlan_change_plan(plan)

    @exclusive_plan('vlan')
    async def reconcile_vlan_change(self, plan_id: str):
        """Resuelve un plan detenido leyendo el controlador. No escribe en la red."""
        plan = self.db.get(SsidVlanChangePlan, plan_id, populate_existing=True)
        if plan is None:
            raise NotFound('Plan H10 no encontrado.')
        if plan.status not in ('executing', 'uncertain', 'rollback_failed'):
            raise Conflict('El plan no requiere conciliación.')
        try:
            observed = await self.writer.read_network(plan.site_id, plan.broadcast_id)
        except ApplicationError:
            raise
        except Exception:
            raise ServiceUnavailable('No se pudo leer la red actual del SSID.') from None
        if observed == plan.target_network_id:
            outcome = 'completed'
        elif observed == plan.current_network_id:
            outcome = 'rolled_back' if plan.status == 'rollback_failed' else 'failed'
        else:
            raise Conflict('El SSID usa una red distinta de la original y de la solicitada. Revísalo en el controlador.')
        resource_key = digest([plan.site_id, plan.ssid.casefold()])
        plan = self.db.get(SsidVlanChangePlan, plan_id)
        plan.status = outcome
        if plan.reservation_id is not None:
            if outcome == 'completed':
                mark_assigned(self.db, plan.reservation_id, utc_now(), plan_id=plan.id)
            elif outcome in {'failed', 'rolled_back'}:
                clear_reservation_hold(self.db, plan.reservation_id, plan.id)
        plan.execution_results = [{'status': 'reconciled_' + outcome, 'broadcast_id': plan.broadcast_id}]
        record_event(self.db, 'wifi.ssid_vlan_change.reconciled', actor_id=plan.owner_id, target_id=plan.owner_id,
                     source='worker', outcome='success' if outcome == 'completed' else 'failure',
                     details={'plan_id': plan.id, 'result': outcome})
        self.db.execute(delete(WifiWriteLease).where(
            WifiWriteLease.resource_key == resource_key, WifiWriteLease.vlan_plan_id == plan.id))
        self.db.commit()
        return self.read_vlan_change_plan(plan)

    async def propose(self, actor, proposal: SsidProposal):
        options, existing, _ = await self.options(actor,proposal.scope_id)
        self.validate(proposal,options,existing)
        return {'proposal':proposal.model_dump(),'status':'awaiting_confirmation',
                'simulated':options['simulated'],'message':'Propuesta de creación. Confirma en el panel; todavía no se creó ningún SSID.'}

    def _store(self, actor, scope_id, options, fingerprint, rows, *, retry_of=None):
        self.scope(actor,scope_id)
        now=utc_now()
        revision=digest([scope_id,fingerprint,rows])
        plan=SsidPlan(id=str(uuid4()),owner_id=actor.id,scope_id=scope_id,status='preview',
                      source='mock' if options['simulated'] else 'unifi', fingerprint=fingerprint,revision=revision,
                      rows=rows,selection=[],created_at=now,expires_at=now+timedelta(seconds=self.settings.csv_preview_ttl_seconds))
        require_open_scope(self.db, plan.scope_id)
        self.db.add(plan)
        record_event(self.db, 'ssid.plan.prepared', actor_id=actor.id,
                     details={'plan_id': plan.id, 'scope_id': scope_id, 'revision': revision,
                              **({'retry_of': retry_of} if retry_of else {})})
        self.db.commit()
        return self.read(plan)

    async def prepare(self, actor, proposal):
        options, existing, fingerprint=await self.options(actor,proposal.scope_id)
        self.validate(proposal,options,existing)
        return self._store(actor,proposal.scope_id,options,fingerprint,[{'row_number':1,'proposal':proposal.model_dump(),'errors':[]}])

    async def retry(self, actor: User, plan_id: str) -> SsidPlanRead:
        original = self.owned(actor, plan_id)
        if original.status not in {'partial', 'failed'}:
            raise Conflict('Solo se retoman planes fallidos o parciales con resultado resuelto.')
        scope_id = original.scope_id
        options, existing, fingerprint = await self.options(actor, scope_id)
        original = self.owned(actor, plan_id)
        if original.status not in {'partial', 'failed'}:
            raise Conflict('El resultado del plan cambió. Recarga antes de retomarlo.')

        results = {row['ssid']: row['status'] for row in original.execution_results}
        approved_numbers = set(original.selection)
        rows = []
        for row in original.rows:
            if row['row_number'] not in approved_numbers:
                continue
            proposal = SsidProposal.model_validate(row['proposal'])
            status = results.get(proposal.ssid)
            if status == 'verified_configuration':
                continue
            if status not in {'failed', 'rolled_back', 'not_started'}:
                raise Conflict('El resultado de una fila no está resuelto. Revisa el plan original.')
            try:
                self.validate(proposal, options, existing)
            except Conflict as error:
                raise Conflict(
                    f"Fila {row['row_number']}: {error.detail} Corrige las filas pendientes en un nuevo listado."
                ) from None
            rows.append({'row_number': row['row_number'], 'proposal': proposal.model_dump(), 'errors': []})
        if not rows:
            raise Conflict('El plan no tiene filas pendientes que se puedan retomar.')
        return self._store(actor, scope_id, options, fingerprint, rows, retry_of=plan_id)

    async def csv(self, actor, payload: SsidCsv):
        self.scope(actor,payload.scope_id)
        parsed=parse_csv(payload.csv_text.encode(),max_bytes=self.settings.csv_max_bytes,max_rows=self.settings.csv_max_rows)
        options, existing, fingerprint=await self.options(actor,payload.scope_id)
        rows=[]
        for row in parsed:
            proposal=None; errors=list(row.errors)
            if row.data is not None and row.data.event_name != options['event_name']:
                errors.append('El evento de la fila no corresponde al ámbito seleccionado.')
            if row.data is not None and not errors:
                binding=next((n for n in options['networks'] if (n['parent_interface'],n['tag'])==(row.data.parent_interface,row.data.tag)),None)
                if not binding: errors.append('VLAN fuera del ámbito o ausente del inventario.')
                else:
                    try:
                        proposal=SsidProposal(scope_id=payload.scope_id,ssid=row.data.ssid,network_id=binding['id'],
                            ap_ids=payload.ap_ids,security_profile=payload.security_profile,purpose=row.data.purpose)
                        self.validate(proposal,options,existing)
                    except ValidationError:
                        errors.append('Propuesta inválida: comprueba el SSID (máximo 32 bytes UTF-8) y los recursos seleccionados.')
                    except Conflict as exc:
                        errors.append(exc.detail)
            rows.append({'row_number':row.row_number,'proposal':proposal.model_dump() if proposal else None,'errors':errors})
        return self._store(actor,payload.scope_id,options,fingerprint,rows)

    async def workbook(self, actor: User, payload: SsidWorkbook):
        self.scope(actor, payload.scope_id)
        try:
            content = b64decode(payload.xlsx_base64.get_secret_value(), validate=True)
        except (Base64Error, ValueError):
            raise InvalidInput('El contenido del Excel no es válido.') from None
        parsed = parse_event_workbook(
            content, max_bytes=self.settings.csv_max_bytes, max_rows=self.settings.csv_max_rows,
        )
        options, existing, fingerprint = await self.options(actor, payload.scope_id)
        rows = []
        for row in parsed:
            errors = list(row.errors)
            proposal = None
            if row.event.casefold() != options['event_name'].casefold():
                errors.append('El evento de la fila no corresponde al ámbito seleccionado.')
            if not errors:
                matches = [network for network in options['networks'] if network['tag'] == row.vlan]
                if len(matches) != 1:
                    errors.append('La VLAN no existe en el ámbito o coincide con más de una red.')
                else:
                    try:
                        candidate = SsidProposal(
                            scope_id=payload.scope_id,
                            ssid=row.ssid,
                            network_id=matches[0]['id'],
                            ap_ids=payload.ap_ids,
                            security_profile=payload.security_profile,
                            purpose='Propuesta Wi-Fi desde la planilla del evento',
                        )
                        self.validate(candidate, options, existing)
                        proposal = candidate.model_dump()
                    except ValidationError:
                        errors.append('SSID inválido: comprueba que ocupe hasta 32 bytes UTF-8.')
                    except Conflict as exc:
                        errors.append(exc.detail)
            rows.append({'row_number': row.number, 'proposal': proposal, 'errors': errors})
        return self._store(actor, payload.scope_id, options, fingerprint, rows)

    def owned(self, actor, plan_id, permission=Permission.CHANGES_REQUEST):
        require_user_permission(self.db,actor,permission)
        plan=self.db.scalar(select(SsidPlan).where(SsidPlan.id==plan_id,SsidPlan.owner_id==actor.id))
        if plan is None: raise NotFound('Plan no encontrado.')
        self.scope(actor,plan.scope_id,permission)
        return plan

    def read(self, plan):
        state='expired' if plan.status=='preview' and as_utc(plan.expires_at)<=utc_now() else plan.status
        execution = 'awaiting_executor' if plan.status=='confirmed' else plan.status if plan.status in {'executing','completed','partial','uncertain','failed'} else 'not_confirmed'
        return SsidPlanRead(id=plan.id,scope_id=plan.scope_id,status=state,source=plan.source,simulated=plan.source=='mock',
            revision=plan.revision,rows=plan.rows,selection=plan.selection,expires_at=as_utc(plan.expires_at),
            execution_status=execution, execution_results=plan.execution_results)

    def get(self, actor, plan_id): return self.read(self.owned(actor,plan_id))

    def list(self, actor):
        require_user_permission(self.db,actor,Permission.CHANGES_REQUEST)
        result=[]
        for plan in self.db.scalars(select(SsidPlan).where(SsidPlan.owner_id==actor.id).order_by(SsidPlan.created_at.desc()).limit(100)):
            try: self.scope(actor,plan.scope_id)
            except NotFound: continue
            result.append(self.read(plan))
        return result

    async def confirm(self, actor, plan_id, payload: SsidConfirm):
        plan=self.owned(actor,plan_id,Permission.CHANGES_APPROVE)
        def check():
            if plan.revision!=payload.revision: raise Conflict('La revisión no coincide con el plan mostrado.')
            if plan.status=='confirmed':
                if plan.selection!=payload.row_numbers: raise Conflict('El plan ya se confirmó con otra selección.')
                return self.read(plan)
            if self.read(plan).status!='preview': raise Conflict('El plan ya no puede confirmarse.')
            rows={r['row_number']:r for r in plan.rows}
            if any(n not in rows or rows[n]['errors'] or rows[n]['proposal'] is None for n in payload.row_numbers):
                raise Conflict('Selecciona únicamente filas válidas.')
        old=check()
        if old: return old
        options, _, fingerprint = await self.options(actor, plan.scope_id)
        plan=self.owned(actor,plan_id,Permission.CHANGES_APPROVE)
        old=check()
        if old: return old
        if fingerprint!=plan.fingerprint: raise Conflict('Cambió el inventario o ámbito. Prepara una nueva propuesta.')
        bindings = {network['id']: network for network in options['networks']}
        require_open_scope(self.db, plan.scope_id)
        now = utc_now()
        approved_rows = []
        for row in plan.rows:
            if row['row_number'] in payload.row_numbers:
                proposal = SsidProposal.model_validate(row['proposal'])
                reservation_id = self._reservation_for(actor.id, options, bindings, proposal.network_id, proposal.ssid, now, lock=True)
                row = {**row, 'reservation_id': reservation_id}
            approved_rows.append(row)
        result=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan_id,SsidPlan.status=='preview',
            SsidPlan.expires_at>utc_now(),SsidPlan.revision==payload.revision).values(status='confirmed',
            selection=payload.row_numbers,confirmed_at=now,rows=approved_rows),execution_options={'synchronize_session':False})
        if result.rowcount!=1:
            self.db.rollback(); raise Conflict('Otra solicitud modificó el plan. Recarga su estado.')
        record_event(self.db, 'ssid.plan.confirmed', actor_id=actor.id,
                     details={'plan_id': plan_id, 'revision': payload.revision, 'rows': payload.row_numbers,
                              'reservation_ids': [row['reservation_id'] for row in approved_rows
                                                  if row.get('reservation_id') is not None]})
        self.db.commit(); self.db.refresh(plan)
        return self.read(plan)

    def cancel(self, actor, plan_id):
        plan=self.owned(actor,plan_id)
        result=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan.id,SsidPlan.status=='preview').values(status='cancelled'),execution_options={'synchronize_session':False})
        if result.rowcount!=1:
            self.db.rollback(); raise Conflict('Un plan confirmado no puede cancelarse como vista previa.')
        record_event(self.db, 'ssid.plan.cancelled', actor_id=actor.id, details={'plan_id': plan_id})
        self.db.commit(); self.db.refresh(plan)
        return self.read(plan)


    def _reservation_for(self, actor_id, options, bindings, network_id, ssid, now, *, lock=False):
        binding = bindings.get(network_id)
        if binding is None:
            return None
        return find_reserved_vlan(
            self.db, parent_interface=binding['parent_interface'], tag=binding['tag'],
            event_name=options['event_name'], ssid=ssid, actor_id=actor_id, now=now, lock=lock,
        )

    @exclusive_plan('ssid')
    async def execute(self, plan_id):
        """Entrada exclusiva del worker. Nunca expuesta como herramienta del LLM.
        Running/uncertain no se reintentan automáticamente después de un crash.
        """
        from .ssid_executor import WriteUncertain
        plan=self.db.get(SsidPlan,plan_id,populate_existing=True)
        if plan is None: raise NotFound('Plan no encontrado.')
        actor=execution_actor(self.db,plan.owner_id)
        scope=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
        if plan.status!='confirmed': raise Conflict('Solo se ejecutan planes confirmados y aún no iniciados.')
        if as_utc(plan.expires_at)<=utc_now(): raise Conflict('La aprobación está fuera de vigencia. Prepara otro plan.')
        options,existing,fingerprint=await self.options(actor,scope.id)
        scope=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
        if fingerprint!=plan.fingerprint: raise Conflict('Cambió el inventario/perfil. Es necesaria otra propuesta y confirmación.')
        approved_rows = [row for row in plan.rows if row['row_number'] in plan.selection]
        selected = [SsidProposal.model_validate(row['proposal']) for row in approved_rows]
        if not selected: raise Conflict('El plan no contiene una selección aprobada.')
        if plan.source=='mock':
            raise Conflict('Un plan simulado nunca se ejecuta en infraestructura real.')
        if not self.settings.unifi_write_enabled or self.settings.unifi_api_contract!='10.6.106':
            raise ServiceUnavailable('El ejecutor real está deshabilitado o el contrato no fue confirmado.')
        for proposal in selected:
            self.validate(proposal,options,existing)
            self.writer.profile(proposal.security_profile)
        require_open_scope(self.db, plan.scope_id)
        # Exclusión durable por SSID/sitio, también entre ámbitos superpuestos.
        try:
            self.db.add_all([WifiWriteLease(resource_key=digest([scope.site_id,p.ssid.casefold()]),plan_id=plan_id) for p in selected])
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise PlanBusy('Otro trabajo posee el SSID o requiere conciliación manual.') from None
        claimed=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan_id,SsidPlan.status=='confirmed',SsidPlan.expires_at>utc_now()).values(status='executing',execution_started_at=utc_now()),execution_options={'synchronize_session':False})
        if claimed.rowcount!=1:
            self.db.rollback(); raise Conflict('El plan fue tomado por otro ejecutor.')
        record_event(self.db, 'ssid.plan.claimed', actor_id=actor.id, source='worker', details={'plan_id': plan_id})
        self.db.commit(); self.db.refresh(plan)
        scope_revision=digest([scope.site_id,scope.resources])
        site_id=scope.site_id
        bindings={n['id']:n for n in options['networks']}
        def reauthorize():
            active=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
            if digest([active.site_id,active.resources])!=scope_revision:
                raise Conflict('Cambió el ámbito durante la ejecución.')
        results=[{'ssid':p.ssid,'status':'not_started'} for p in selected]
        # Política de lote: detener en el primer fallo, compensar solo la fila afectada y
        # conservar las filas ya verificadas. Nunca se reintenta una escritura ambigua.
        for entry, proposal, row in zip(results, selected, approved_rows):
            reservation_id = row.get('reservation_id')
            try:
                reauthorize()
                if reservation_id is not None:
                    expected = self._reservation_for(
                        actor.id, options, bindings, proposal.network_id, proposal.ssid, utc_now(),
                    )
                    if expected != reservation_id:
                        raise Conflict('La reserva confirmada ya no está vigente para este cambio.')
                    hold_reservation(self.db, reservation_id, plan_id, utc_now())
                entry['status'] = 'writing'
                plan.execution_results = [dict(result) for result in results]
                self.db.commit()
                external_id = await self.writer.create(site_id, proposal, authorize=reauthorize)
            except WriteUncertain:
                entry['status']='uncertain'; break
            except ApplicationError:
                # Rechazo anterior a la escritura (permiso, versión, perfil): nada que compensar.
                self.db.rollback(); entry['status']='failed'; break
            except Exception:
                self.db.rollback(); entry['status']='uncertain'; break
            entry.update(external_id=external_id,status='verifying')
            plan=self.db.get(SsidPlan,plan_id); plan.execution_results=[dict(r) for r in results]; self.db.commit()
            try:
                verified=await self.writer.verify(site_id,external_id,proposal) is True
            except Exception:
                verified=False
            if verified:
                entry['status']='verified_configuration'
                if reservation_id is not None:
                    mark_assigned(self.db, reservation_id, utc_now(), plan_id=plan_id)
                plan.execution_results = [dict(result) for result in results]
                self.db.commit()
                continue
            # Compensación: se elimina únicamente el SSID creado por este trabajo.
            try:
                removed=await self.writer.delete_created(site_id,external_id,proposal.ssid) is True
            except Exception:
                removed=False
            entry['status']='rolled_back' if removed else 'rollback_failed'
            break
        return self._finish_plan(plan_id,actor.id,site_id,results)

    def _finish_plan(self, plan_id, actor_id, site_id, results):
        """Estado final del lote, liberación de bloqueos resueltos, auditoría y escalamiento."""
        plan=self.db.get(SsidPlan,plan_id)
        by_ssid = {result['ssid']: result['status'] for result in results}
        for row in plan.rows:
            reservation_id = row.get('reservation_id')
            if reservation_id is None:
                continue
            outcome = by_ssid.get(row['proposal']['ssid'])
            if outcome == 'verified_configuration':
                mark_assigned(self.db, reservation_id, utc_now(), plan_id=plan_id)
            elif outcome not in {'uncertain', 'rollback_failed', 'verifying', 'writing'}:
                clear_reservation_hold(self.db, reservation_id, plan_id)
        states=[r['status'] for r in results]
        verified=states.count('verified_configuration')
        if any(s in ('uncertain','rollback_failed','verifying','writing') for s in states):
            status='uncertain'
        elif verified==len(states):
            status='completed'
        else:
            status='partial' if verified else 'failed'
        plan.status=status; plan.execution_results=[dict(r) for r in results]
        # El bloqueo solo se conserva para los SSID cuyo estado remoto no se pudo acreditar.
        resolved=[digest([site_id,r['ssid'].casefold()]) for r in results
                  if r['status'] not in ('uncertain','rollback_failed','verifying','writing')]
        if resolved:
            self.db.execute(delete(WifiWriteLease).where(WifiWriteLease.plan_id==plan_id,
                                                         WifiWriteLease.resource_key.in_(resolved)))
        record_event(self.db, 'ssid.plan.executed', actor_id=actor_id, source='worker',
                     outcome='success' if status == 'completed' else 'failure',
                     details={'plan_id': plan_id, 'status': status,
                              'rows': [{'ssid': r['ssid'], 'status': r['status']} for r in results]})
        for row in results:
            key=f"change:ssid:{plan_id}:{row['ssid']}"
            if row['status']=='rolled_back':
                self._incident('verification_failed',key,f"El SSID «{row['ssid']}» no se verificó tras crearlo; se eliminó.")
            elif row['status']=='rollback_failed':
                self._incident('rollback_failed',key,f"El SSID «{row['ssid']}» no se verificó y no se pudo eliminar. Requiere conciliación manual.")
            elif row['status'] in ('uncertain','verifying'):
                self._incident('verification_failed',key,f"La creación del SSID «{row['ssid']}» quedó en estado incierto. Requiere conciliación.")
        self.db.commit()
        return self.read(plan)

    @exclusive_plan('ssid')
    async def reconcile(self, plan_id):
        """Resuelve un lote detenido comparando con el inventario. No escribe en la red."""
        plan=self.db.get(SsidPlan,plan_id,populate_existing=True)
        if plan is None: raise NotFound('Plan no encontrado.')
        if plan.status not in ('executing','uncertain'): raise Conflict('El plan no requiere conciliación.')
        scope=self.db.get(WifiScope,plan.scope_id)
        if scope is None: raise NotFound('Ámbito no encontrado.')
        site_id=scope.site_id
        remote={b['ssid']:b['id'] for b in (await self.inventory.read(site_id))['ssids']}
        selected={p.ssid:p for p in (SsidProposal.model_validate(r['proposal']) for r in plan.rows
                                       if r['row_number'] in plan.selection)}
        previous={r['ssid']:r for r in (plan.execution_results or [])}
        results=[]
        for ssid,proposal in selected.items():
            entry=dict(previous.get(ssid) or {'ssid':ssid,'status':'not_started'})
            if entry['status'] in ('uncertain','rollback_failed','verifying','not_started','writing'):
                external_id=remote.get(ssid)
                if external_id is None:
                    # Ausente: no se creó o la compensación sí se aplicó.
                    entry['status']='rolled_back' if entry['status']=='rollback_failed' else 'not_created'
                    entry.pop('external_id',None)
                elif await self.writer.verify(site_id,external_id,proposal) is True:
                    entry.update(external_id=external_id,status='verified_configuration')
                elif plan.status=='uncertain':
                    raise Conflict(f'El SSID «{ssid}» existe con otra configuración. Revísalo en el controlador.')
            results.append(entry)
        plan=self.db.get(SsidPlan,plan_id)
        record_event(self.db, 'ssid.plan.reconciled', actor_id=plan.owner_id, source='worker',
                     details={'plan_id': plan_id})
        # not_created cuenta como fila fallida sin efecto remoto.
        return self._finish_plan(plan_id,plan.owner_id,site_id,
                                 [dict(r,status='failed') if r['status']=='not_created' else r for r in results])
