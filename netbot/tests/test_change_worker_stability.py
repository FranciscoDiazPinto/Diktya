"""Regresiones de cola vencida y exclusión entre ejecución y conciliación."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.agents.models import AgentEvent
from app.agents.worker import ChangeWorker
from app.auth.models import AuthAuditEvent
from app.changes.csv_service import utc_now
from app.changes.execution import PlanBusy, plan_lock
from app.changes.models import DeviceRestartPlan, SsidPlan, SsidVlanChangePlan, WifiScopeGrant, WifiWriteLease
from app.changes.queue import confirmed_ids, interrupted_ids
from app.changes.ssid_schemas import SsidConfirm, SsidProposal
from tests.test_change_recovery import creator, ready, vlan_writer
from tests.test_device_restart import approve, device, service as restart_service
from tests.test_ssid_plans import execution_service, ssid_setup  # noqa: F401


def creation(db, x, writer):
    svc = execution_service(db, x, writer)
    async def prepare():
        plan = await svc.prepare(x.tech, SsidProposal(**x.proposal))
        return await svc.confirm(x.tech, plan.id, SsidConfirm(revision=plan.revision, row_numbers=[1]))
    return svc, asyncio.run(prepare())


def worker_for(db, svc, writer):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    return ChangeWorker(factory, svc.settings, getattr(svc, 'monitoring', None), writer=writer,
                        inventory=getattr(svc, 'inventory', None))


def test_twenty_expired_approvals_cannot_starve_new_work(db_session, ssid_setup):
    writer = creator(verify=AsyncMock(return_value=True))
    svc, valid = creation(db_session, ssid_setup, writer)
    template = db_session.get(SsidPlan, valid.id)
    values = {column.name: getattr(template, column.name) for column in SsidPlan.__table__.columns}
    now = utc_now()
    for index in range(20):
        db_session.add(SsidPlan(**{**values, 'id': f'expired-{index}',
                                  'confirmed_at': now-timedelta(hours=2, seconds=index),
                                  'expires_at': now-timedelta(hours=1)}))
    db_session.commit()
    worker = worker_for(db_session, svc, writer)
    asyncio.run(worker.run_cycle())
    asyncio.run(worker.run_cycle())
    db_session.expire_all()
    assert db_session.get(SsidPlan, valid.id).status == 'completed'
    assert db_session.scalar(select(func.count()).select_from(SsidPlan).where(SsidPlan.status == 'expired')) == 20
    assert db_session.scalar(select(func.count()).select_from(AuthAuditEvent)
                             .where(AuthAuditEvent.action == 'change.approval.expired')) == 20
    assert confirmed_ids(db_session, 'ssid') == []
    assert writer.create.await_count == 1


def test_revoked_approval_is_rejected_once_not_retried_forever(db_session, ssid_setup):
    writer = creator(verify=AsyncMock(return_value=True))
    svc, plan = creation(db_session, ssid_setup, writer)
    db_session.delete(db_session.get(WifiScopeGrant, (ssid_setup.scope, ssid_setup.tech.id)))
    db_session.commit()
    worker = worker_for(db_session, svc, writer)
    asyncio.run(worker.run_cycle())
    asyncio.run(worker.run_cycle())
    db_session.expire_all()
    assert db_session.get(SsidPlan, plan.id).status == 'rejected'
    assert db_session.scalar(select(func.count()).select_from(AgentEvent)
                             .where(AgentEvent.event_type == 'change.ssid.rejected')) == 1
    writer.create.assert_not_awaited()


def test_busy_approval_waits_without_being_rejected(db_session, ssid_setup):
    writer = creator(verify=AsyncMock(return_value=True))
    svc, plan = creation(db_session, ssid_setup, writer)
    worker = worker_for(db_session, svc, writer)
    with plan_lock(db_session, 'ssid', plan.id):
        asyncio.run(worker.run_cycle())
    db_session.expire_all()
    assert db_session.get(SsidPlan, plan.id).status == 'confirmed'
    writer.create.assert_not_awaited()
    assert db_session.scalar(select(func.count()).select_from(AgentEvent)) == 0
    asyncio.run(worker.run_cycle())
    assert writer.create.await_count == 1


@pytest.mark.parametrize('kind', ['ssid', 'vlan', 'restart'])
def test_active_execution_cannot_be_reconciled_even_when_old(db_session, ssid_setup, kind):
    # Pausar el proveedor después del claim durable simula una ejecución larga real.
    entered, release = asyncio.Event(), asyncio.Event()
    async def pause(*args, **kwargs):
        entered.set()
        await release.wait()
        return 'created-by-plan'
    if kind == 'ssid':
        writer = creator(verify=AsyncMock(return_value=True))
        writer.create.side_effect = pause
        svc, plan = creation(db_session, ssid_setup, writer)
        plan_id, model, execute, reconcile = plan.id, SsidPlan, svc.execute, svc.reconcile
    elif kind == 'vlan':
        writer = vlan_writer(verify=True, observed='network-30')
        writer.update_vlan.side_effect = pause
        svc, plan = ready(db_session, ssid_setup, writer)
        plan_id, model, execute, reconcile = plan['id'], SsidVlanChangePlan, svc.execute_vlan_change, svc.reconcile_vlan_change
    else:
        svc, writer = restart_service(db_session, [device(), device(), device(uptime=12)])
        writer.restart.side_effect = pause
        plan = approve(svc, ssid_setup.tech, ssid_setup.scope)
        plan_id, model, execute, reconcile = plan['id'], DeviceRestartPlan, svc.execute, svc.reconcile
    row = db_session.get(model, plan_id)
    row.confirmed_at = utc_now() - timedelta(minutes=12)
    db_session.commit()
    worker = worker_for(db_session, svc, writer)

    async def run():
        task = asyncio.create_task(execute(plan_id))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            db_session.refresh(row)
            # Una aprobación antigua no hace vieja a una ejecución recién iniciada.
            assert row.execution_started_at is not None
            assert interrupted_ids(db_session, kind, utc_now()-timedelta(seconds=60)) == []
            row.execution_started_at = utc_now()-timedelta(hours=2)
            db_session.commit()
            assert interrupted_ids(db_session, kind, utc_now()-timedelta(seconds=60)) == [plan_id]
            with pytest.raises(PlanBusy):
                await reconcile(plan_id)  # misma entrada que usa la API administrativa
            await worker.run_cycle()  # otro worker tampoco puede conciliar ni repetirlo
            db_session.refresh(row)
            assert row.status == 'executing'
            assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 1
            assert not task.done()
            release.set()
            result = await asyncio.wait_for(task, timeout=3)
            assert (result.status if kind == 'ssid' else result['status']) == 'completed'
            assert db_session.scalar(select(func.count()).select_from(WifiWriteLease)) == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
