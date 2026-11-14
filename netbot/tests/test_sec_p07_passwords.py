"""Auditoría 2026-11: política de contraseñas, cambio propio y CLI sin secretos en argumentos."""
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.models import AuthAuditEvent
from app.auth.schemas import UserCreate

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('password', ['corta-1', 'aaaaaaaaaaaaaaaa', 'password1234', 'ababababababab'])
def test_trivial_passwords_are_rejected(password):
    with pytest.raises(ValidationError):
        UserCreate(email='a@example.com', password=password)


def test_long_passphrases_are_accepted_without_composition_rules():
    assert UserCreate(email='a@example.com', password='caballo correcto bateria').password


def test_user_changes_own_password_with_current_one_and_sessions_close(client, db_session, viewer_user, login):
    _, headers = login(viewer_user.email, 'viewer-password')
    response = client.post('/auth/password', headers=headers, json={'current_password': 'viewer-password', 'new_password': 'una clave nueva larga'})
    assert response.status_code == 204
    assert client.get('/auth/me', headers=headers).status_code == 401
    assert client.post('/auth/login', json={'email': viewer_user.email, 'password': 'viewer-password'}).status_code == 401
    assert client.post('/auth/login', json={'email': viewer_user.email, 'password': 'una clave nueva larga'}).status_code == 200


def test_wrong_current_password_changes_nothing_and_is_audited(client, db_session, viewer_user, login):
    _, headers = login(viewer_user.email, 'viewer-password')
    response = client.post('/auth/password', headers=headers, json={'current_password': 'no-es-esta', 'new_password': 'una clave nueva larga'})
    assert response.status_code == 401
    assert db_session.scalar(select(AuthAuditEvent).where(AuthAuditEvent.action == 'user.password_change_failed'))
    assert client.post('/auth/login', json={'email': viewer_user.email, 'password': 'viewer-password'}).status_code == 200


def test_cli_no_longer_accepts_the_password_as_an_argument():
    result = subprocess.run([sys.executable, '-m', 'app.auth.cli', 'a@example.com', 'secreto-en-argv', '--role', 'visor'],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2 and 'unrecognized arguments' in result.stderr
