"""Auditoría de identidad; sin contraseñas, tokens ni cuerpos de solicitudes.

Los casos de uso agregan eventos a su transacción. Las denegaciones HTTP se
acumulan por solicitud y se guardan tras cerrar la transacción rechazada.
"""
import hashlib
import hmac
import json
import logging
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass, field

from anyio import to_thread
from sqlalchemy.orm import Session

from app.core.keys import derive_key
from app.core.request_security import SharedRequestLimits, client_peer

from .models import AuthAuditEvent

logger = logging.getLogger('netbot.auth')
# Denegaciones sin identidad: admiten muestreo porque no atribuyen nada a una cuenta.
ANONYMOUS_DENIALS_PER_PEER = 5
ANONYMOUS_DENIALS_TOTAL = 20


def record_event(db: Session, action: str, *, actor_id=None, target_id=None,
                 outcome='success', details=None, source='http') -> None:
    """No confirma: el caso de uso posee la transacción."""
    merged = dict(details or {})
    trail = _request.get()
    if trail is not None and trail.peer:
        merged.setdefault('peer', trail.peer)
    db.add(AuthAuditEvent(action=action, actor_id=actor_id, target_id=target_id,
                         outcome=outcome, details=merged, source=source))


@dataclass
class RequestAudit:
    bind: object = None
    actor_id: int | None = None
    denials: list[dict] = field(default_factory=list)
    peer: str | None = None


_request: ContextVar[RequestAudit | None] = ContextVar('auth_request_audit', default=None)


def bind_request(db: Session, actor_id: int | None = None) -> None:
    trail = _request.get()
    if trail is not None:
        trail.bind = db.get_bind()
        if actor_id is not None:
            trail.actor_id = actor_id


def current_peer() -> str | None:
    """Huella del origen de la solicitud; nunca la IP en claro."""
    trail = _request.get()
    return trail.peer if trail is not None else None


def queue_denial(actor_id=None, permission=None, *, reason='permission') -> None:
    """Solo metadatos del servidor; funciona también desde hilos y herramientas."""
    trail = _request.get()
    if trail is None:
        return
    item = {'actor_id': actor_id if actor_id is not None else trail.actor_id,
            'permission': str(permission.value if hasattr(permission, 'value') else permission or ''),
            'reason': reason}
    if item not in trail.denials:
        trail.denials.append(item)


def _persist_denials(trail: RequestAudit, route: str) -> None:
    with Session(trail.bind) as db:
        for item in trail.denials:
            record_event(db, 'access.denied', actor_id=item['actor_id'], outcome='denied',
                         details={'permission': item['permission'], 'reason': item['reason'], 'route': route})
        db.commit()


class AuthAuditMiddleware:
    """Difiere solo respuestas con denegaciones hasta persistir su auditoría.

    Espera la limpieza de dependencias antes de abrir la transacción de auditoría:
    nunca confirma escrituras pendientes del caso de uso denegado. Las denegaciones
    anónimas se muestrean: la tabla es de solo inserción y no debe crecer a voluntad
    de quien no tiene cuenta. Las de una identidad conocida se registran siempre.
    """
    def __init__(self, app, path=None, secret=None):
        self.app = app
        self.limits = SharedRequestLimits(path, secret) if path and secret else None
        self.peer_key = derive_key(secret, 'audit-peer').encode() if secret else None

    def _peer(self, scope) -> str | None:
        if self.peer_key is None:
            return None
        return hmac.new(self.peer_key, client_peer(scope).encode(), hashlib.sha256).hexdigest()[:32]

    async def _record_anonymous(self, scope) -> bool:
        if self.limits is None:
            return True
        try:
            return await to_thread.run_sync(self.limits.admit, 'audit-anonymous', client_peer(scope),
                                            ANONYMOUS_DENIALS_PER_PEER, ANONYMOUS_DENIALS_TOTAL)
        except (sqlite3.Error, OSError):
            return False

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        trail = RequestAudit(peer=self._peer(scope))
        token = _request.set(trail)
        buffered = []

        async def audited_send(message):
            if message['type'] == 'http.response.start' and scope['path'].startswith(('/auth/', '/admin/')):
                message = {**message, 'headers': list(message.get('headers', [])) + [(b'cache-control', b'no-store, private')]}
            if message['type'] == 'http.response.start' and message['status'] == 403 and trail.actor_id is not None and not trail.denials:
                queue_denial(reason='forbidden')
            if trail.denials:
                buffered.append(message)
            else:
                await send(message)

        try:
            await self.app(scope, receive, audited_send)
            if buffered:
                anonymous = all(item['actor_id'] is None for item in trail.denials)
                if anonymous and not await self._record_anonymous(scope):
                    for message in buffered:
                        await send(message)
                    return
                try:
                    if trail.bind is None:
                        raise RuntimeError('Auditoría sin conexión de solicitud')
                    route = getattr(scope.get('route'), 'path', '')
                    await to_thread.run_sync(_persist_denials, trail, route)
                except Exception:
                    logger.error('No se pudo persistir la auditoría de autorización.')
                    body = json.dumps({'detail': 'No fue posible registrar la operación de seguridad.'}).encode()
                    await send({'type': 'http.response.start', 'status': 503,
                                'headers': [(b'content-type', b'application/json'), (b'cache-control', b'no-store')]})
                    await send({'type': 'http.response.body', 'body': body})
                    return
                for message in buffered:
                    await send(message)
        finally:
            _request.reset(token)
