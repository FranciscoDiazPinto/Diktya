"""Criterios de cierre HU001/002/003, incluyendo invariantes concurrentes."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import jwt
import pytest
from fastapi.routing import APIRoute, APIRouter
from app import routes as composition
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import AuthAuditEvent, User, Role, RefreshToken
from app.auth.roles import DEFAULT_ROLES, RoleName, effective_permissions
from app.auth.schemas import UserCreate, UserUpdate
from app.auth.security import hash_password
from app.core.config import settings
from app.core.database import Base
from app.core.errors import Conflict
from app.main import app


def rows(db, action):
    return list(db.scalars(select(AuthAuditEvent).where(AuthAuditEvent.action == action)))


def test_login_failures_are_generic_audited_and_never_store_identifiers_or_secrets(client, db_session, admin_user):
    attempts = [(admin_user.email, 'wrong-password'), ('unknown@example.com', 'wrong-password')]
    responses = [client.post('/auth/login', json={'email': email, 'password': password}) for email, password in attempts]
    assert all(r.status_code == 401 for r in responses)
    assert responses[0].json() == responses[1].json() == {'detail': 'Invalid credentials'}
    admin_user.is_active=False;db_session.commit()
    inactive=client.post('/auth/login',json={'email':admin_user.email,'password':'admin-password'})
    assert inactive.status_code==401 and inactive.json()==responses[0].json()
    events = rows(db_session, 'auth.login.failed')
    assert len(events) == 3
    assert all(e.actor_id is None and e.outcome == 'failure' for e in events)
    assert all(len(e.details['subject_fingerprint']) == 64 for e in events)
    serialized = json.dumps([e.details for e in events])
    assert not any(email in serialized or password in serialized for email, password in attempts)


def test_sessions_are_independent_logout_revokes_access_and_rotation_has_one_winner(client, db_session, admin_user, login):
    first, headers = login(admin_user.email, 'admin-password')
    second, second_headers = login(admin_user.email, 'admin-password')
    assert len(rows(db_session, 'auth.login.succeeded')) == 2
    assert client.post('/auth/logout', json={'refresh_token': first.json()['refresh_token']}).status_code == 204
    assert client.get('/auth/me', headers=headers).status_code == 401
    assert client.get('/auth/me', headers=second_headers).status_code == 200
    rotated = client.post('/auth/refresh', json={'refresh_token': second.json()['refresh_token']})
    assert rotated.status_code == 200
    assert client.post('/auth/refresh', json={'refresh_token': second.json()['refresh_token']}).status_code == 401
    assert client.get('/auth/me', headers=second_headers).status_code == 401
    assert client.get('/auth/me', headers={'Authorization': 'Bearer '+rotated.json()['access_token']}).status_code == 200
    assert len(rows(db_session, 'auth.logout')) == 1
    for event in db_session.scalars(select(AuthAuditEvent)):
        assert first.json()['refresh_token'] not in json.dumps(event.details)
        assert rotated.json()['access_token'] not in json.dumps(event.details)


@pytest.mark.parametrize('mutation', [{'is_active':False}, {'roles':['visor']}])
def test_last_active_admin_cannot_be_disabled_or_demoted(client, db_session, admin_user, login, mutation):
    _, headers = login(admin_user.email, 'admin-password')
    response = client.patch(f'/admin/users/{admin_user.id}', headers=headers, json=mutation)
    assert response.status_code == 409
    db_session.refresh(admin_user)
    assert admin_user.is_active and [r.name for r in admin_user.roles] == ['admin']
    assert not rows(db_session, 'user.updated')
    assert client.get('/auth/me', headers=headers).status_code == 200


def test_user_changes_are_atomic_audited_and_old_sessions_never_revive(client, db_session, admin_user, viewer_user, login):
    _, admin = login(admin_user.email, 'admin-password')
    viewer_login, viewer = login(viewer_user.email, 'viewer-password')
    path = f'/admin/users/{viewer_user.id}'
    assert client.patch(path, headers=admin, json={'is_active':False}).status_code == 200
    assert client.get('/auth/me', headers=viewer).status_code == 401
    assert client.patch(path, headers=admin, json={'is_active':True}).status_code == 200
    assert client.get('/auth/me', headers=viewer).status_code == 401
    assert client.post('/auth/refresh', json={'refresh_token':viewer_login.json()['refresh_token']}).status_code == 401
    _, viewer = login(viewer_user.email, 'viewer-password')
    changed = client.patch(path, headers=admin, json={'password':'replacement-password', 'roles':['cliente']})
    assert changed.status_code == 200
    assert 'password' not in changed.text and 'hashed_password' not in changed.text
    assert client.get('/auth/me', headers=viewer).status_code == 401
    assert client.post('/auth/login', json={'email':viewer_user.email,'password':'viewer-password'}).status_code == 401
    assert client.post('/auth/login', json={'email':viewer_user.email,'password':'replacement-password'}).status_code == 200
    actions = [e.action for e in db_session.scalars(select(AuthAuditEvent))]
    assert {'user.deactivated','user.activated','user.roles_changed','user.password_changed','user.updated'} <= set(actions)
    assert all(e.target_id == viewer_user.id for e in rows(db_session,'user.updated'))
    assert 'replacement-password' not in json.dumps([e.details for e in db_session.scalars(select(AuthAuditEvent))])


def test_validation_identifies_fields_without_echoing_passwords_and_unknown_roles_do_not_partially_update(client, db_session, admin_user, viewer_user, login):
    _, headers = login(admin_user.email,'admin-password')
    duplicate = client.post('/admin/users', headers=headers, json={'email':admin_user.email,'password':'a-valid-password'})
    assert duplicate.status_code == 409 and 'email' in duplicate.json()['errors']
    weak = client.post('/admin/users', headers=headers, json={'email':'new@example.com','password':'weak'})
    assert weak.status_code == 422
    assert weak.json()['detail'][0]['loc'] == ['body','password']
    assert 'weak' not in weak.text
    assert client.patch(f'/admin/users/{viewer_user.id}', headers=headers, json={'full_name':'Should not persist','roles':['missing']}).status_code == 400
    db_session.refresh(viewer_user)
    assert viewer_user.full_name is None
    assert not rows(db_session,'user.updated')


def test_audit_is_admin_only_paginated_append_only_and_retains_users(client, db_session, admin_user, viewer_user, login):
    _, admin = login(admin_user.email,'admin-password')
    _, viewer = login(viewer_user.email,'viewer-password')
    assert client.get('/admin/auth-audit', headers=viewer).status_code == 403
    events = client.get('/admin/auth-audit?limit=1&offset=0', headers=admin)
    assert events.status_code == 200 and len(events.json()) == 1
    assert events.json()[0]['action'] == 'access.denied'
    assert events.json()[0]['actor_id'] == viewer_user.id
    assert events.json()[0]['details']['permission'] == 'auth:audit:read'
    assert 'no-store' in events.headers['cache-control']
    for statement in ['UPDATE auth_audit_events SET action=\'forged\'', 'DELETE FROM auth_audit_events', f'DELETE FROM users WHERE id={admin_user.id}']:
        with pytest.raises(IntegrityError):
            db_session.execute(text(statement))
        db_session.rollback()
    assert client.delete('/admin/auth-audit/1', headers=admin).status_code == 404


def test_expired_wrong_type_missing_session_and_role_claims_do_not_bypass_permissions(client, db_session, viewer_user, login):
    response, _ = login(viewer_user.email, 'viewer-password')
    payload = jwt.decode(response.json()['access_token'], options={'verify_signature':False})
    for change in [{'exp':datetime.now(timezone.utc)-timedelta(seconds=1)}, {'type':'refresh'}, {'sid':'x'*64}]:
        token = jwt.encode({**payload, **change}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        assert client.get('/auth/me', headers={'Authorization':'Bearer '+token}).status_code == 401
    forged_role = jwt.encode({**payload, 'roles':['admin']}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert client.get('/admin/users', headers={'Authorization':'Bearer '+forged_role}).status_code == 403
    assert rows(db_session,'access.denied')


def _permissions(dependant):
    permission = getattr(dependant.call, 'required_permission', None)
    result = {permission} if permission else set()
    for child in dependant.dependencies:
        result |= _permissions(child)
    return result


@pytest.mark.parametrize('role_name', list(RoleName))
def test_every_declared_http_permission_gate_matches_role_matrix(client, db_session, role_name):
    role = db_session.scalar(select(Role).where(Role.name == role_name.value))
    actor = User(email=f'matrix-{role_name.value}@example.com', hashed_password=hash_password('matrix-password'), roles=[role])
    db_session.add(actor);db_session.commit()
    response = client.post('/auth/login', json={'email':actor.email,'password':'matrix-password'})
    headers = {'Authorization':'Bearer '+response.json()['access_token']}
    allowed = effective_permissions(actor)
    tested = 0
    schema = app.openapi()["paths"]
    routers = [value for value in vars(composition).values() if isinstance(value, APIRouter)]
    for route in [route for router in routers for route in router.routes]:
        if not isinstance(route, APIRoute):
            continue
        required = _permissions(route.dependant)
        if not required:
            continue
        candidates = [path for path in (route.path, "/api/v1"+route.path) if path in schema]
        assert len(candidates) == 1, route.path
        path = candidates[0]
        for name in route.param_convertors:
            value = '00000000-0000-0000-0000-000000000001' if name in {'conversation_id','plan_id','import_id'} else '999999'
            path = path.replace('{'+name+'}',value)
        for method in route.methods - {'HEAD','OPTIONS'}:
            result = client.request(method,path,headers=headers,json={} if method in {'POST','PUT','PATCH'} else None)
            if not required <= allowed:
                assert result.status_code == 403,(role_name,method,path,result.text)
            else:
                assert result.status_code not in {401,403},(role_name,method,path,result.text)
            tested += 1
    assert tested >= 30


def test_two_admins_cannot_concurrently_remove_the_last_admin(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "concurrent.db"}', connect_args={'check_same_thread':False,'timeout':10})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        role = Role(name='admin');db.add(role);db.flush()
        users = [User(email=f'admin-{i}@example.com',hashed_password=hash_password('test-password'),roles=[role]) for i in range(2)]
        db.add_all(users);db.commit();ids=[u.id for u in users]
    barrier = Barrier(2)
    def demote(user_id):
        with Session(engine,expire_on_commit=False) as db:
            user=db.get(User,user_id);barrier.wait(timeout=10)
            try:
                service.update_user(user_id,UserUpdate(is_active=False),db,user)
                return 'ok'
            except Conflict:
                db.rollback();return 'protected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(demote,ids))
    assert sorted(results)==['ok','protected']
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) == 1
        assert len(rows(db,'user.deactivated')) == 1
    engine.dispose()


def test_cli_provisioning_uses_the_same_admin_guard_and_audit(db_session, admin_user):
    with pytest.raises(Conflict):
        service.provision_user(UserCreate(email=admin_user.email,password='new-password',roles=['visor']), db_session)
    db_session.rollback()
    new = service.provision_user(UserCreate(email='cli@example.com',password='cli-password',roles=['admin']),db_session)
    assert new.roles == ['admin']
    assert rows(db_session,'user.created')[-1].source == 'cli'


def test_denial_audit_never_commits_partial_business_writes(tmp_path):
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from app.auth.access import require_user_permission
    from app.auth.dependencies import get_current_user
    from app.auth.permissions import Permission
    from app.core.database import get_db
    from app.main import create_app
    engine = create_engine(f'sqlite:///{tmp_path / "denied.db"}', connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        role=Role(name='visor');db.add(role);db.flush()
        db.add(User(email='denied@example.com',hashed_password=hash_password('test-password'),roles=[role]));db.commit()
    test_app=create_app()
    def request_db():
        with Session(engine) as db:
            yield db
    test_app.dependency_overrides[get_db]=request_db
    @test_app.post('/test-denied')
    def denied(user=Depends(get_current_user),db=Depends(get_db)):
        user.full_name='must roll back';db.flush()
        require_user_permission(db,user,Permission.USERS_MANAGE)
    with TestClient(test_app) as client:
        tokens=client.post('/auth/login',json={'email':'denied@example.com','password':'test-password'}).json()
        assert client.post('/test-denied',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==403
    with Session(engine) as db:
        assert db.scalar(select(User)).full_name is None
        assert len(rows(db,'access.denied'))==1
    engine.dispose()


def test_failed_denial_audit_does_not_report_the_operation_as_recorded(client, viewer_user, login, monkeypatch):
    from app.auth import audit
    _,headers=login(viewer_user.email,'viewer-password')
    def fail(*args):
        raise RuntimeError('simulated database failure')
    monkeypatch.setattr(audit,'_persist_denials',fail)
    response=client.get('/admin/users',headers=headers)
    assert response.status_code==503
    assert response.json()=={'detail':'No fue posible registrar la operación de seguridad.'}


def test_first_cli_identity_must_be_an_active_admin(db_session):
    with pytest.raises(Conflict):
        service.provision_user(UserCreate(email='first@example.com',password='test-password',roles=['visor']),db_session)
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(User))==0
    assert service.provision_user(UserCreate(email='first@example.com',password='test-password',roles=['admin']),db_session).roles==['admin']


def test_simultaneous_refresh_never_creates_two_live_sessions(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path / "refresh.db"}',connect_args={'check_same_thread':False,'timeout':10})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Role(name='admin'));db.commit()
        service.provision_user(UserCreate(email='refresh@example.com',password='test-password',roles=['admin']),db)
        token=service.login(service.LoginRequest(email='refresh@example.com',password='test-password'),db).refresh_token
    barrier=Barrier(2)
    def refresh_once(_):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                service.refresh(service.RefreshRequest(refresh_token=token),db)
                return 'ok'
            except service.Unauthenticated:
                return 'revoked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(refresh_once,range(2)))==['ok','revoked']
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None)))==1
    engine.dispose()
