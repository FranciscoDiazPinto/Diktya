# Netbot

Base del proyecto Netbot: API con FastAPI, PostgreSQL y Alembic. El frontend queda pendiente de definir.

## Requisitos

- Python 3.11 o superior
- Docker y Docker Compose

## Inicio local

1. Crear el entorno: `python -m venv .venv` y activarlo.
2. Instalar dependencias: `pip install -r requirements.txt`.
3. Copiar `.env.example` a `.env` y ajustar la configuración local.
4. Iniciar PostgreSQL: `docker compose up -d db`.
5. Iniciar la API: `uvicorn app.main:app --reload`.

La documentación interactiva de la API estará en `/docs` al iniciar el servidor.

## Estructura

- `app/core`: configuración, seguridad, base de datos y logging.
- `app/auth`: usuarios, roles y permisos (Épica 001).
- `app/monitoring`: clientes UniFi/OPNsense y dashboard (Épica 002).
- `app/chat`: agente LLM, CSV y reservas de VLAN (Épica 003).
- `app/changes`: confirmación, ejecución y rollback (Épica 004).
- `app/tickets`: incidencias y notificaciones (Épica 005).
- `app/agents`: procesos en background (Épica 006).
- `migrations`: historial de migraciones de Alembic.
- `docs`: ERS, diagramas PlantUML y decisiones de arquitectura.
- `tests`: pruebas automatizadas.

## Migraciones

Crear una migración con `alembic revision --autogenerate -m "descripcion"` y aplicarla con `alembic upgrade head`.
