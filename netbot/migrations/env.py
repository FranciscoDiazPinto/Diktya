from alembic import context
from sqlalchemy import engine_from_config, pool
from app.core.database import Base
from app.model_registry import register_models
from app.core.config import settings

register_models()

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Solo mantenimiento offline: batch recrea tablas y con CASCADE activo
            # borraría filas hijas. Validar antes, migrar atómicamente y validar después.
            if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("SQLite tiene referencias huérfanas; corregir antes de migrar")
            connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata,
                          **({"transactional_ddl": True} if sqlite else {}))
        try:
            with context.begin_transaction():
                if sqlite:
                    # sqlite3 en modo legacy no inicia transacción para DDL por sí solo.
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                context.run_migrations()
                if sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("La migración produjo referencias inválidas; rollback")
        finally:
            if sqlite:
                connection.rollback()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
