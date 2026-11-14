"""Auditoría 2026-11: permisos del archivo SQLite, clave de escritura y CSP de la interfaz."""
import stat
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine

from app.bootstrap import initialize_database
from app.changes.ssid_executor import UniFiSsidWriter
from app.changes.ssid_schemas import SsidProposal
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_file_is_readable_only_by_the_service_account(tmp_path):
    path = tmp_path / 'netbot.db'
    path.touch(mode=0o644)
    initialize_database(Settings(_env_file=None, environment='development'), bind=create_engine(f'sqlite:///{path}'))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_writer_uses_its_own_key_when_configured():
    seen = []
    def handler(request):
        seen.append(request.headers['x-api-key'])
        if request.url.path.endswith('/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        return httpx.Response(201, json={'id': 'nuevo'})
    settings = Settings(_env_file=None, unifi_write_enabled=True, unifi_api_contract='10.6.106', unifi_inventory_mode='api',
                        unifi_api_base_url='https://unifi.test/integration/v1', unifi_api_key='solo-lectura', unifi_write_api_key='escritura',
                        ssid_security_profiles_json='{"p":{"type":"WPA2_PERSONAL","passphrase":"clave-sintetica-1","bands":[5]}}')
    writer = UniFiSsidWriter(settings, transport=httpx.MockTransport(handler))
    proposal = SsidProposal(scope_id=1, ssid='Feria', network_id='n', ap_ids=['a'], security_profile='p', purpose='x')
    assert await writer.create('site', proposal, authorize=lambda: None) == 'nuevo'
    assert set(seen) == {'escritura'}


def test_interface_declares_a_restrictive_content_policy():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "script-src 'self';" in html and "object-src 'none'" in html and 'unsafe-eval' not in html
