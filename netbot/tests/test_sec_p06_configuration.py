"""Auditoría 2026-11: configuración que falla cerrada, API sin metadatos en producción."""
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app

STRONG = 'k9-' + ''.join(chr(48 + i % 70) for i in range(80))


def production(**overrides):
    return Settings(_env_file=None, environment='production', jwt_secret_key=STRONG, **overrides)


@pytest.mark.parametrize('overrides', [
    {'jwt_secret_key': 'a' * 64}, {'jwt_secret_key': 'replace-with-a-long-random-secret'}, {'admin_password': '1'},
    {'public_app_url': 'http://netbot.example.com'}, {'cors_origins': 'http://evil.example.com'},
    {'smtp_host': 'smtp.example.com', 'smtp_starttls': False},
])
def test_production_rejects_weak_settings_it_used_to_accept(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{'environment': 'production', 'jwt_secret_key': STRONG, **overrides})


def test_valid_production_settings_are_accepted():
    assert production(public_app_url='https://netbot.example.com', cors_origins='https://netbot.example.com',
                      smtp_host='smtp.example.com', admin_password='clave-larga-segura').environment == 'production'


def test_undeclared_environment_applies_production_rules(monkeypatch):
    monkeypatch.delenv('ENVIRONMENT')
    monkeypatch.delenv('JWT_SECRET_KEY')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize('value', ['', 'change-me-in-production', 'replace-with-a-long-random-secret'])
def test_development_never_signs_with_a_published_key(value):
    current = Settings(_env_file=None, environment='development', jwt_secret_key=value)
    assert len(current.jwt_secret_key) >= 64 and current.jwt_secret_key != value


def test_sqlite_in_production_is_reported(caplog):
    with caplog.at_level(logging.WARNING, 'netbot.config'):
        production(database_url='sqlite:///x.db')
    assert 'SQLite' in caplog.text


def test_settings_repr_does_not_reveal_secrets():
    text = repr(production(admin_password='clave-larga-segura', database_url='postgresql://u:clave-db@h/d'))
    assert 'clave-larga-segura' not in text and STRONG not in text and 'clave-db' not in text


def test_api_contract_is_not_published_in_production(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'get_settings', lambda: production(database_url='sqlite://'))
    client = TestClient(create_app())  # sin contexto: no ejecuta el arranque
    assert [client.get(path).status_code for path in ('/docs', '/redoc', '/openapi.json')] == [404] * 3


def test_api_sets_defensive_headers_without_touching_the_recovery_page_policy(client):
    headers = client.get('/health').headers
    assert headers['x-frame-options'] == 'DENY' and "frame-ancestors 'none'" in headers['content-security-policy']
    page = client.get('/api/v1/guest/recovery/approve').headers
    assert "script-src 'self'" in page['content-security-policy']


def test_cors_only_allows_the_headers_the_client_uses(client):
    response = client.options('/auth/login', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
                                                      'Access-Control-Request-Headers': 'X-Admin-Override'})
    assert response.status_code == 400
    allowed = client.options('/auth/login', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
                                                     'Access-Control-Request-Headers': 'content-type'})
    assert allowed.status_code == 200 and 'access-control-allow-credentials' not in allowed.headers
