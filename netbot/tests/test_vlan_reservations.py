import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.changes.models import VlanReservation
from app.changes.schemas import VlanReservationCreate
from app.changes.service import ReservationAlreadyReleased, VlanReservationService, VlanConflict
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
