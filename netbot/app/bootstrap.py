"""Preparación de base/roles para API y CLI; no importa main ni FastAPI."""
from pathlib import Path
from alembic.script import ScriptDirectory
from sqlalchemy import select, inspect, text
from sqlalchemy.orm import Session
from app.core.config import get_settings, Settings
from sqlalchemy.engine import Engine
from app.core.database import Base, engine
from app.model_registry import register_models
from app.auth.models import Role, User
from app.auth.roles import DEFAULT_ROLES
from app.auth.security import hash_password

def initialize_database(config: Settings | None = None, bind: Engine | None = None) -> None:
    """Preparación explícita. Producción exige migraciones previas; nunca create_all."""
    config = config or get_settings()
    bind = bind or engine
    register_models()
    if config.environment in {"development", "test"}:
        Base.metadata.create_all(bind=bind)
    else:
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))
        if not inspect(bind).has_table("alembic_version"):
            raise RuntimeError("La base debe migrarse antes del arranque: alembic upgrade head")
        with bind.connect() as connection:
            versions = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
        if versions != set(scripts.get_heads()):
            raise RuntimeError("La base debe migrarse antes del arranque: alembic upgrade head")
    db = Session(bind)
    try:
        for role_name, role_definition in DEFAULT_ROLES.items():
            role = db.scalar(select(Role).where(Role.name == role_name.value))
            if role is None:
                db.add(Role(name=role_name.value, description=role_definition.description))
            else:
                role.description = role_definition.description
        db.commit()
        if config.admin_email and config.admin_password and not db.scalar(
            select(User).where(User.email == config.admin_email.lower())
        ):
            admin_role = db.scalar(select(Role).where(Role.name == "admin"))
            db.add(User(email=config.admin_email.lower(), hashed_password=hash_password(config.admin_password), roles=[admin_role]))
            db.commit()
    finally:
        db.close()
