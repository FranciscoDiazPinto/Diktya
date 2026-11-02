"""Enlace de posesión por correo: QR en el dispositivo que confirma, nunca en el LLM."""
import hashlib
import logging
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlsplit

from sqlalchemy import delete, select, update
from app.core.errors import NotFound, ServiceUnavailable
from .support_models import NetworkSupportConfig, WifiEmailRecovery
from .recipients import matching_networks, normalize_contact
from .guest_policy import expositor_network, lock_recovery_networks
from .guest_access import GuestWifiQr
from .credentials import credential_for
from .wifi_qr import wifi_qr_data_url

GENERIC_MESSAGE = 'Si el correo tiene acceso a una red de expositores habilitada, recibirá un enlace. Revisa tu bandeja de entrada. SMS y Telegram todavía no están disponibles.'


def now_utc():
    return datetime.now(timezone.utc)


def build_recovery_mailer(settings):
    if not settings.smtp_host:
        return None
    def send(to, subject, body):
        message = EmailMessage()
        message['To'], message['From'], message['Subject'] = to, settings.smtp_from or settings.smtp_username or 'netbot@localhost', subject
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds) as client:
            if settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value() if settings.smtp_password else '')
            client.send_message(message)
    return send


def recovery_origin(settings):
    base = urlsplit(settings.guest_email_recovery_public_url)
    if (not settings.guest_email_recovery_enabled or base.scheme not in {'http', 'https'}
            or not base.netloc or base.username or base.password or base.query or base.fragment
            or base.path not in {'', '/'}):
        raise ServiceUnavailable('La recuperación por correo no está configurada. Solicita ayuda al equipo.')
    if settings.environment == 'production' and base.scheme != 'https':
        raise ServiceUnavailable('La recuperación requiere HTTPS.')
    return f'{base.scheme}://{base.netloc}'


def eligible_networks(db, email):
    return [n for n in matching_networks(db, ('email', email))
            if expositor_network(n, db.get(NetworkSupportConfig, n.id))]


def prepare_email(db, settings, email, mailer):
    origin = recovery_origin(settings)
    if mailer is None:
        raise ServiceUnavailable('El envío de correo no está configurado. Solicita ayuda al equipo.')
    _, email = normalize_contact(email)
    now = now_utc()
    # Sin conservar enlaces crudos. Limpiar datos caducados al solicitar recuperación.
    db.execute(delete(WifiEmailRecovery).where(WifiEmailRecovery.expires_at <= now))
    networks = eligible_networks(db, email)
    lock_recovery_networks(db, [n.id for n in networks])
    networks = eligible_networks(db, email)
    recent = db.scalars(select(WifiEmailRecovery.id).where(WifiEmailRecovery.email == email,
                        WifiEmailRecovery.expires_at > now)).all()
    if len(recent) >= 2:
        networks = []
    raw = secrets.token_urlsafe(32)
    if networks:
        db.add(WifiEmailRecovery(id=secrets.token_urlsafe(24), token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                                email=email, network_ids=[n.id for n in networks], expires_at=now + timedelta(minutes=5)))
    db.commit()
    def deliver():
        if not networks:
            return
        link = origin + '/api/v1/guest/recovery/approve#' + raw
        try:
            mailer(email, 'Netbot: confirma tu acceso Wi-Fi de expositor',
                   'Solicitaste recuperar acceso Wi-Fi. Si no fuiste tú, ignora este correo.\n'
                   'El enlace caduca en cinco minutos y se utiliza una sola vez.\n'
                   'Ábrelo en tu dispositivo y confirma para ver tu QR:\n' + link)
        except Exception:
            # No registrar excepciones SMTP que puedan contener destinatarios o enlaces.
            logging.getLogger('netbot.recovery').warning('No se pudo entregar un correo de recuperación; comprueba SMTP.')
            return
    return deliver


def approve_and_reveal(db, settings, raw):
    recovery_origin(settings)
    now = now_utc()
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    row = db.scalar(select(WifiEmailRecovery).where(WifiEmailRecovery.token_hash == hashed,
                    WifiEmailRecovery.consumed_at.is_(None), WifiEmailRecovery.expires_at > now))
    error = NotFound('El enlace venció, ya fue utilizado o no permite recuperar acceso. Solicita uno nuevo.')
    if row is None:
        raise error
    allowed = set(row.network_ids)
    lock_recovery_networks(db, allowed)
    networks = [n for n in eligible_networks(db, row.email) if n.id in allowed]
    if not networks:
        raise error
    # Preparar sin consumir ante configuración incompleta; nunca devolver errores con secretos.
    result = [GuestWifiQr(ssid=c.ssid, qr_data_url=wifi_qr_data_url(c)) for c in
              [credential_for(n, db.get(NetworkSupportConfig, n.id), settings) for n in networks]]
    claimed = db.execute(update(WifiEmailRecovery).where(WifiEmailRecovery.id == row.id,
                         WifiEmailRecovery.consumed_at.is_(None), WifiEmailRecovery.expires_at > now)
                         .values(consumed_at=now, email='', network_ids=[]), execution_options={'synchronize_session': False})
    if claimed.rowcount != 1:
        db.rollback()
        raise error
    db.commit()
    return result
