"""Ambas líneas publicadas convergen sin borrar datos ni cambiar revisiones."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('previous', ['009_network_monitoring_scope', '008_ticket_incidents'])
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
        if previous == '009_network_monitoring_scope':
            db.execute(text("INSERT INTO auth_audit_events (actor_id,action,outcome,source,details) VALUES (17,'test','success','test','{}')"))
        else:
            db.execute(text("INSERT INTO monitoring_sources (source,status,consecutive_failures) VALUES ('mock','ok',0)"))
    migrate('head')
    with engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '010_merge_monitoring_tickets'
        assert db.scalar(text('SELECT email FROM users WHERE id=17')) == 'preserved@example.com'
        if previous == '009_network_monitoring_scope':
            assert db.scalar(text('SELECT actor_id FROM auth_audit_events')) == 17
        else:
            assert db.scalar(text('SELECT status FROM monitoring_sources')) == 'ok'
    names = inspect(engine).get_table_names()
    assert {'ssid_plans', 'auth_audit_events', 'monitoring_devices', 'notifications'} <= set(names)
    assert {'unifi_site_id', 'unifi_ap_ids'} <= {column['name'] for column in inspect(engine).get_columns('network_support_config')}
    engine.dispose()
