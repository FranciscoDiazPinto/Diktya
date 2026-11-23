from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.changes.models import VlanReservation
from app.changes.schemas import VlanReservationCreate
from app.changes.service import (
    ReservationAlreadyReleased, VlanReservationService, VlanConflict,
    find_reserved_vlan, mark_assigned,
)
from app.monitoring.providers.mock import MockMonitoringProvider
from app.monitoring.service import MonitoringService


def data(tag=20):
    return VlanReservationCreate(parent_interface="igc1", tag=tag,
                                 event_name=" Feria ", purpose=" Invitados ", ssid=" Evento ")


@pytest.mark.asyncio
async def test_reservation_lifecycle_and_reuse(db_session, admin_user):
    service = VlanReservationService(MonitoringService(MockMonitoringProvider()), db_session)
    row = await service.create(data(), admin_user)
    assert row.requested_by_id == admin_user.id
    assert row.event_name == "Feria" and row.purpose == "Invitados"
    assert [item.tag for item in await service.available_vlans()] == [30]
    released = service.release(row.id, admin_user)
    assert released.status == "released" and released.released_by_id == admin_user.id
    assert released.released_at is not None
    assert [item.tag for item in await service.available_vlans()] == [20, 30]
    with pytest.raises(ReservationAlreadyReleased):
        service.release(row.id, admin_user)


@pytest.mark.asyncio
async def test_reject_uninventoried_and_duplicate_active_vlan(db_session, admin_user):
    service = VlanReservationService(MonitoringService(MockMonitoringProvider()), db_session)
    with pytest.raises(VlanConflict):
        await service.create(data(99), admin_user)
    await service.create(data(), admin_user)
    with pytest.raises(VlanConflict):
        await service.create(data(), admin_user)


def test_active_partial_unique_index_allows_released_history(db_session, admin_user):
    base = dict(parent_interface="igc1", tag=20, interface_name="vlan01", event_name="E",
                purpose="P", ssid="S", requested_by_id=admin_user.id)
    db_session.add_all([VlanReservation(**base, status="reserved", created_at=__import__('datetime').datetime.now()),
                        VlanReservation(**base, status="reserved", created_at=__import__('datetime').datetime.now())])
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    db_session.add(VlanReservation(**base, status="released", created_at=__import__('datetime').datetime.now()))
    db_session.commit()


def test_request_schema_trims_and_forbids_actor_fields():
    from pydantic import ValidationError
    clean = data()
    assert clean.event_name == "Feria" and clean.ssid == "Evento"
    with pytest.raises(ValidationError):
        VlanReservationCreate(**data().model_dump(), requested_by_id=99)


@pytest.mark.asyncio
async def test_assignment_uses_exact_reservation_and_never_a_replacement(db_session, admin_user):
    service = VlanReservationService(MonitoringService(MockMonitoringProvider()), db_session)
    original = await service.create(data(), admin_user)
    match = dict(parent_interface="igc1", tag=20, event_name="Feria",
                 ssid="Evento", actor_id=admin_user.id, now=datetime.now(timezone.utc))
    for field, value in (("event_name", "Otra feria"), ("ssid", "Otro SSID"),
                         ("actor_id", admin_user.id + 1)):
        assert find_reserved_vlan(db_session, **(match | {field: value})) is None
    assert find_reserved_vlan(db_session, **match) == original.id

    assert service.release(original.id, admin_user).status == "released"
    replacement = await service.create(data(), admin_user)
    assert not mark_assigned(db_session, original.id, match["now"])
    assert find_reserved_vlan(db_session, **match) == replacement.id
    assert mark_assigned(db_session, replacement.id, match["now"])
    db_session.commit()
    assert db_session.get(VlanReservation, replacement.id).status == "assigned"


@pytest.mark.asyncio
async def test_expiration_is_audited_once_and_visible_only_to_its_requester(db_session, admin_user):
    from datetime import timedelta
    from sqlalchemy import func, select
    from app.auth.models import AuthAuditEvent
    from app.changes.service import expire_due

    service = VlanReservationService(MonitoringService(MockMonitoringProvider()), db_session)
    row = await service.create(data(), admin_user)
    reservation = db_session.get(VlanReservation, row.id)
    reservation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    other = User(email='other-admin@example.com', hashed_password='synthetic', roles=admin_user.roles)
    db_session.add(other)
    db_session.commit()

    assert service.list_my_expired(other, 25, 0) == []
    assert [notice.id for notice in service.list_my_expired(admin_user, 25, 0)] == [row.id]
    assert expire_due(db_session, datetime.now(timezone.utc)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuthAuditEvent).where(
        AuthAuditEvent.action == 'vlan.reservation.expired', AuthAuditEvent.target_id == admin_user.id,
    )) == 1


@pytest.mark.asyncio
async def test_active_execution_protects_reservation_until_resolution(db_session, admin_user):
    from datetime import timedelta
    from app.changes.service import clear_reservation_hold, expire_due, hold_reservation
    from app.core.errors import Conflict

    service = VlanReservationService(MonitoringService(MockMonitoringProvider()), db_session, ttl_hours=1)
    row = await service.create(data(), admin_user)
    now = datetime.now(timezone.utc)
    hold_reservation(db_session, row.id, 'active-plan', now)
    db_session.commit()

    later = now + timedelta(hours=2)
    assert expire_due(db_session, later) == 0
    with pytest.raises(Conflict, match='protegida'):
        service.release(row.id, admin_user)
    clear_reservation_hold(db_session, row.id, 'other-plan')
    assert expire_due(db_session, later) == 0
    clear_reservation_hold(db_session, row.id, 'active-plan')
    assert expire_due(db_session, later) == 1
