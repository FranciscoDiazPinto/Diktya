"""Ambas líneas publicadas convergen sin borrar datos ni cambiar revisiones."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


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
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '012_wifi_email_recovery'
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
