"""HU001: cinco fallos consecutivos bloquean el ingreso por quince minutos."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth import service
from app.auth.models import AuthAuditEvent, RefreshToken, Role, User
from app.auth.schemas import LoginRequest
from app.auth.security import hash_password
from app.core.database import Base
from app.core.errors import Unauthenticated

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def clock(monkeypatch):
    current = {'now': T0}
    monkeypatch.setattr(service, '_login_now', lambda: current['now'])
    return current


def attempt(client, email='admin@example.com', password='wrong-password'):
    return client.post('/auth/login', json={'email': email, 'password': password})


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def test_fifth_failure_blocks_correct_password_until_exact_deadline(client, db_session, admin_user, clock):
    for n in range(1, 6):
        response = attempt(client, email='ADMIN@example.com')
        assert response.status_code == 401
        db_session.refresh(admin_user)
        assert admin_user.failed_login_attempts == n
        assert (admin_user.login_locked_until is not None) == (n == 5)
    deadline = utc(admin_user.login_locked_until)
    assert deadline == T0 + timedelta(minutes=15)
    clock['now'] = deadline - timedelta(microseconds=1)
    assert attempt(client, password='admin-password').status_code == 401
    db_session.refresh(admin_user)
    assert utc(admin_user.login_locked_until) == deadline  # no prolonga el bloqueo
    assert admin_user.failed_login_attempts == 5
    assert db_session.scalar(select(func.count()).select_from(RefreshToken)) == 0
    clock['now'] = deadline
    assert attempt(client, password='admin-password').status_code == 200
    db_session.refresh(admin_user)
    assert admin_user.failed_login_attempts == 0 and admin_user.login_locked_until is None


def test_success_resets_consecutive_failure_count(client, db_session, admin_user, clock):
    for _ in range(4):
        assert attempt(client).status_code == 401
    assert attempt(client, password='admin-password').status_code == 200
    for _ in range(4):
        assert attempt(client).status_code == 401
    db_session.refresh(admin_user)
    assert admin_user.failed_login_attempts == 4 and admin_user.login_locked_until is None
    assert attempt(client, password='admin-password').status_code == 200


def test_failed_attempt_after_expiry_starts_new_sequence(client, db_session, admin_user, clock):
    for _ in range(5):
        attempt(client)
    clock['now'] += timedelta(minutes=15)
    assert attempt(client).status_code == 401
    db_session.refresh(admin_user)
    assert admin_user.failed_login_attempts == 1 and admin_user.login_locked_until is None
    for _ in range(4):
        attempt(client)
    db_session.refresh(admin_user)
    assert utc(admin_user.login_locked_until) == T0 + timedelta(minutes=30)


def test_block_is_account_specific_and_does_not_reveal_its_state(client, db_session, admin_user, viewer_user, clock):
    normal = attempt(client).json()
    for _ in range(4):
        attempt(client)
    assert attempt(client, password='admin-password').json() == normal
    assert attempt(client, email='missing@example.com').json() == normal
    assert attempt(client, email=viewer_user.email, password='viewer-password').status_code == 200
    db_session.refresh(viewer_user)
    assert viewer_user.failed_login_attempts == 0
    assert db_session.scalar(select(func.count()).select_from(User)) == 2


def test_inactive_account_remains_inactive_after_lock_expiry(client, db_session, admin_user, clock):
    admin_user.is_active = False
    db_session.commit()
    for _ in range(6):
        assert attempt(client, password='admin-password').status_code == 401
    clock['now'] += timedelta(minutes=16)
    assert attempt(client, password='admin-password').status_code == 401
    db_session.refresh(admin_user)
    assert not admin_user.is_active and admin_user.failed_login_attempts == 0


def test_lock_survives_new_database_session_and_is_audited_without_secrets(client, db_session, admin_user, clock):
    for _ in range(5):
        attempt(client)
    with Session(db_session.get_bind()) as independent:
        with pytest.raises(Unauthenticated):
            service.login(LoginRequest(email=admin_user.email, password='admin-password'), independent)
    locks = list(db_session.scalars(select(AuthAuditEvent).where(AuthAuditEvent.action == 'auth.login.locked')))
    assert len(locks) == 1 and locks[0].target_id == admin_user.id
    assert db_session.scalar(select(func.count()).select_from(AuthAuditEvent)
                             .where(AuthAuditEvent.action == 'auth.login.failed')) == 6
    assert not any(secret in str(locks[0].details) for secret in ['admin-password', 'wrong-password', admin_user.email])


def test_concurrent_failures_cannot_lose_counter_or_extend_existing_lock(tmp_path, clock):
    engine = create_engine(f'sqlite:///{tmp_path / "lockout.db"}',
                           connect_args={'check_same_thread': False, 'timeout': 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        role = Role(name='admin')
        db.add(User(email='race@example.com', hashed_password=hash_password('test-password'),
                    roles=[role], failed_login_attempts=4))
        db.commit()
    barrier = Barrier(2)
    def fail():
        with factory() as db:
            barrier.wait(timeout=5)
            with pytest.raises(Unauthenticated):
                service.login(LoginRequest(email='race@example.com', password='wrong-password'), db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: fail(), range(2)))
    with factory() as db:
        user = db.scalar(select(User))
        assert user.failed_login_attempts == 5
        assert utc(user.login_locked_until) == T0 + timedelta(minutes=15)
        assert db.scalar(select(func.count()).select_from(AuthAuditEvent)
                         .where(AuthAuditEvent.action == 'auth.login.locked')) == 1
    engine.dispose()
