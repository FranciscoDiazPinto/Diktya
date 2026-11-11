"""Planes SSID privados compartidos por CSV y chat. Confirmar no ejecuta UniFi."""
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
from app.core.errors import NotFound, Conflict, InvalidInput, ServiceUnavailable
from app.core.config import Settings
from app.monitoring.service import MonitoringService
from .models import (
    WifiScope,
    WifiScopeGrant,
    SsidPlan,
    WifiWriteLease,
    SsidVlanChangePlan,
)
from .ssid_schemas import (
    ScopeWrite,
    SsidProposal,
    SsidCsv,
    SsidConfirm,
    SsidPlanRead,
    SsidVlanChangeProposal,
    SsidVlanChangeConfirm,
)
from .wifi_inventory import WifiInventory
from .csv_parser import parse_csv
from .csv_service import as_utc, utc_now


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SsidPlanService:
    def __init__(self, db: Session, settings: Settings, monitoring: MonitoringService, inventory=None, writer=None):
        self.db, self.settings, self.monitoring = db, settings, monitoring
        self.inventory = inventory or WifiInventory(settings)
        from .ssid_executor import UniFiSsidWriter
        self.writer = writer or UniFiSsidWriter(settings)

    def scope(self, actor: User, scope_id: int, permission=Permission.CHANGES_REQUEST):
        require_user_permission(self.db, actor, permission)
        scope = self.db.get(WifiScope, scope_id)
        admin = Permission.NETWORKS_MANAGE in effective_permissions(actor)
        if scope is None or (not admin and not self.db.get(WifiScopeGrant, (scope_id,actor.id))):
            queue_denial(actor.id, permission, reason='wifi_scope')
            raise NotFound('Ámbito de aprovisionamiento no encontrado.')
        return scope

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
        return safe, remote['ssids'], fingerprint

    def validate(self, proposal: SsidProposal, options, existing):
        if not set(proposal.ap_ids) <= {a['id'] for a in options['aps']}:
            raise Conflict('Selecciona únicamente AP autorizados y presentes en el inventario.')
        if proposal.network_id not in {n['id'] for n in options['networks']}:
            raise Conflict('La red/VLAN no está autorizada o no coincide con el inventario existente.')
        if proposal.security_profile not in options['security_profiles']:
            raise Conflict('Perfil de seguridad no autorizado.')
        if any(b['ssid'].casefold()==proposal.ssid.casefold() for b in existing):
            raise Conflict('El SSID ya existe. No se sobrescribe mediante una creación.')

    async def propose_vlan_change(
        self,
        actor: User,
        proposal: SsidVlanChangeProposal,
    ):
        """Valida y guarda una vista previa H10; nunca escribe en UniFi."""
        options, existing, fingerprint = await self.options(actor, proposal.scope_id)

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
        self.db.add(plan)
        self.db.commit()

        return {
            "id": plan.id,
            "status": plan.status,
            "scope_id": plan.scope_id,
            "broadcast_id": plan.broadcast_id,
            "ssid": plan.ssid,
            "current_network_id": plan.current_network_id,
            "target_network_id": plan.target_network_id,
            "target_vlan": target_network["tag"],
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
        if options["simulated"] or fingerprint != plan.fingerprint:
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

        result = self.db.execute(
            update(SsidVlanChangePlan)
            .where(
                SsidVlanChangePlan.id == plan_id,
                SsidVlanChangePlan.owner_id == actor.id,
                SsidVlanChangePlan.status == "preview",
                SsidVlanChangePlan.revision == payload.revision,
                SsidVlanChangePlan.expires_at > utc_now(),
            )
            .values(status="confirmed", confirmed_at=utc_now()),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise Conflict("El plan fue modificado por otra solicitud.")
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
            "execution_results": plan.execution_results or [],
        }

    async def execute_vlan_change(self, plan_id: str):
        """Worker interno H10. No se expone por HTTP ni al LLM.

        El estado executing/uncertain y su lease son durables: no hay reintento
        automático tras una interrupción o respuesta ambigua del controlador.
        """
        plan = self.db.get(SsidVlanChangePlan, plan_id)
        if plan is None:
            raise NotFound('Plan H10 no encontrado.')
        actor = execution_actor(self.db, plan.owner_id)
        scope = self.scope(actor, plan.scope_id, Permission.CHANGES_EXECUTE)
        if plan.status != 'confirmed' or as_utc(plan.expires_at) <= utc_now():
            raise Conflict('El plan no está confirmado o ya venció.')
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
        if options['simulated'] or fingerprint != plan.fingerprint:
            raise Conflict('Cambió el inventario desde la confirmación.')
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

        # PK compartida con la creación: bloqueo durable por sitio + nombre de SSID.
        resource_key = digest([plan.site_id, plan.ssid.casefold()])
        try:
            self.db.add(WifiWriteLease(resource_key=resource_key, vlan_plan_id=plan.id))
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise Conflict('El SSID está bloqueado por otra operación o conciliación pendiente.') from None
        claim = self.db.execute(
            update(SsidVlanChangePlan).where(
                SsidVlanChangePlan.id == plan.id,
                SsidVlanChangePlan.status == 'confirmed',
                SsidVlanChangePlan.expires_at > utc_now(),
            ).values(status='executing'),
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

        # Desde executing, cualquier excepción deja el plan incierto, nunca se reintenta.
        try:
            reauthorize()
            await self.writer.update_vlan(
                plan.site_id, plan.broadcast_id, plan.current_network_id,
                plan.target_network_id, authorize=reauthorize,
            )
            plan.execution_results = [{'status': 'verifying', 'broadcast_id': plan.broadcast_id}]
            self.db.commit()
            verified = await self.writer.verify_vlan(
                plan.site_id, plan.broadcast_id, plan.ssid, plan.target_network_id,
            )
            if not verified:
                raise RuntimeError('Verificación inconclusa')
            plan.status = 'completed'
            plan.execution_results = [{'status': 'verified_configuration', 'broadcast_id': plan.broadcast_id}]
            record_event(self.db, 'wifi.ssid_vlan_change.completed', actor_id=actor.id,
                         target_id=actor.id, details={'plan_id': plan.id, 'scope_id': plan.scope_id,
                         'broadcast_id': plan.broadcast_id})
            self.db.execute(delete(WifiWriteLease).where(
                WifiWriteLease.resource_key == resource_key,
                WifiWriteLease.vlan_plan_id == plan.id,
            ))
            self.db.commit()
        except Exception:
            # No guardar respuestas, excepciones ni credenciales del proveedor.
            self.db.rollback()
            plan = self.db.get(SsidVlanChangePlan, plan_id)
            plan.status = 'uncertain'
            plan.execution_results = [{'status': 'uncertain', 'broadcast_id': plan.broadcast_id}]
            record_event(self.db, 'wifi.ssid_vlan_change.uncertain', actor_id=actor.id,
                         target_id=actor.id, outcome='uncertain',
                         details={'plan_id': plan.id, 'scope_id': plan.scope_id,
                                  'broadcast_id': plan.broadcast_id})
            self.db.commit()  # conservar lease hasta conciliación manual
        return self.read_vlan_change_plan(plan)

    async def propose(self, actor, proposal: SsidProposal):
        options, existing, _ = await self.options(actor,proposal.scope_id)
        self.validate(proposal,options,existing)
        return {'proposal':proposal.model_dump(),'status':'awaiting_confirmation',
                'simulated':options['simulated'],'message':'Propuesta de creación. Confirma en el panel; todavía no se creó ningún SSID.'}

    def _store(self, actor, scope_id, options, fingerprint, rows):
        self.scope(actor,scope_id)
        now=utc_now()
        revision=digest([scope_id,fingerprint,rows])
        plan=SsidPlan(id=str(uuid4()),owner_id=actor.id,scope_id=scope_id,status='preview',
                      source='mock' if options['simulated'] else 'unifi', fingerprint=fingerprint,revision=revision,
                      rows=rows,selection=[],created_at=now,expires_at=now+timedelta(seconds=self.settings.csv_preview_ttl_seconds))
        self.db.add(plan); self.db.commit()
        return self.read(plan)

    async def prepare(self, actor, proposal):
        options, existing, fingerprint=await self.options(actor,proposal.scope_id)
        self.validate(proposal,options,existing)
        return self._store(actor,proposal.scope_id,options,fingerprint,[{'row_number':1,'proposal':proposal.model_dump(),'errors':[]}])

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
        _,_,fingerprint=await self.options(actor,plan.scope_id)
        plan=self.owned(actor,plan_id,Permission.CHANGES_APPROVE)
        old=check()
        if old: return old
        if fingerprint!=plan.fingerprint: raise Conflict('Cambió el inventario o ámbito. Prepara una nueva propuesta.')
        result=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan_id,SsidPlan.status=='preview',
            SsidPlan.expires_at>utc_now(),SsidPlan.revision==payload.revision).values(status='confirmed',
            selection=payload.row_numbers,confirmed_at=utc_now()),execution_options={'synchronize_session':False})
        if result.rowcount!=1:
            self.db.rollback(); raise Conflict('Otra solicitud modificó el plan. Recarga su estado.')
        self.db.commit(); self.db.refresh(plan)
        return self.read(plan)

    def cancel(self, actor, plan_id):
        plan=self.owned(actor,plan_id)
        result=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan.id,SsidPlan.status=='preview').values(status='cancelled'),execution_options={'synchronize_session':False})
        if result.rowcount!=1:
            self.db.rollback(); raise Conflict('Un plan confirmado no puede cancelarse como vista previa.')
        self.db.commit(); self.db.refresh(plan)
        return self.read(plan)


    async def execute(self, plan_id):
        """Entrada exclusiva del worker. Nunca expuesta como herramienta del LLM.
        Running/uncertain no se reintentan automáticamente después de un crash.
        """
        from .ssid_executor import WriteUncertain
        plan=self.db.get(SsidPlan,plan_id)
        if plan is None: raise NotFound('Plan no encontrado.')
        actor=execution_actor(self.db,plan.owner_id)
        scope=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
        if plan.status!='confirmed': raise Conflict('Solo se ejecutan planes confirmados y aún no iniciados.')
        if as_utc(plan.expires_at)<=utc_now(): raise Conflict('La aprobación está fuera de vigencia. Prepara otro plan.')
        options,existing,fingerprint=await self.options(actor,scope.id)
        scope=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
        if fingerprint!=plan.fingerprint: raise Conflict('Cambió el inventario/perfil. Es necesaria otra propuesta y confirmación.')
        selected=[SsidProposal.model_validate(r['proposal']) for r in plan.rows if r['row_number'] in plan.selection]
        if not selected: raise Conflict('El plan no contiene una selección aprobada.')
        if plan.source=='mock':
            raise Conflict('Un plan simulado nunca se ejecuta en infraestructura real.')
        if not self.settings.unifi_write_enabled or self.settings.unifi_api_contract!='10.6.106':
            raise ServiceUnavailable('El ejecutor real está deshabilitado o el contrato no fue confirmado.')
        for proposal in selected:
            self.validate(proposal,options,existing)
            self.writer.profile(proposal.security_profile)
        # Exclusión durable por SSID/sitio, también entre ámbitos superpuestos.
        try:
            self.db.add_all([WifiWriteLease(resource_key=digest([scope.site_id,p.ssid.casefold()]),plan_id=plan_id) for p in selected])
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise Conflict('Otro trabajo posee el SSID o requiere conciliación manual.') from None
        claimed=self.db.execute(update(SsidPlan).where(SsidPlan.id==plan_id,SsidPlan.status=='confirmed',SsidPlan.expires_at>utc_now()).values(status='executing'),execution_options={'synchronize_session':False})
        if claimed.rowcount!=1:
            self.db.rollback(); raise Conflict('El plan fue tomado por otro ejecutor.')
        self.db.commit(); self.db.refresh(plan)
        results=[]
        scope_revision=digest([scope.site_id,scope.resources])
        def reauthorize():
            active=self.scope(actor,plan.scope_id,Permission.CHANGES_EXECUTE)
            if digest([active.site_id,active.resources])!=scope_revision:
                raise Conflict('Cambió el ámbito durante la ejecución.')
        for proposal in selected:
            try:
                # Reautorizar después de cada espera y antes de la siguiente escritura.
                reauthorize()
                external_id=await self.writer.create(scope.site_id,proposal,authorize=reauthorize)
                results.append({'ssid':proposal.ssid,'external_id':external_id,'status':'verifying'})
                plan.execution_results=list(results);self.db.commit()
                verified=await self.writer.verify(scope.site_id,external_id,proposal)
                results[-1]['status']='verified_configuration' if verified else 'uncertain'
                if not verified:
                    # No borrar/reintentar: otra configuración puede haber cambiado.
                    plan.status='uncertain';plan.execution_results=list(results);self.db.commit()
                    return self.read(plan)
            except Exception:
                # No guardar excepción/cuerpo externo: puede contener secretos del proveedor.
                results.append({'ssid':proposal.ssid,'status':'uncertain'})
                self.db.rollback()
                plan=self.db.get(SsidPlan,plan_id);plan.status='uncertain';plan.execution_results=list(results);self.db.commit()
                return self.read(plan)
        plan.status='completed';plan.execution_results=list(results)
        self.db.execute(delete(WifiWriteLease).where(WifiWriteLease.plan_id==plan_id))
        self.db.commit()
        return self.read(plan)
