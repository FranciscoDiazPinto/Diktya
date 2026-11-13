"""Conciliación de trabajos detenidos (executing/uncertain). Solo lectura sobre la red.

Se usa desde el worker y desde la API administrativa. Nunca repite una escritura: compara
el estado remoto con el plan y registra el resultado comprobado.
"""
from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.errors import NotFound

KINDS = ('ssid', 'vlan', 'restart')


async def reconcile_plan(actor: User, kind: str, plan_id: str, plans, restarts):
    require_user_permission(plans.db, actor, Permission.NETWORKS_MANAGE)
    if kind == 'ssid':
        return await plans.reconcile(plan_id)
    if kind == 'vlan':
        return await plans.reconcile_vlan_change(plan_id)
    if kind == 'restart':
        return await restarts.reconcile(plan_id)
    raise NotFound('Tipo de trabajo desconocido.')
