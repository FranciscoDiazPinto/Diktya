"""Pruebas locales sin Telegram real ni controlador UniFi."""
from unittest.mock import AsyncMock
from sqlalchemy import select
from app.auth.models import RefreshToken
from app.auth.security import verify_password
from app.telegram_recovery import service
from app.telegram_recovery.models import TelegramBinding, TelegramChallenge


def test_link_and_reset(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(service, 'configured', lambda: True)
    raw = service.create_link(db_session, admin_user)
    assert service.accept_link(db_session, raw, '12345', True)
    assert not service.accept_link(db_session, raw, '12345', True)
    assert db_session.get(TelegramBinding, admin_user.id).chat_id == '12345'
    sent = []
    async def fake_send(chat, message):
        sent.append((chat, message))
        return True
    monkeypatch.setattr(service, 'send', fake_send)
    import asyncio
    asyncio.run(service.request_reset(db_session, admin_user.email))
    assert len(sent) == 1
    code = sent[0][1].split('recuperación: ')[1].split('.')[0]
    assert not service.complete_reset(db_session, admin_user.email, '00000000' if code != '00000000' else '11111111', 'New-password-12345')
    assert service.complete_reset(db_session, admin_user.email, code, 'New-password-12345')
    assert verify_password('New-password-12345', admin_user.hashed_password)
    assert not service.complete_reset(db_session, admin_user.email, code, 'Another-password-12345')


def test_reset_unknown_user_has_no_delivery(db_session, monkeypatch):
    monkeypatch.setattr(service, 'configured', lambda: True)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(service, 'send', send)
    import asyncio
    asyncio.run(service.request_reset(db_session, 'unknown@example.com'))
    send.assert_not_awaited()


def test_link_rejects_reused_token_and_nonprivate(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(service, 'configured', lambda: True)
    raw = service.create_link(db_session, admin_user)
    assert not service.accept_link(db_session, raw, '-1001234', False)
    assert service.accept_link(db_session, raw, '1234', True)
    assert not service.accept_link(db_session, raw, '9999', True)
