"""Exclusión real entre sesiones/procesos y liberación al morir el propietario."""
import os
from pathlib import Path
import select
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.changes.execution import PlanBusy, plan_lock

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=['sqlite', 'postgresql'])
def lock_engine(request, tmp_path):
    url = f'sqlite:///{tmp_path / "locks.db"}'
    if request.param == 'postgresql':
        url = os.environ.get('NETBOT_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('PostgreSQL temporal no configurado; CI lo proporciona.')
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def test_plan_lock_survives_business_commits_and_rollbacks(lock_engine):
    with Session(lock_engine) as first, Session(lock_engine) as second:
        with plan_lock(first, 'ssid', 'commits'):
            first.execute(text('SELECT 1'))
            first.commit()
            with pytest.raises(PlanBusy):
                with plan_lock(second, 'ssid', 'commits'):
                    pytest.fail('Dos propietarios del mismo plan')
            first.execute(text('SELECT 1'))
            first.rollback()
            with pytest.raises(PlanBusy):
                with plan_lock(second, 'ssid', 'commits'):
                    pytest.fail('Rollback liberó la exclusión')
            with plan_lock(second, 'vlan', 'another-plan'):
                pass  # otros planes no quedan serializados globalmente
        with plan_lock(second, 'ssid', 'commits'):
            pass


def test_plan_lock_is_released_on_failure_before_returning_to_pool(lock_engine):
    with Session(lock_engine) as db:
        with pytest.raises(RuntimeError):
            with plan_lock(db, 'vlan', 'failed'):
                raise RuntimeError('fallo simulado')
        with plan_lock(db, 'vlan', 'failed'):
            pass


def test_dead_process_releases_ownership_but_a_live_one_does_not(lock_engine, tmp_path):
    child = '''
import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.changes.execution import plan_lock
engine = create_engine(os.environ['NETBOT_LOCK_TEST_URL'])
with Session(engine) as db, plan_lock(db, 'restart', 'crashed-process'):
    print('held', flush=True)
    sys.stdin.read(1)
'''
    env = dict(os.environ, PYTHONPATH=str(ROOT),
               NETBOT_LOCK_TEST_URL=lock_engine.url.render_as_string(hide_password=False))
    process = subprocess.Popen([sys.executable, '-c', child], cwd=tmp_path, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 8)[0], 'El propietario no inició a tiempo'
        assert process.stdout.readline().strip() == 'held'
        with Session(lock_engine) as db:
            with pytest.raises(PlanBusy):
                with plan_lock(db, 'restart', 'crashed-process'):
                    pytest.fail('El proceso vivo perdió su exclusión')
            process.kill()
            process.communicate(timeout=5)
            # PostgreSQL debe observar primero el cierre de su conexión.
            deadline = time.monotonic() + 3
            while True:
                try:
                    with plan_lock(db, 'restart', 'crashed-process'):
                        break
                except PlanBusy:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
