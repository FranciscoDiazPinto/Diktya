"""Ambas líneas publicadas convergen sin borrar datos ni cambiar revisiones."""
from alembic.script import ScriptDirectory
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import make_url
from datetime import datetime, timedelta, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=['sqlite', 'postgresql'])
def execution_migration_url(request, tmp_path):
    if request.param == 'sqlite':
        yield f'sqlite:///{tmp_path / "execution.db"}'
        return
    configured = os.environ.get('NETBOT_TEST_POSTGRES_URL')
    if not configured:
        pytest.skip('PostgreSQL temporal no configurado; CI lo proporciona.')
    # Solo una base nueva con nombre aleatorio; nunca migrar la base del URL recibido.
    database = 'netbot_migration_' + uuid4().hex
    admin = create_engine(configured, isolation_level='AUTOCOMMIT')
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{database}"'))
        try:
            yield make_url(configured).set(database=database).render_as_string(hide_password=False)
        finally:
            with admin.connect() as db:
                db.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
    finally:
        admin.dispose()


def test_execution_upgrade_preserves_jobs_and_downgrade_requires_reconciliation(execution_migration_url, tmp_path):
    url = execution_migration_url
    env = dict(os.environ, DATABASE_URL=url, ENVIRONMENT='test', MONITORING_PROVIDER='mock',
               ADMIN_EMAIL='', ADMIN_PASSWORD='', UNIFI_ENABLED='false', GUEST_EMAIL_RECOVERY_ENABLED='false')
    def migrate(command, target, success=True):
        result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(ROOT/'alembic.ini'), command, target],
                                cwd=tmp_path, env=env, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stderr
        return result
    migrate('upgrade', '020_agent_events')
    engine = create_engine(url)
    try:
        old = datetime.now(timezone.utc)-timedelta(hours=2)
        common = dict(owner_id=17, scope_id=1, status='executing', revision='a'*64, execution_results=[],
                      created_at=old, expires_at=old+timedelta(hours=3), confirmed_at=old)
        metadata = MetaData()
        metadata.reflect(engine)
        with engine.begin() as db:
            db.execute(metadata.tables['users'].insert().values(id=17, email='review@example.test',
                       hashed_password='synthetic', is_active=True))
            db.execute(metadata.tables['wifi_scopes'].insert().values(id=1, name='Test', site_id='site', resources={}))
            db.execute(metadata.tables['ssid_plans'].insert().values(**common, id='ssid', source='unifi',
                       fingerprint='b'*64, rows=[], selection=[]))
            db.execute(metadata.tables['ssid_vlan_change_plans'].insert().values(**common, id='vlan',
                       broadcast_id='broadcast', site_id='site', ssid='Test', current_network_id='old',
                       target_network_id='new', purpose='test', fingerprint='b'*64))
            db.execute(metadata.tables['device_restart_plans'].insert().values(**common, id='restart',
                       site_id='site', device_id='ap', device_name='AP Test', access_point=True, purpose='test'))
            db.execute(metadata.tables['wifi_write_leases'].insert().values(resource_key='c'*64, restart_plan_id='restart'))
        migrate('upgrade', 'head')
        with engine.connect() as db:
            for name in ('ssid_plans', 'ssid_vlan_change_plans', 'device_restart_plans'):
                values = db.execute(text(f'SELECT confirmed_at, execution_started_at FROM {name}')).one()
                assert values.execution_started_at is not None
                assert str(values.execution_started_at) > str(values.confirmed_at)
            assert db.scalar(text('SELECT COUNT(*) FROM wifi_write_leases')) == 1
        failure = migrate('downgrade', '020_agent_events', success=False)
        assert 'pendientes de conciliación' in failure.stderr
        with engine.begin() as db:
            for name in ('ssid_plans', 'ssid_vlan_change_plans', 'device_restart_plans'):
                db.execute(text(f"UPDATE {name} SET status='failed'"))
            db.execute(text('DELETE FROM wifi_write_leases'))
        migrate('downgrade', '020_agent_events')
        for name in ('ssid_plans', 'ssid_vlan_change_plans', 'device_restart_plans'):
            assert 'execution_started_at' not in {column['name'] for column in inspect(engine).get_columns(name)}
        with engine.connect() as db:
            assert db.scalar(text('SELECT COUNT(*) FROM device_restart_plans')) == 1
            assert db.scalar(text('SELECT email FROM users WHERE id=17')) == 'review@example.test'
        migrate('upgrade', 'head')
    finally:
        engine.dispose()


@pytest.mark.parametrize('previous', ['009_network_monitoring_scope', '008_ticket_incidents', '010_merge_monitoring_tickets'])
def test_upgrade_each_history_preserves_records_and_converges(previous, tmp_path):
    url = f'sqlite:///{tmp_path / "integration.db"}'
    env = dict(os.environ, DATABASE_URL=url, ENVIRONMENT='test', MONITORING_PROVIDER='mock',
               UNIFI_ENABLED='false', TICKET_AGENT_ENABLED='false')
    def migrate(revision):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    migrate(previous)
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id,email,hashed_password,is_active) VALUES (17,'preserved@example.com','test-hash',1)"))
        if previous != '008_ticket_incidents':
            db.execute(text("INSERT INTO auth_audit_events (actor_id,action,outcome,source,details) VALUES (17,'test','success','test','{}')"))
        else:
            db.execute(text("INSERT INTO monitoring_sources (source,status,consecutive_failures) VALUES ('mock','ok',0)"))
    migrate('head')
    with engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory(str(ROOT / 'migrations')).get_current_head()
        assert db.scalar(text('SELECT email FROM users WHERE id=17')) == 'preserved@example.com'
        assert db.scalar(text('SELECT failed_login_attempts FROM users WHERE id=17')) == 0
        assert db.scalar(text('SELECT login_locked_until FROM users WHERE id=17')) is None
        if previous != '008_ticket_incidents':
            assert db.scalar(text('SELECT actor_id FROM auth_audit_events')) == 17
        else:
            assert db.scalar(text('SELECT status FROM monitoring_sources')) == 'ok'
    names = inspect(engine).get_table_names()
    assert {'ssid_plans', 'auth_audit_events', 'monitoring_devices', 'notifications'} <= set(names)
    assert {'unifi_site_id', 'unifi_ap_ids'} <= {column['name'] for column in inspect(engine).get_columns('network_support_config')}
    engine.dispose()


def test_sqlite_batch_upgrade_preserves_ticket_event_rows(tmp_path):
    url = f'sqlite:///{tmp_path / "ticket-history.db"}'
    env = dict(os.environ, DATABASE_URL=url, ENVIRONMENT='test', MONITORING_PROVIDER='mock')
    def migrate(target):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    migrate('008_auth_audit')
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id,email,hashed_password,is_active) VALUES (17,'preserved@example.com','test-hash',1)"))
        db.execute(text("INSERT INTO networks (id,name,site,event_name,external_id,ssid) VALUES (1,'Test','test','test','test','Test')"))
        db.execute(text("INSERT INTO tickets (id,network_id,created_by_id,request_key,summary,description,status,version,network_snapshot) VALUES (1,1,17,'synthetic','Preserved','Test','open',0,'{}')"))
        db.execute(text("INSERT INTO ticket_events (id,ticket_id,actor_id,status,note) VALUES (1,1,17,'open','Preserved event')"))
    migrate('head')
    with engine.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM tickets')) == 1
        assert db.scalar(text('SELECT note FROM ticket_events WHERE id=1')) == 'Preserved event'
        assert db.execute(text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()


def test_sqlite_migration_refuses_existing_orphans_before_schema_changes(tmp_path):
    import sqlite3
    file = tmp_path / 'orphan.db'
    url = f'sqlite:///{file}'
    env = dict(os.environ, DATABASE_URL=url, ENVIRONMENT='test', MONITORING_PROVIDER='mock')
    def migrate(target):
        return subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], cwd=ROOT,
                              env=env, capture_output=True, text=True)
    assert migrate('008_auth_audit').returncode == 0
    # Reproduce una inconsistencia creada por una versión antigua sin FK activas.
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO refresh_tokens (token_hash,user_id,expires_at) VALUES ('synthetic-orphan',99999,'2099-01-01')")
    result = migrate('head')
    assert result.returncode != 0
    assert 'referencias huérfanas' in result.stderr
    with sqlite3.connect(file) as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '008_auth_audit'
        assert 'failed_login_attempts' not in {row[1] for row in db.execute('PRAGMA table_info(users)')}
