"""HU017/HU018: orquestador, aislamiento de fallas, trazas por agente y worker durable."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.events import Event, record
from app.agents.models import AgentEvent, AgentState
from app.agents.orchestrator import FAILURES_BEFORE_INCIDENT, Orchestrator, agent_events, agent_status
from app.agents.worker import ChangeWorker
from app.auth.models import Role, User
from app.core.config import Settings
from app.core.database import Base
from app.core.errors import AccessDenied
from app.model_registry import register_models
from app.tickets.models import Ticket

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def lab():
    register_models()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    roles = {name: Role(name=name) for name in ("admin", "tecnico", "visor")}
    db.add_all(roles.values())
    users = {name: User(email=f"{name}@example.com", hashed_password="x", roles=[role]) for name, role in roles.items()}
    db.add_all(users.values())
    db.commit()
    clock = {"now": T0}
    settings = Settings(_env_file=None)
    return SimpleNamespace(factory=factory, db=db, users=users, clock=clock, settings=settings,
                           orchestrator=Orchestrator(factory, settings, clock=lambda: clock["now"]))


def test_failing_agent_is_isolated_traced_and_escalated_once(lab):
    calls = {"good": 0}

    async def broken():
        raise RuntimeError("clave-secreta-no-debe-guardarse")

    async def good():
        calls["good"] += 1

    lab.orchestrator.register("monitoring", broken, 1)
    lab.orchestrator.register("tickets", good, 1)
    with pytest.raises(ValueError):
        lab.orchestrator.register("tickets", good, 1)

    async def run():
        for _ in range(FAILURES_BEFORE_INCIDENT + 2):
            assert await lab.orchestrator.run_once("monitoring") is False
            assert await lab.orchestrator.run_once("tickets") is True
            lab.clock["now"] += timedelta(seconds=30)
    asyncio.run(run())
    assert calls["good"] == FAILURES_BEFORE_INCIDENT + 2  # los demás agentes siguieron operando
    status = {row["agent_id"]: row for row in agent_status(lab.db, lab.users["visor"], now=lab.clock["now"])}
    assert status["monitoring"]["status"] == "failed" and status["monitoring"]["consecutive_failures"] == 5
    assert status["monitoring"]["last_error"] == "RuntimeError"  # el tipo, nunca el mensaje
    assert status["tickets"]["status"] == "ok" and status["tickets"]["last_success_at"] is not None
    tickets = list(lab.db.scalars(select(Ticket)))
    assert len(tickets) == 1 and tickets[0].incident_type == "agent_failed"
    assert "secreta" not in str([(e.detail, e.event_type) for e in lab.db.scalars(select(AgentEvent))])


def test_recovery_is_recorded_and_stalled_agents_are_visible(lab):
    state = {"fail": True}

    async def flaky():
        if state["fail"]:
            raise OSError("sin red")

    lab.orchestrator.register("monitoring", flaky, 30)
    asyncio.run(lab.orchestrator.run_once("monitoring"))
    state["fail"] = False
    asyncio.run(lab.orchestrator.run_once("monitoring"))
    kinds = list(lab.db.scalars(select(AgentEvent.event_type).order_by(AgentEvent.id)))
    assert kinds == ["agent.cycle_failed", "agent.recovered"]
    assert agent_status(lab.db, lab.users["admin"], now=T0)[0]["status"] == "ok"
    later = T0 + timedelta(minutes=10)
    assert agent_status(lab.db, lab.users["admin"], now=later)[0]["status"] == "stalled"


def test_healthy_cycles_do_not_write_state_on_every_run(lab):
    async def noop():
        return None

    lab.orchestrator.register("monitoring", noop, 1)

    async def run():
        for _ in range(5):
            await lab.orchestrator.run_once("monitoring")
            lab.clock["now"] += timedelta(seconds=1)
    asyncio.run(run())
    assert lab.db.scalar(select(AgentState.runs)) == 1


def test_event_contract_deduplicates_and_requires_a_known_agent(lab):
    event = Event(agent_id="changes", event_type="change.vlan.executed", correlation_id="change:vlan:1",
                  resource_type="vlan_plan", resource_id="1", detail="completed")
    assert record(lab.db, event) is True
    lab.db.commit()
    assert record(lab.db, event) is False
    with pytest.raises(ValueError):
        Event(agent_id="desconocido", event_type="x", correlation_id="y")
    traces = agent_events(lab.db, lab.users["admin"], correlation_id="change:vlan:1")
    assert [t["agent_id"] for t in traces] == ["changes"]
    with pytest.raises(AccessDenied):
        agent_events(lab.db, lab.users["tecnico"])
    with pytest.raises(AccessDenied):
        agent_status(lab.db, lab.users["tecnico"])


def test_worker_executes_each_approval_once_and_traces_rejections(lab, monkeypatch):
    from app.agents import worker as module
    from app.core.errors import Conflict

    executed = []
    monkeypatch.setattr(module, "confirmed_ids", lambda db, kind, limit=20: {"vlan": ["plan-1", "plan-2"]}.get(kind, []))
    monkeypatch.setattr(module, "interrupted_ids", lambda db, kind, before, limit=20: [])

    async def execute(plan_id):
        executed.append(plan_id)
        if plan_id == "plan-2":
            raise Conflict("Cambió el inventario desde la confirmación.")
        return {"status": "completed"}

    worker = ChangeWorker(lab.factory, Settings(_env_file=None, unifi_write_enabled=True), monitoring=None)
    monkeypatch.setattr(worker, "_services", lambda db: (
        SimpleNamespace(execute=AsyncMock(), execute_vlan_change=execute, reconcile=AsyncMock(), reconcile_vlan_change=AsyncMock()),
        SimpleNamespace(execute=AsyncMock(), reconcile=AsyncMock())))
    asyncio.run(worker.run_cycle())
    assert executed == ["plan-1", "plan-2"]
    rows = lab.db.execute(select(AgentEvent.event_type, AgentEvent.outcome, AgentEvent.correlation_id)
                          .order_by(AgentEvent.id)).all()
    assert rows == [("change.vlan.executed", "success", "change:vlan:plan-1"),
                    ("change.vlan.rejected", "failure", "change:vlan:plan-2")]


def test_worker_never_touches_the_network_when_writes_are_disabled(lab, monkeypatch):
    from app.agents import worker as module
    monkeypatch.setattr(module, "confirmed_ids", lambda *a, **k: pytest.fail("no debe consultar trabajos"))
    worker = ChangeWorker(lab.factory, Settings(_env_file=None, unifi_write_enabled=False), monitoring=None)
    asyncio.run(worker.run_cycle())
    assert lab.db.scalar(select(func.count()).select_from(AgentEvent)) == 0


def test_agent_status_api_requires_monitoring_permission(client, admin_user, viewer_user, login):
    _, admin = login("admin@example.com", "admin-password")
    _, viewer = login("viewer@example.com", "viewer-password")
    assert client.get("/api/v1/agents/status").status_code == 401
    assert client.get("/api/v1/agents/status", headers=viewer).status_code == 200
    assert client.get("/api/v1/agents/events", headers=viewer).status_code == 403
    assert client.get("/api/v1/agents/events", headers=admin).status_code == 200


def test_changes_cli_keeps_working_without_loading_the_http_application():
    import os
    import subprocess
    import sys
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import app.agents.cli, app.changes.cli; "
                                "assert 'app.main' not in sys.modules and 'fastapi' not in sys.modules"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        env=dict(os.environ, DATABASE_URL="sqlite://", MONITORING_PROVIDER="mock"))
    assert result.returncode == 0, result.stderr
