"""Notificaciones de tickets: en la aplicación y por correo, con registro de cada entrega.

La notificación interna se registra en la misma transacción que el ticket, por lo que no
depende del correo. El correo queda pendiente y lo envía el agente, con reintentos.
"""

import logging
import smtplib
import ssl
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.service import active_staff
from app.core.config import Settings
from app.core.errors import NotFound
from app.networks.access import assigned_user_ids

from .models import Notification, Ticket
from .schemas import NotificationPage, NotificationRead

logger = logging.getLogger("netbot.tickets.notifications")

_LABELS = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
_EVENTS = {"created": "Nuevo ticket", "escalated": "Ticket sin atención", "reopened": "Incidente repetido",
           "resolved": "Ticket resuelto"}
Mailer = Callable[[str, str, str], None]


def _recipients(db: Session, ticket: Ticket) -> list[dict]:
    staff = active_staff(db)
    if ticket.network_id is None:
        return staff
    # Un ticket de cliente solo es visible para quien gestiona esa red.
    assigned = assigned_user_ids(db, ticket.network_id)
    return [person for person in staff if person["admin"] or person["id"] in assigned]


def enqueue(db: Session, ticket: Ticket, event: str, settings: Settings, now: datetime) -> None:
    """Agrega las entregas a la sesión. No confirma: el dueño es el caso de uso."""
    label = _LABELS[ticket.criticality]
    title = f"[{label}] {_EVENTS[event]} #{ticket.id}: {ticket.summary}"[:255]
    device = f"Dispositivo: {ticket.device_name}\n" if ticket.device_name else ""
    link = f"{settings.public_app_url.rstrip('/')}/#ticket-{ticket.id}"
    body = f"Ticket #{ticket.id}\nCriticidad: {label}\n{device}Detalle: {link}"
    highlighted = ticket.criticality in {"alta", "critica"}
    for person in _recipients(db, ticket):
        common = dict(ticket_id=ticket.id, user_id=person["id"], event=event, criticality=ticket.criticality,
                      highlighted=highlighted, title=title, body=body, link=link)
        db.add(Notification(channel="in_app", status="sent", sent_at=now, **common))
        if settings.smtp_host:
            db.add(Notification(channel="email", status="pending", next_attempt_at=now, **common))


def build_mailer(settings: Settings) -> Mailer | None:
    if not settings.smtp_host:
        return None

    def send(recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = settings.smtp_from or settings.smtp_username or "netbot@localhost"
        message["To"] = recipient
        message["Subject"] = " ".join(subject.split())  # sin saltos de línea en la cabecera
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as client:
            if settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
            client.send_message(message)

    return send


def due_emails(db: Session, now: datetime) -> list[Notification]:
    """Alta y Crítica primero."""
    return list(db.scalars(select(Notification).where(
        Notification.channel == "email", Notification.status == "pending", Notification.next_attempt_at <= now,
    ).order_by(Notification.highlighted.desc(), Notification.id).limit(50)))


def register_attempt(row: Notification, error: Exception | None, settings: Settings, now: datetime) -> None:
    row.attempts += 1
    if error is None:
        row.status, row.sent_at, row.last_error = "sent", now, None
        return
    row.last_error = type(error).__name__[:80]  # nunca el mensaje: puede traer credenciales
    if row.attempts >= settings.notification_email_max_attempts:
        row.status = "failed"
        return
    row.next_attempt_at = now + timedelta(seconds=settings.notification_email_retry_seconds * 2 ** (row.attempts - 1))


def list_for_user(db: Session, user: User, limit: int) -> NotificationPage:
    mine = (Notification.user_id == user.id, Notification.channel == "in_app")
    rows = db.scalars(select(Notification).where(*mine).order_by(Notification.id.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(*mine, Notification.read_at.is_(None)))
    return NotificationPage(items=[NotificationRead.model_validate(row) for row in rows], unread=unread or 0)


def mark_read(db: Session, user: User, notification_id: int) -> NotificationRead:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id or row.channel != "in_app":
        raise NotFound("Notificación no encontrada.")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return NotificationRead.model_validate(row)
