"""Exclusión de ejecución y conciliación de un mismo plan entre procesos.

PostgreSQL usa un advisory lock de sesión, en una conexión dedicada que nunca vuelve
al pool con el lock tomado. SQLite local usa flock junto a la base (Unix).
Ninguno vence por tiempo: una operación lenta sigue protegida. Al morir el proceso
se libera la exclusión; el lease durable del recurso permanece hasta conciliar.

https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS
https://docs.python.org/3.12/library/fcntl.html#fcntl.flock
"""
from contextlib import contextmanager
from functools import wraps
import hashlib
import os
from pathlib import Path
import tempfile

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import Conflict, ServiceUnavailable


class PlanBusy(Conflict):
    """Otro ejecutor o conciliador posee el plan; no es un rechazo de aprobación."""


@contextmanager
def plan_lock(db, kind: str, plan_id: str):
    engine = db.get_bind().engine
    digest = hashlib.sha256(f'netbot:change:{kind}:{plan_id}'.encode()).digest()
    if engine.dialect.name == 'postgresql':
        key = int.from_bytes(digest[:8], 'big', signed=True)
        # No reutilizar la conexión de la transacción del servicio: sus commits
        # no deben liberar el bloqueo ni devolverlo inadvertidamente al pool.
        with engine.connect() as connection:
            try:
                acquired = connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': key})
                connection.commit()
            except SQLAlchemyError:
                connection.invalidate()
                raise ServiceUnavailable('No se pudo proteger la ejecución del cambio.') from None
            if not acquired:
                raise PlanBusy('El trabajo sigue activo en otro ejecutor o conciliador.')
            try:
                yield
            finally:
                try:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                    connection.commit()
                except SQLAlchemyError:
                    # Cerrar la conexión física: un lock de sesión nunca vuelve al pool.
                    connection.invalidate()
        return
    if engine.dialect.name != 'sqlite':
        raise ServiceUnavailable('La base no admite la exclusión de cambios configurada.')
    try:
        import fcntl
    except ImportError:
        raise ServiceUnavailable('La ejecución con SQLite requiere un sistema con flock.') from None
    database = engine.url.database
    if not database or database == ':memory:':
        directory = Path(tempfile.gettempdir()) / f'netbot-changes-{os.getpid()}-{id(engine)}'
    else:
        file = Path(database).resolve()
        directory = file.parent / f'.{file.name}.change-locks'
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(directory / digest.hex(), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        raise ServiceUnavailable('No se pudo proteger la ejecución del cambio.') from None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PlanBusy('El trabajo sigue activo en otro ejecutor o conciliador.') from None
        yield
    finally:
        # No borrar el archivo: otro proceso podría haber abierto ya ese mismo inode.
        os.close(descriptor)


def exclusive_plan(kind: str):
    def decorate(method):
        @wraps(method)
        async def guarded(self, plan_id: str):
            with plan_lock(self.db, kind, plan_id):
                return await method(self, plan_id)
        return guarded
    return decorate
