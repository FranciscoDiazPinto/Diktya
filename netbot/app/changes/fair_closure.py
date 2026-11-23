"""Inventario local previo al cierre de cambios de un ámbito de feria."""
from hashlib import sha256
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.access import require_user_permission
from app.auth.audit import record_event
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.errors import Conflict, NotFound

from .csv_service import utc_now
from .models import DeviceRestartPlan, SsidPlan, SsidVlanBatchPlan, SsidVlanChangePlan, VlanReservation, WifiScope

PLAN_TYPES = (
    ('ssid', SsidPlan),
    ('vlan', SsidVlanChangePlan),
    ('vlan_batch', SsidVlanBatchPlan),
    ('restart', DeviceRestartPlan),
)
PENDING = {'preview', 'confirmed'}
IN_PROGRESS = {'executing', 'uncertain', 'rollback_failed'}
REVIEW = {'completed', 'partial', 'unverified'}


def _ssid_reservation_ids(rows):
    return {row['reservation_id'] for row in rows if row.get('reservation_id') is not None}


def require_open_scope(db: Session, scope_id: int) -> None:
    """Serializa escrituras locales de planes con la confirmación del cierre."""
    changed = db.execute(update(WifiScope).where(
        WifiScope.id == scope_id, WifiScope.accepts_changes.is_(True),
    ).values(accepts_changes=True), execution_options={'synchronize_session': False})
    if changed.rowcount != 1:
        raise Conflict('El ámbito de feria ya no acepta cambios.')


def preview_fair_closure(db: Session, actor: User, scope_id: int) -> dict:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    scope = db.get(WifiScope, scope_id, populate_existing=True)
    if scope is None:
        raise NotFound('Ámbito de feria no encontrado.')

    pending = []
    blockers = []
    review = []
    reservation_ids = set()
    protected_ids = set()
    for kind, model in PLAN_TYPES:
        plans = db.scalars(select(model).where(model.scope_id == scope_id).order_by(model.id))
        for plan in plans:
            entry = {'kind': kind, 'id': plan.id, 'status': plan.status}
            if plan.status in PENDING and (kind != 'vlan_batch' or plan.status == 'preview'):
                pending.append(entry)
            elif plan.status in IN_PROGRESS:
                blockers.append(entry)
            elif plan.status in REVIEW:
                review.append(entry)

            if kind == 'ssid':
                ids = _ssid_reservation_ids(plan.rows)
                if plan.status == 'partial':
                    applied = {row['ssid'] for row in plan.execution_results
                               if row['status'] == 'verified_configuration'}
                    protected_ids.update(_ssid_reservation_ids(
                        row for row in plan.rows if (row.get('proposal') or {}).get('ssid') in applied
                    ))
            elif kind == 'vlan' and plan.reservation_id is not None:
                ids = {plan.reservation_id}
            else:
                continue
            reservation_ids.update(ids)
            if plan.status in IN_PROGRESS or plan.status in REVIEW - {'partial'}:
                protected_ids.update(ids)

    if reservation_ids:
        protected_ids.update(db.scalars(select(SsidVlanChangePlan.reservation_id).where(
            SsidVlanChangePlan.scope_id != scope_id,
            SsidVlanChangePlan.reservation_id.in_(reservation_ids),
        )))
        for rows in db.scalars(select(SsidPlan.rows).where(SsidPlan.scope_id != scope_id)):
            protected_ids.update(_ssid_reservation_ids(rows) & reservation_ids)

    reservations = db.execute(select(VlanReservation.id, VlanReservation.status, VlanReservation.held_by_plan_id).where(
        VlanReservation.id.in_(reservation_ids),
        VlanReservation.status.in_(('reserved', 'assigned')),
    ).order_by(VlanReservation.id))
    inventory = {
        'scope_id': scope.id,
        'accepts_changes': scope.accepts_changes,
        'event_name': scope.resources['event_name'],
        'pending': pending,
        'blockers': blockers,
        'review': review,
        'linked_reservations': [
            {'id': reservation_id, 'status': status,
             'releasable': status == 'reserved' and hold is None and reservation_id not in protected_ids}
            for reservation_id, status, hold in reservations
        ],
    }
    revision = sha256(json.dumps([actor.id, inventory], sort_keys=True).encode()).hexdigest()
    return {**inventory, 'revision': revision}


def confirm_fair_closure(db: Session, actor: User, scope_id: int, revision: str) -> dict:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    locked = db.execute(update(WifiScope).where(WifiScope.id == scope_id).values(
        accepts_changes=WifiScope.accepts_changes,
    ), execution_options={'synchronize_session': False})
    if locked.rowcount != 1:
        raise NotFound('Ámbito de feria no encontrado.')

    preview = preview_fair_closure(db, actor, scope_id)
    if preview['revision'] != revision:
        db.rollback()
        raise Conflict('La vista previa cambió. Revísala antes de confirmar el cierre.')
    releasable = [row['id'] for row in preview['linked_reservations'] if row['releasable']]
    if releasable:
        db.execute(update(VlanReservation).where(VlanReservation.id.in_(releasable)).values(
            status=VlanReservation.status,
        ), execution_options={'synchronize_session': False})
        if preview_fair_closure(db, actor, scope_id)['revision'] != revision:
            db.rollback()
            raise Conflict('Las reservas cambiaron. Revisa la vista previa antes de confirmar.')
    if not preview['accepts_changes'] and not releasable:
        db.commit()
        return preview

    scope = db.get(WifiScope, scope_id)
    scope.accepts_changes = False
    cancelled = []
    for kind, model in PLAN_TYPES:
        ids = [entry['id'] for entry in preview['pending'] if entry['kind'] == kind]
        if not ids:
            continue
        changed = db.execute(update(model).where(
            model.scope_id == scope_id, model.id.in_(ids), model.status.in_(PENDING),
        ).values(status='cancelled'), execution_options={'synchronize_session': False})
        if changed.rowcount != len(ids):
            db.rollback()
            raise Conflict('Un plan cambió durante la confirmación. Revisa la vista previa.')
        cancelled.extend(ids)
    if releasable:
        db.execute(update(VlanReservation).where(
            VlanReservation.id.in_(releasable), VlanReservation.status == 'reserved',
            VlanReservation.held_by_plan_id.is_(None),
        ).values(status='released', released_at=utc_now(), released_by_id=actor.id),
            execution_options={'synchronize_session': False})
    record_event(db, 'wifi.fair_closure.confirmed', actor_id=actor.id,
                 details={'scope_id': scope_id, 'cancelled_plan_ids': cancelled,
                          'released_reservation_ids': releasable,
                          'revision': revision})
    db.commit()
    return preview_fair_closure(db, actor, scope_id)
