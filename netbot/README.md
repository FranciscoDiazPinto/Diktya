# Netbot

Netbot combina una API con FastAPI, PostgreSQL y Alembic con un dashboard web estático. Incluye autenticación, monitoreo de red y un asistente conversacional conectado a OpenRouter.

## Requisitos

- Python 3.11 o superior
- Docker y Docker Compose

## Inicio local

1. Crear el entorno: `python3 -m venv .venv` y activarlo con `source .venv/bin/activate`.
2. Instalar dependencias: `pip install -r requirements.txt` (para pruebas: `requirements-dev.txt`).
3. Copiar `.env.example` a `.env` y ajustar la configuración local.
4. Iniciar PostgreSQL: `docker compose up -d db`.
5. Iniciar la API: `uvicorn app.main:app --reload`.

Para usar el chatbot, definir `OPENROUTER_API_KEY` y `OPENROUTER_MODEL` en el `.env` local. La clave se usa solo desde el backend; nunca debe incluirse en el frontend ni guardarse en Git. Sin esos valores, la API devuelve un error de servicio y no contacta a OpenRouter.

El dashboard estático puede servirse en otra terminal con `python3 -m http.server 5173 --directory frontend`. Iniciar sesión con un usuario `visor`, `operador` o `admin` para acceder al asistente. El historial del chat vive en memoria durante la sesión del navegador.

La documentación interactiva de la API estará en `/docs` al iniciar el servidor.

## Estructura

- `app/core`: configuración, seguridad, base de datos y logging.
- `app/auth`: usuarios, roles y permisos (Épica 001).
- `app/monitoring`: clientes UniFi/OPNsense y dashboard (Épica 002). Ver `docs/epica-002-monitoreo.md`.
- `app/chat`: asistente de monitoreo mediante OpenRouter (Épica 003; solo lectura en esta entrega).
- `app/changes`: confirmación, ejecución y rollback (Épica 004).
- `app/tickets`: incidencias y notificaciones (Épica 005).
- `app/agents`: procesos en background (Épica 006).
- `migrations`: historial de migraciones de Alembic.
- `docs`: ERS, diagramas PlantUML y decisiones de arquitectura.
- `tests`: pruebas automatizadas.

## Migraciones

Crear una migración con `alembic revision --autogenerate -m "descripcion"` y aplicarla con `alembic upgrade head`.

## Monitoreo sin hardware

Por defecto `MONITORING_PROVIDER=mock`: la API sirve datos simulados y coherentes en
`/api/v1/monitoring/{system,interfaces,clients,firewall/stats,firewall/events}`. Para usar
OPNsense real, definir `MONITORING_PROVIDER=opnsense` y las variables `OPNSENSE_*` en `.env`.

## Chatbot

El endpoint `POST /api/v1/chat/messages` requiere autenticación y el permiso `CHAT_USE`. Los roles predeterminados `visor`, `operador` y `admin` pueden consultar monitoreo en lenguaje natural. Las herramientas del modelo son de solo lectura y el backend vuelve a comprobar `MONITORING_READ` antes de ejecutarlas. El chatbot no reserva VLAN ni aplica cambios de red.

Las preguntas, el historial acotado y los resultados de monitoreo necesarios se procesan en OpenRouter para generar respuestas.

## Pruebas

`pip install -r requirements-dev.txt` y luego `pytest`.
