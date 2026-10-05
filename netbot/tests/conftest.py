import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-auth.db")
os.environ.setdefault("JWT_SECRET_KEY", "a-test-secret-key-that-is-long-enough")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import Role, User
from app.auth.roles import DEFAULT_ROLES
from app.auth.security import hash_password
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    for role_name, role_definition in DEFAULT_ROLES.items():
        session.add(Role(name=role_name.value, description=role_definition.description))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user(db_session):
    role = db_session.query(Role).filter_by(name="admin").one()
    user = User(email="admin@example.com", hashed_password=hash_password("admin-password"), roles=[role])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def viewer_user(db_session):
    role = db_session.query(Role).filter_by(name="visor").one()
    user = User(email="viewer@example.com", hashed_password=hash_password("viewer-password"), roles=[role])
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture()
def login(client):
    def do_login(email, password):
        response = client.post("/auth/login", json={"email": email, "password": password})
        return response, {"Authorization": f"Bearer {response.json()['access_token']}"}

    return do_login
