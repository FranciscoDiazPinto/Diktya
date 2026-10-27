"""Límites ejecutables: evitan que futuros cambios vuelvan a acoplar dominios."""
import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect

from app.bootstrap import initialize_database
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {"auth", "chat", "networks", "tickets", "changes", "monitoring", "agents"}


def domain_sources():
    for domain in sorted(DOMAINS):
        for path in (ROOT / "app" / domain).rglob("*.py"):
            yield domain, path, ast.parse(path.read_text())


def test_domains_do_not_import_http_composition():
    for _, path, tree in domain_sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {"app.main", "app.routes", "app.lifecycle"}, str(path)
                if node.module == "app.bootstrap":
                    assert path.name == "cli.py", str(path)


def test_http_and_database_logic_stay_on_their_respective_layers():
    for _, path, tree in domain_sources():
        http_boundary = path.name in {"routes.py", "router.py", "support_router.py", "dependencies.py"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fastapi"):
                assert http_boundary, f"FastAPI fuera del adaptador: {path}"
            if http_boundary and path.name != "dependencies.py" and isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                assert name not in {"select", "query", "execute", "scalars", "scalar", "commit", "flush", "rollback"}, f"SQL/transacción en ruta: {path}:{node.lineno}"


def test_domains_do_not_import_other_domains_tables():
    for owner, path, tree in domain_sources():
        for node in ast.walk(tree):
            if owner != "auth" and isinstance(node, ast.Call) and node.args:
                first = node.args[0]
                if isinstance(first, ast.Name) and first.id == "User":
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    assert name not in {"get", "select", "query"}, f"User solo es identidad fuera de auth: {path}:{node.lineno}"
            if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith("app."):
                continue
            parts = node.module.split(".")
            if len(parts) >= 3 and parts[1] in DOMAINS and parts[1] != owner and parts[2] in {"models", "support_models"}:
                # User es el contrato de identidad de la sesión existente; las demás
                # tablas se consultan únicamente mediante el servicio propietario.
                assert node.module == "app.auth.models" and all(alias.name == "User" for alias in node.names), str(path)


def test_cli_import_does_not_load_fastapi_or_main():
    result = subprocess.run([sys.executable, "-c", "import sys; import app.auth.cli; assert 'app.main' not in sys.modules; assert 'fastapi' not in sys.modules"],
                            cwd=ROOT, env=dict(os.environ, DATABASE_URL="sqlite://", MONITORING_PROVIDER="mock"),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_production_startup_never_creates_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        initialize_database(Settings(_env_file=None, environment="production"), bind=engine)
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_production_startup_rejects_outdated_revision(tmp_path):
    from sqlalchemy import text
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('003_scoped_chat')"))
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        initialize_database(Settings(_env_file=None, environment="production"), bind=engine)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_production_starts_on_migrated_schema_without_changing_tables(tmp_path):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.auth.models import Role
    from app.auth.roles import RoleName

    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                            env=dict(os.environ, DATABASE_URL=url, ENVIRONMENT="production", MONITORING_PROVIDER="mock"),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    tables = inspect(engine).get_table_names()
    initialize_database(Settings(_env_file=None, environment="production"), bind=engine)
    assert inspect(engine).get_table_names() == tables
    with Session(engine) as db:
        assert set(db.scalars(select(Role.name))) == {role.value for role in RoleName}
    engine.dispose()


def test_admin_services_reject_unprivileged_actor_without_http(client, db_session, viewer_user):
    from app.auth import service as auth_service
    from app.networks import service as networks_service
    from app.core.errors import AccessDenied

    with pytest.raises(AccessDenied):
        auth_service.list_users(db_session, viewer_user)
    with pytest.raises(AccessDenied):
        networks_service.list_assignments(1, db_session, viewer_user)
