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

El dashboard estático puede servirse en otra terminal con `python3 -m http.server 5173 --directory frontend`. Iniciar sesión con un usuario `cliente`, `tecnico`, `operador`, `visor` o `admin`. Las conversaciones se guardan en la base por usuario y se recuperan al iniciar sesión. Cliente y técnico acceden únicamente a redes asignadas; visor es un rol interno de monitoreo global.

La documentación interactiva de la API estará en `/docs` al iniciar el servidor.

Sin PostgreSQL se puede omitir `DATABASE_URL`: la API usa SQLite (`netbot.db`).

### Crear un usuario

`python -m app.auth.cli correo@dominio.cl contraseña --role admin --name "Nombre"`
(roles: `admin`, `operador`, `visor`). Si el correo existe, actualiza su contraseña y rol.

### Dashboard

Servir la carpeta `frontend` en el puerto 5173 (origen permitido por CORS):
`python -m http.server 5173 --directory frontend` y abrir `http://localhost:5173`.

## Estructura

- `app/core`: configuración, seguridad, base de datos y logging.
- `app/auth`: usuarios, roles y permisos (Épica 001).
- `app/monitoring`: clientes UniFi/OPNsense y dashboard (Épica 002). Ver `docs/epica-002-monitoreo.md`.
- `app/chat`: asistente mediante OpenRouter, conversaciones privadas persistentes y políticas por rol.
- `app/networks`: registro local y asignación de acceso por red.
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

El endpoint `POST /api/v1/chat/messages` requiere autenticación y `chat:use`. El servidor carga el historial persistente de la conversación y comprueba propietario, rol y ámbito antes de enviar contexto al proveedor. No acepta historial desde el navegador. Las herramientas se filtran por permisos y vuelven a autorizarlos antes de ejecutarse.

Clientes y técnicos solo pueden consultar su inventario asignado. El monitoreo global queda para visor/admin, y las reservas VLAN globales para admin. Las operaciones UniFi, credenciales Wi-Fi y tickets todavía están pendientes. Ver [roles, asignaciones, migración y contrato HTTP](docs/chat-roles-y-persistencia.md).

Las preguntas, el historial acotado y los resultados de monitoreo necesarios se procesan en OpenRouter para generar respuestas.

## Pruebas

`pip install -r requirements-dev.txt` y luego `pytest`.
# Reservas VLAN desde el chatbot

El chatbot puede preparar propuestas para reservar VLAN ya existentes para un administrador. En
`MONITORING_PROVIDER=opnsense`, Netbot consulta el inventario OPNsense de forma
read-only; en modo mock solo aparecen VLAN sintéticas para desarrollo. Ninguna
operación de reserva escribe configuración en OPNsense. El SSID se guarda como
metadato de Netbot y la liberación es manual por administrador.

La consulta de opciones está disponible para usuarios con `monitoring:read` en
`GET /api/v1/changes/vlan-options`. Las rutas `GET` y `POST
/api/v1/changes/vlan-reservations` y `POST
/api/v1/changes/vlan-reservations/{id}/release` requieren `vlan:reserve`
(rol admin). Preparar una propuesta en el chat no la persiste: el
usuario debe confirmarla explícitamente en el panel. Para propuestas, el texto
de chat, su historial y la información VLAN relevante se envían al proveedor
configurado en OpenRouter.
