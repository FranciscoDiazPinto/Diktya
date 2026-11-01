"""Épica 005: incidentes, criticidad, notificaciones, seguimiento y permisos."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.core.config import Settings
from app.core.database import Base
from app.model_registry import register_models
from app.monitoring.alerts import AlertCondition, Incident, sync_alerts
from app.monitoring.models import MonitoringAlert
from app.monitoring.schemas import AlertSeverity
from app.tickets.agent import TicketAgent, open_incident
from app.tickets.criticality import attention_minutes, classify, criticality_rules
from app.tickets.models import Notification, Ticket, TicketEvent

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
BASE = "/api/v1/tickets"


def settings(**extra):
    return Settings(_env_file=None, **extra)


class Lab:
    def __init__(self, **extra):
        register_models()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.settings = settings(**extra)
        self.now = T0
        self.sent = []
        self.fail_mail = False
        self.db = self.factory()
        roles = {name: Role(name=name) for name in ("admin", "tecnico", "cliente", "visor")}
        self.db.add_all(roles.values())
        self.tech = User(email="tech@example.com", hashed_password="x", roles=[roles["tecnico"]])
        self.admin = User(email="admin@example.com", hashed_password="x", roles=[roles["admin"]])
        self.off = User(email="off@example.com", hashed_password="x", roles=[roles["tecnico"]], is_active=False)
        self.client = User(email="c@example.com", hashed_password="x", roles=[roles["cliente"]])
        self.db.add_all([self.tech, self.admin, self.off, self.client])
        self.db.commit()
        self.agent = TicketAgent(self.factory, self.settings, self.mail, clock=lambda: self.now)

    def mail(self, to, subject, body):
        if self.fail_mail:
            raise OSError("smtp caído")
        self.sent.append((to, subject, body))

    def alert(self, key="device:1:offline", resolved=False, message="AP Hall está fuera de línea."):
        sync_alerts(self.db, source="mock", categories={"device"}, now=self.now, conditions=[] if resolved else [
            AlertCondition(key, "device", AlertSeverity.CRITICAL, message, None, "AP Hall")])
        self.db.commit()

    async def cycle(self, advance=30):
        self.now += timedelta(seconds=advance)
        await self.agent.run_cycle()
        self.db.expire_all()

    def tickets(self):
        return self.db.scalars(select(Ticket).order_by(Ticket.id)).all()

    def rows(self, **filters):
        return self.db.scalars(select(Notification).filter_by(**filters).order_by(Notification.id)).all()


@pytest.fixture()
def lab():
    instance = Lab(smtp_host="smtp.test", ticket_attention_minutes_json='{"alta": 10}')
    yield instance
    instance.db.close()


@pytest.mark.parametrize("incident, device, affected, expected, review", [
    ("device_offline", "ap", 1, "alta", False),
    ("device_offline", "gateway", 1, "critica", False),
    ("device_offline", "firewall", 1, "critica", False),
    ("device_offline", "ap", 3, "critica", False),
    ("device_degraded", "ap", 1, "media", False),
    ("device_degraded", "ap", 3, "alta", False),
    ("device_missing", "switch", 1, "media", False),
    ("source_unavailable", None, 1, "critica", False),
    ("verification_failed", None, 1, "alta", False),
    ("rollback_failed", None, 1, "critica", False),
    ("algo_desconocido", None, 1, "media", True),
])
def test_criticality_by_incident_type(incident, device, affected, expected, review):
    assert classify(incident, device_type=device, affected=affected, settings=settings()) == (expected, review)


def test_rules_and_attention_times_are_configurable():
    custom = settings(ticket_criticality_rules_json='{"device_degraded": "baja"}', ticket_attention_minutes_json='{"critica": 5}')
    assert classify("device_degraded", device_type="ap", affected=1, settings=custom) == ("baja", False)
    assert attention_minutes(custom)["critica"] == 5
    with pytest.raises(ValueError):
        criticality_rules(settings(ticket_criticality_rules_json='{"device_offline": "urgente"}'))
    with pytest.raises(ValueError):
        attention_minutes(settings(ticket_attention_minutes_json='{"critica": 0}'))
    with pytest.raises(ValueError):
        TicketAgent(lambda: None, settings(ticket_criticality_rules_json="no-json"), None)


async def test_alert_creates_one_ticket_with_device_alert_and_evidence(lab):
    lab.alert()
    await lab.cycle()
    await lab.cycle()
    tickets = lab.tickets()
    assert len(tickets) == 1
    ticket = tickets[0]
    alert = lab.db.scalar(select(MonitoringAlert))
    assert (ticket.source, ticket.criticality, ticket.alert_id, ticket.device_name) == ("incident", "alta", alert.id, "AP Hall")
    assert ticket.evidence["alert_id"] == alert.id and ticket.evidence["simulated"] is True
    assert ticket.summary and ticket.description and ticket.incident_type == "device_offline"
    assert lab.now - T0 <= timedelta(minutes=2)


async def test_same_incident_links_events_instead_of_duplicating(lab):
    lab.alert()
    await lab.cycle()
    lab.alert(resolved=True)
    await lab.cycle()
    assert lab.tickets()[0].status == "resolved"
    lab.alert()  # la misma condición vuelve: alerta nueva, mismo incidente
    await lab.cycle()
    tickets = lab.tickets()
    assert len(tickets) == 1 and tickets[0].status == "open"
    assert tickets[0].alert_id == lab.db.scalar(select(func.max(MonitoringAlert.id)))
    notes = [e.note for e in lab.db.scalars(select(TicketEvent))]
    assert any("volvió a ocurrir" in note for note in notes)


async def test_closed_incident_opens_a_new_ticket_on_recurrence(lab):
    lab.alert()
    await lab.cycle()
    ticket = lab.tickets()[0]
    ticket.status = "closed"
    lab.db.commit()
    lab.alert(resolved=True)
    lab.alert()
    await lab.cycle()
    assert [t.status for t in lab.tickets()] == ["closed", "open"]


async def test_unclassifiable_incident_is_media_and_flagged(lab):
    ticket = open_incident(lab.db, Incident(key="x:1", incident_type="nuevo_tipo", message="Raro", detected_at=T0, source="mock"),
                           lab.settings, T0)
    lab.db.commit()
    assert (ticket.criticality, ticket.needs_review) == ("media", True)


async def test_incidents_outside_monitoring_are_idempotent(lab):
    incident = Incident(key="change:9:rollback", incident_type="rollback_failed", message="Falló el rollback", detected_at=T0, source="mock")
    first = open_incident(lab.db, incident, lab.settings, T0)
    second = open_incident(lab.db, incident, lab.settings, T0)
    lab.db.commit()
    assert first.id == second.id and first.criticality == "critica"
    await lab.cycle()
    assert lab.tickets()[0].status == "open"  # sin alerta asociada no se autorresuelve


async def test_notifies_active_staff_only_and_records_delivery(lab):
    lab.alert()
    await lab.cycle()
    in_app = lab.rows(channel="in_app")
    assert {n.user_id for n in in_app} == {lab.tech.id, lab.admin.id}
    assert all(n.highlighted and n.status == "sent" and n.sent_at for n in in_app)
    assert "[Alta]" in in_app[0].title and "AP Hall" in in_app[0].body and f"#ticket-{lab.tickets()[0].id}" in in_app[0].link
    assert sorted(to for to, _, _ in lab.sent) == ["admin@example.com", "tech@example.com"]
    assert all(n.status == "sent" and n.attempts == 1 for n in lab.rows(channel="email"))


async def test_email_failure_keeps_in_app_and_retries_with_backoff(lab):
    lab.fail_mail = True
    lab.alert()
    await lab.cycle()
    assert len(lab.rows(channel="in_app")) == 2
    row = lab.rows(channel="email")[0]
    assert (row.status, row.attempts, row.last_error) == ("pending", 1, "OSError")
    await lab.cycle(advance=5)  # aún no vence el reintento
    lab.db.refresh(row)
    assert row.attempts == 1
    lab.fail_mail = False
    await lab.cycle(advance=61)
    lab.db.refresh(row)
    assert (row.status, row.attempts, row.last_error) == ("sent", 2, None)


async def test_email_gives_up_after_max_attempts(lab):
    lab.fail_mail = True
    lab.alert()
    for _ in range(6):
        await lab.cycle(advance=4000)
    original = lab.rows(channel="email", event="created")
    assert {n.status for n in original} == {"failed"}
    assert all(n.attempts == lab.settings.notification_email_max_attempts for n in original)


async def test_pending_email_is_cancelled_when_user_is_deactivated(lab):
    lab.fail_mail = True
    lab.alert()
    await lab.cycle()
    lab.tech.is_active = False
    lab.db.commit()
    lab.fail_mail = False
    await lab.cycle(advance=61)
    statuses = {n.user_id: n.status for n in lab.rows(channel="email")}
    assert statuses[lab.tech.id] == "cancelled" and statuses[lab.admin.id] == "sent"


async def test_without_smtp_only_in_app_is_recorded():
    lab = Lab()
    lab.agent = TicketAgent(lab.factory, lab.settings, None, clock=lambda: lab.now)
    lab.alert()
    await lab.cycle()
    assert len(lab.rows(channel="in_app")) == 2 and lab.rows(channel="email") == []
    lab.db.close()


async def test_overdue_ticket_is_escalated_and_renotified(lab):
    lab.alert()
    await lab.cycle()
    before = len(lab.rows(channel="in_app"))
    await lab.cycle(advance=9 * 60)
    assert lab.tickets()[0].criticality == "alta"
    await lab.cycle(advance=2 * 60)
    ticket = lab.tickets()[0]
    assert (ticket.criticality, ticket.escalations) == ("critica", 1)
    assert len(lab.rows(channel="in_app")) == before + 2
    assert {n.event for n in lab.rows(channel="in_app")} == {"created", "escalated"}


async def test_attended_ticket_is_not_escalated(lab):
    lab.alert()
    await lab.cycle()
    ticket = lab.tickets()[0]
    ticket.assignee_id = lab.tech.id
    lab.db.commit()
    await lab.cycle(advance=3600)
    assert lab.tickets()[0].escalations == 0


async def test_normalized_condition_resolves_and_waits_for_closure(lab):
    lab.alert()
    await lab.cycle()
    lab.alert(resolved=True)
    await lab.cycle()
    ticket = lab.tickets()[0]
    assert ticket.status == "resolved" and "normalizó" in ticket.resolution
    await lab.cycle()
    assert lab.tickets()[0].status == "resolved"  # el cierre sigue siendo de un técnico


async def test_failed_step_does_not_stop_the_others(lab, caplog):
    async def broken():
        raise RuntimeError("bug")

    lab.agent.sync_incidents = broken
    lab.alert()
    await lab.agent.run_cycle()
    assert "broken" in caplog.text
    assert lab.rows(channel="in_app") == []


# --- API ---


@pytest.fixture()
def team(client, db_session, login, admin_user, viewer_user):
    role = db_session.query(Role).filter_by(name="tecnico").one()
    db_session.add(User(email="tech@example.com", hashed_password=hash_password("tech-password"), roles=[role]))
    role = db_session.query(Role).filter_by(name="cliente").one()
    db_session.add(User(email="client@example.com", hashed_password=hash_password("client-password"), roles=[role]))
    db_session.commit()
    return {"admin": login("admin@example.com", "admin-password")[1], "visor": login("viewer@example.com", "viewer-password")[1],
            "tech": login("tech@example.com", "tech-password")[1], "client": login("client@example.com", "client-password")[1]}


def manual(client, headers, key=None, **extra):
    return client.post(f"{BASE}/manual", headers=headers, json={
        "summary": "Revisar AP", "description": "Sin señal", "criticality": "alta", "request_key": key or str(uuid4()), **extra})


def test_manual_ticket_permissions_and_idempotency(client, team):
    assert manual(client, team["client"]).status_code == 403
    assert manual(client, team["visor"]).status_code == 403
    key = str(uuid4())
    first = manual(client, team["tech"], key)
    assert first.status_code == 201, first.text
    assert (first.json()["source"], first.json()["criticality"]) == ("manual", "alta")
    assert manual(client, team["tech"], key).json()["id"] == first.json()["id"]
    assert manual(client, team["admin"], device_id=99999).status_code == 400


def test_infrastructure_tickets_visibility_is_role_based(client, team):
    ticket = manual(client, team["tech"]).json()
    path = f"{BASE}/{ticket['id']}"
    assert client.get(path, headers=team["visor"]).status_code == 200
    assert client.get(path, headers=team["client"]).status_code == 404
    assert client.get(BASE, headers=team["client"]).json() == []
    payload = {"status": "in_progress", "version": 0, "note": "Reviso"}
    assert client.patch(path, json=payload, headers=team["visor"]).status_code == 403
    assert client.post(f"{path}/assign", json={"version": 0}, headers=team["visor"]).status_code == 403
    assert client.post(f"{path}/comments", json={"note": "x"}, headers=team["visor"]).status_code == 403


def test_assign_comment_filters_and_history(client, team):
    ticket = manual(client, team["tech"]).json()
    manual(client, team["tech"], criticality="baja")
    path = f"{BASE}/{ticket['id']}"
    assigned = client.post(f"{path}/assign", json={"version": 0}, headers=team["tech"])
    assert assigned.status_code == 200 and assigned.json()["assignee_id"]
    assert client.post(f"{path}/assign", json={"version": 0}, headers=team["tech"]).status_code == 409
    me = assigned.json()["assignee_id"]
    assert client.post(f"{path}/comments", json={"note": "Voy en camino"}, headers=team["tech"]).status_code == 201
    assert [t["id"] for t in client.get(BASE, params={"assignee_id": me}, headers=team["tech"]).json()] == [ticket["id"]]
    assert len(client.get(BASE, params={"criticality": "baja"}, headers=team["tech"]).json()) == 1
    assert len(client.get(BASE, params={"status": "open"}, headers=team["tech"]).json()) == 2
    detail = client.get(path, headers=team["tech"]).json()
    assert [e["kind"] for e in detail["events"]] == ["status", "assignment", "comment"]


def test_adjusting_criticality_clears_review_and_needs_reason(client, db_session, team):
    ticket = manual(client, team["tech"]).json()
    db_session.get(Ticket, ticket["id"]).needs_review = True
    db_session.commit()
    path = f"{BASE}/{ticket['id']}/criticality"
    assert client.patch(path, json={"criticality": "critica", "version": 0}, headers=team["tech"]).status_code == 422
    changed = client.patch(path, json={"criticality": "critica", "version": 0, "note": "Afecta al escenario"}, headers=team["tech"])
    assert changed.status_code == 200
    assert (changed.json()["criticality"], changed.json()["needs_review"]) == ("critica", False)


def test_state_transitions_and_closure_reason(client, team):
    ticket = manual(client, team["tech"]).json()
    path = f"{BASE}/{ticket['id']}"
    step = lambda status, version, note="Motivo suficiente": client.patch(path, json={"status": status, "version": version, "note": note}, headers=team["tech"])
    assert step("closed", 0).status_code == 409  # inválida: abierto no pasa a cerrado
    assert step("in_progress", 0).status_code == 200
    assert step("resolved", 1).status_code == 200
    assert step("closed", 2, "ok").status_code == 400  # sin motivo real
    closed = step("closed", 2, "Se reemplazó el AP")
    assert (closed.status_code, closed.json()["resolution"]) == (200, "Se reemplazó el AP")
    detail = client.get(path, headers=team["tech"]).json()
    assert [e["status"] for e in detail["events"]] == ["open", "in_progress", "resolved", "closed"]


def test_notifications_inbox_is_private_and_tracks_reading(client, team):
    manual(client, team["admin"])
    inbox = client.get("/api/v1/notifications", headers=team["tech"]).json()
    assert inbox["unread"] == 1 and inbox["items"][0]["highlighted"] is True
    item = inbox["items"][0]["id"]
    assert client.get("/api/v1/notifications", headers=team["client"]).json() == {"items": [], "unread": 0}
    assert client.post(f"/api/v1/notifications/{item}/read", headers=team["client"]).status_code == 404
    read = client.post(f"/api/v1/notifications/{item}/read", headers=team["tech"])
    assert read.status_code == 200 and read.json()["read_at"]
    assert client.get("/api/v1/notifications", headers=team["tech"]).json()["unread"] == 0
    assert client.get("/api/v1/notifications").status_code == 401


def test_managers_see_delivery_record_but_viewer_does_not(client, team):
    ticket = manual(client, team["tech"]).json()
    path = f"{BASE}/{ticket['id']}"
    assert {d["channel"] for d in client.get(path, headers=team["tech"]).json()["deliveries"]} == {"in_app"}
    assert client.get(path, headers=team["visor"]).json()["deliveries"] == []
