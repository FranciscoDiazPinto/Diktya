"""Límites compartidos por procesos locales; sin tokens ni IP en claro en disco."""
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import time

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class SharedRequestLimits:
    def __init__(self, path, secret, clock=time.time):
        self.path = str(Path(path).resolve())
        self.secret = secret.encode()
        self.clock = clock
        # No guardar identificadores en un archivo legible por otros usuarios.
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with sqlite3.connect(self.path, timeout=1) as db:
            db.execute('CREATE TABLE IF NOT EXISTS request_limits (key TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)')

    def admit(self, group, peer, per_peer, total):
        window = int(self.clock() // 60)
        digest = hmac.new(self.secret, peer.encode(), hashlib.sha256).hexdigest()
        keys = [(f'{group}:{digest}', per_peer), (f'{group}:global', total)]
        with sqlite3.connect(self.path, timeout=0.25) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM request_limits WHERE window < ?', (window - 1,))
            for key, limit in keys:
                row = db.execute('SELECT count FROM request_limits WHERE key=? AND window=?', (key, window)).fetchone()
                if row and row[0] >= limit:
                    return False
            for key, _ in keys:
                db.execute('INSERT INTO request_limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET window=excluded.window, count=CASE WHEN request_limits.window=excluded.window THEN request_limits.count+1 ELSE 1 END', (key, window))
        return True


class RequestSecurityMiddleware:
    def __init__(self, app, path, secret):
        self.app = app
        self.limits = SharedRequestLimits(path, secret)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'], scope['method']
        policy = None
        if method == 'POST':
            if path in {'/auth/login', '/auth/refresh'}:
                policy = ('auth', 10, 60)
            elif path == '/api/v1/guest/sessions':
                policy = ('guest-start', 5, 120)
            elif path.startswith(('/api/v1/chat/', '/api/v1/guest/')) and path.endswith('/messages'):
                policy = ('chat', 10, 60)
            elif path == '/api/v1/guest/identify':
                policy = ('recovery', 5, 60)
        if policy:
            # No confiar en X-Forwarded-For aportado por clientes; el servidor ASGI
            # solo debe aceptar proxy headers desde su proxy explícitamente confiable.
            peer = (scope.get('client') or ('unknown', 0))[0]
            group, per_peer, total = policy
            try:
                admitted = await run_in_threadpool(self.limits.admit, group, peer, per_peer, total)
            except (sqlite3.Error, OSError):
                return await JSONResponse({'detail': 'Control de acceso temporalmente no disponible.'}, status_code=503)(scope, receive, send)
            if not admitted:
                return await JSONResponse({'detail': 'Demasiadas solicitudes. Espera un minuto.'}, status_code=429,
                                          headers={'Retry-After': '60', 'Cache-Control': 'no-store'})(scope, receive, send)
        received_bytes = 0
        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            received_bytes += len(message.get('body', b''))
            if policy and received_bytes > 65536:
                raise HTTPException(413, 'La solicitud excede el tamaño permitido.')
            return message

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = [(key, value) for key, value in message.get('headers', [])
                                      if key.lower() not in {b'x-content-type-options', b'referrer-policy'}] + [
                    (b'x-content-type-options', b'nosniff'),
                    (b'referrer-policy', b'no-referrer'),
                ]
                if path.startswith('/auth/'):
                    message['headers'].append((b'cache-control', b'no-store'))
            await send(message)
        await self.app(scope, limited_receive, secure_send)
