"""Límites compartidos por procesos locales; sin tokens ni IP en claro en disco."""
from contextlib import closing
import hashlib
import hmac
import ipaddress
import os
from pathlib import Path
import sqlite3
import time

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

SMALL_BODY_BYTES = 65536
# (grupo, por origen/min, global/min). Cada frontera tiene su propio grupo: un invitado
# anónimo nunca consume el cupo de un usuario autenticado, ni el login el de la renovación.
EXACT_POLICIES = {
    '/auth/login': ('auth-login', 10, 600),
    '/auth/refresh': ('auth-refresh', 20, 1200),
    '/auth/logout': ('auth-logout', 20, 1200),
    '/auth/password': ('auth-password', 5, 120),
    '/api/v1/guest/sessions': ('guest-start', 5, 120),
    '/api/v1/guest/session/activity': ('guest-touch', 12, 600),
    '/api/v1/guest/messages': ('chat-guest', 10, 60),
    '/api/v1/chat/messages': ('chat-user', 20, 240),
    '/api/v1/guest/identify': ('recovery', 5, 60),
    '/api/v1/guest/recovery/email': ('recovery', 5, 60),
    '/api/v1/guest/recovery/approve': ('recovery', 5, 60),
}
GUEST_QR_POLICY = ('guest-qr', 10, 120)
DOCUMENTATION_PATHS = ('/docs', '/redoc', '/openapi.json')
API_HEADERS = ((b'content-security-policy', b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
               (b'x-frame-options', b'DENY'),
               (b'permissions-policy', b'camera=(), microphone=(), geolocation=()'),
               (b'cross-origin-resource-policy', b'same-site'))


def client_peer(scope) -> str:
    """Identidad de red para cuotas. IPv6 se agrupa por /64: un cliente controla todo su prefijo."""
    host = (scope.get('client') or ('unknown', 0))[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if address.version == 6:
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f'{address}/64', strict=False).network_address)
    return host


def request_policy(method, path):
    if method != 'POST':
        return None
    if path.startswith('/api/v1/guest/networks/') and path.endswith('/access'):
        return GUEST_QR_POLICY
    return EXACT_POLICIES.get(path)


class SharedRequestLimits:
    def __init__(self, path, secret, clock=time.time):
        self.path = str(Path(path).resolve())
        self.secret = secret.encode()
        self.clock = clock
        # No guardar identificadores en un archivo legible por otros usuarios.
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with closing(self._connect()) as connection, connection as db:
            # WAL: los contadores no esperan a sincronizar disco en cada solicitud. Perderlos
            # en un corte eléctrico solo reinicia una ventana; un 503 afecta a usuarios reales.
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS request_limits (key TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS request_budgets (key TEXT PRIMARY KEY, day INTEGER NOT NULL, count INTEGER NOT NULL)')

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=2)
        connection.execute('PRAGMA synchronous=OFF')
        return connection

    def admit(self, group, peer, per_peer, total):
        window = int(self.clock() // 60)
        digest = hmac.new(self.secret, peer.encode(), hashlib.sha256).hexdigest()
        keys = [(f'{group}:{digest}', per_peer), (f'{group}:global', total)]
        with closing(self._connect()) as connection, connection as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM request_limits WHERE window < ?', (window - 1,))
            for key, limit in keys:
                row = db.execute('SELECT count FROM request_limits WHERE key=? AND window=?', (key, window)).fetchone()
                if row and row[0] >= limit:
                    return False
            for key, _ in keys:
                db.execute('INSERT INTO request_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET window=excluded.window, count=CASE WHEN request_limits.window=excluded.window THEN request_limits.count+1 ELSE 1 END', (key, window))
        return True

    def spend(self, group, limit):
        """Presupuesto diario de un recurso con costo externo (llamadas al LLM)."""
        day = int(self.clock() // 86400)
        with closing(self._connect()) as connection, connection as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM request_budgets WHERE day < ?', (day,))
            row = db.execute('SELECT count FROM request_budgets WHERE key=? AND day=?', (group, day)).fetchone()
            if row and row[0] >= limit:
                return False
            db.execute('INSERT INTO request_budgets VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET day=excluded.day, count=CASE WHEN request_budgets.day=excluded.day THEN request_budgets.count+1 ELSE 1 END', (group, day))
        return True


class RequestSecurityMiddleware:
    def __init__(self, app, path, secret, *, json_limit=262144, upload_limits=None, budgets=None):
        self.app = app
        self.limits = SharedRequestLimits(path, secret)
        self.json_limit = json_limit
        self.upload_limits = upload_limits or {}
        self.budgets = budgets or {}

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'], scope['method']
        policy = request_policy(method, path)

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = [(key, value) for key, value in message.get('headers', [])
                                      if key.lower() not in {b'x-content-type-options', b'referrer-policy'}] + [
                    (b'x-content-type-options', b'nosniff'),
                    (b'referrer-policy', b'no-referrer'),
                ]
                present = {key.lower() for key, _ in message['headers']}
                # La API no se enmarca ni carga subrecursos; /docs de desarrollo sí los necesita.
                if not path.startswith(DOCUMENTATION_PATHS):
                    for name, value in API_HEADERS:
                        if name not in present:
                            message['headers'].append((name, value))
                if path.startswith('/auth/'):
                    message['headers'].append((b'cache-control', b'no-store'))
            await send(message)

        # FastAPI lee el cuerpo JSON antes de resolver la autenticación: el tope debe estar aquí.
        limit = SMALL_BODY_BYTES if policy else self.upload_limits.get(path, self.json_limit)
        declared = dict(scope.get('headers') or []).get(b'content-length', b'')
        if declared.isdigit() and int(declared) > limit:
            return await JSONResponse({'detail': 'La solicitud excede el tamaño permitido.'},
                                      status_code=413)(scope, receive, secure_send)
        if policy:
            # No confiar en X-Forwarded-For aportado por clientes; el servidor ASGI
            # solo debe aceptar proxy headers desde su proxy explícitamente confiable.
            group, per_peer, total = policy
            budget = self.budgets.get(group)
            try:
                admitted = await run_in_threadpool(self.limits.admit, group, client_peer(scope), per_peer, total)
                exhausted = bool(admitted and budget and not await run_in_threadpool(self.limits.spend, group, budget))
            except (sqlite3.Error, OSError):
                return await JSONResponse({'detail': 'Control de acceso temporalmente no disponible.'},
                                          status_code=503)(scope, receive, secure_send)
            if exhausted:
                return await JSONResponse({'detail': 'Se agotó el cupo diario del asistente. Usa las opciones del portal o contacta al equipo.'},
                                          status_code=429, headers={'Cache-Control': 'no-store'})(scope, receive, secure_send)
            if not admitted:
                return await JSONResponse({'detail': 'Demasiadas solicitudes. Espera un minuto.'}, status_code=429,
                                          headers={'Retry-After': '60', 'Cache-Control': 'no-store'})(scope, receive, secure_send)
        received_bytes = 0
        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            received_bytes += len(message.get('body', b''))
            if received_bytes > limit:
                raise HTTPException(413, 'La solicitud excede el tamaño permitido.')
            return message

        await self.app(scope, limited_receive, secure_send)
