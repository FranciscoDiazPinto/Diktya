"""Auditoría de identidad; sin contraseñas, tokens ni cuerpos de solicitudes.

Los casos de uso agregan eventos a su transacción. Las denegaciones HTTP se
acumulan por solicitud y se guardan tras cerrar la transacción rechazada.
"""
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field

from anyio import to_thread
from sqlalchemy.orm import Session

from .models import AuthAuditEvent

logger = logging.getLogger('netbot.auth')


def record_event(db: Session, action: str, *, actor_id=None, target_id=None,
                 outcome='success', details=None, source='http') -> None:
    """No confirma: el caso de uso posee la transacción."""
    db.add(AuthAuditEvent(action=action, actor_id=actor_id, target_id=target_id,
                         outcome=outcome, details=details or {}, source=source))


@dataclass
class RequestAudit:
    bind: object = None
    actor_id: int | None = None
    denials: list[dict] = field(default_factory=list)


_request: ContextVar[RequestAudit | None] = ContextVar('auth_request_audit', default=None)


def bind_request(db: Session, actor_id: int | None = None) -> None:
    trail = _request.get()
    if trail is not None:
        trail.bind = db.get_bind()
        if actor_id is not None:
            trail.actor_id = actor_id


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
    nunca confirma escrituras pendientes del caso de uso denegado.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        trail = RequestAudit()
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
