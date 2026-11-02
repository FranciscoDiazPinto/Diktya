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
5. Aplicar migraciones con `alembic upgrade head`.
6. Iniciar la API: `uvicorn app.main:app --reload`.

Para usar el chatbot, definir `OPENROUTER_API_KEY` y `OPENROUTER_MODEL` en el `.env` local. La clave se usa solo desde el backend; nunca debe incluirse en el frontend ni guardarse en Git. Sin esos valores, la API devuelve un error de servicio y no contacta a OpenRouter.

La entrada abre un chat de invitados sin cuenta. «Iniciar sesión · Equipo» lleva al login y, tras autenticarse, al dashboard. La atención temporal se limpia con confirmación o tras 60 segundos sin respuesta. La recuperación de expositores requiere confirmar un enlace enviado al correo registrado; conocer un contacto por sí solo no habilita credenciales. El portal de invitados solo publica redes abiertas de `GUEST_WIFI_NETWORK_IDS`; ver [autoatención y configuración QR](docs/atencion-invitados.md).

El dashboard estático puede servirse en otra terminal con `python3 -m http.server 5173 --directory frontend`. Iniciar sesión con un usuario `cliente`, `tecnico`, `operador`, `visor` o `admin`. Las conversaciones autenticadas se guardan en la base por usuario y se recuperan al iniciar sesión. Cliente y técnico acceden únicamente a redes asignadas; visor es un rol interno de monitoreo global.

La documentación interactiva de la API estará en `/docs` al iniciar el servidor.

Sin PostgreSQL se puede omitir `DATABASE_URL`: la API usa SQLite (`netbot.db`).

### Crear un usuario

`python -m app.auth.cli correo@dominio.cl contraseña --role admin --name "Nombre"`
(roles: `admin`, `tecnico`, `operador`, `cliente`, `visor`). Si el correo existe, actualiza su contraseña y rol.

### Dashboard

Servir la carpeta `frontend` en el puerto 5173 (origen permitido por CORS):
`python -m http.server 5173 --directory frontend` y abrir `http://localhost:5173`.

## Guía para contribuir

Leer [AGENTS.md](../AGENTS.md) y la [arquitectura modular](docs/arquitectura-modular.md) antes de editar. Los routers delegan en servicios propios; el chat consume contratos públicos. `main.py` compone HTTP, `lifecycle.py` gestiona recursos, `bootstrap.py` prepara roles/base y `model_registry.py` registra metadata. El frontend se divide en `frontend/modules/`; `app.js` solo lo arranca.

## Estructura

- `app/core`: configuración, seguridad, base de datos y logging.
- `app/auth`: usuarios, roles y permisos (Épica 001).
- `app/monitoring`: proveedores OPNsense/UniFi/mock, inventario, alertas y planos (Épica 002). Ver `docs/epica-002-monitoreo.md`.
- `app/chat`: asistente mediante OpenRouter, conversaciones privadas persistentes y políticas por rol.
- `app/networks`: registro local y asignación de acceso por red.
- `app/changes`: reservas VLAN locales confirmadas; ejecución real y rollback pendientes.
- `app/tickets`: tickets internos y de incidentes, criticidad, notificaciones y seguimiento (Épica 005). Ver `docs/soporte-cliente.md`.
- `app/agents`: espacio reservado; workers durables pendientes.
- `migrations`: historial de migraciones de Alembic.
- `docs`: ERS, diagramas PlantUML y decisiones de arquitectura.
- `tests`: pruebas automatizadas.

## Migraciones

La recuperación por contacto requiere la migración `006_network_recipients`. El administrador mantiene los contactos por red desde el dashboard, sin crear cuentas de cliente.

Crear una migración con `alembic revision --autogenerate -m "descripcion"`, revisarla y aplicarla con `alembic upgrade head` antes del arranque. Producción comprueba las revisiones de Alembic y no crea tablas automáticamente. Solo development/test conservan create_all como ayuda local. Bases heredadas con tablas creadas fuera de Alembic necesitan conciliar su estado antes de migrar.

## Monitoreo

Por defecto consulta las fuentes reales: definir las variables `OPNSENSE_*` y `UNIFI_*` en `.env`.
Sin credenciales la API arranca igual: la fuente figura como no configurada y el dashboard indica
qué falta, sin inventar datos. Si una fuente cae, se conserva el último dato conocido marcado como
desactualizado. `MONITORING_PROVIDER=mock` activa datos simulados solo si se pide de forma
explícita, y se rotulan como tales. Ver [la guía de la épica](docs/epica-002-monitoreo.md). La
migración `007_monitoring_inventory` crea las tablas de inventario, alertas y planos.

## Chatbot

El endpoint `POST /api/v1/chat/messages` requiere autenticación y `chat:use`. El servidor carga el historial persistente de la conversación y comprueba propietario, rol y ámbito antes de enviar contexto al proveedor. No acepta historial desde el navegador. Las herramientas se filtran por permisos y vuelven a autorizarlos antes de ejecutarse.

Clientes y técnicos solo pueden consultar su inventario asignado. El monitoreo global queda para visor/admin, y las reservas VLAN globales para admin. El soporte incluye acceso Wi-Fi protegido, diagnóstico parcial por interfaz y tickets persistentes. Las operaciones de escritura en UniFi siguen pendientes. Ver [configuración y límites del soporte](docs/soporte-cliente.md). Ver [roles, asignaciones, migración y contrato HTTP](docs/chat-roles-y-persistencia.md).

Las preguntas, el historial acotado y los resultados de monitoreo necesarios se procesan en OpenRouter para generar respuestas.

## Pruebas

`pip install -r requirements-dev.txt`, después `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Las pruebas incluyen límites modulares, contratos HTTP, aislamiento, arranque y controladores ES reales.
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

### Carga CSV

Admin puede validar la [plantilla y contrato CSV](docs/carga-csv.md), revisar filas y confirmar reservas locales. No crea SSIDs ni modifica infraestructura. Las cargas persisten por propietario y las vistas previas vencen. Producción requiere migración 005.

La rama chatbot incorpora planes SSID para admin/técnico, selección de AP y VLAN existentes y ejecutor optativo separado. Aplicar migración 007; consultar [configuración, confirmación y límites](docs/carga-csv.md#planes-ssid-por-chat-y-csv-rama-chatbot) antes de habilitar escrituras.

## Seguridad de despliegue y remediación de auditoría

- Producción: `ENVIRONMENT=production`, `JWT_SECRET_KEY` aleatoria de al menos 64 caracteres, algoritmos permitidos cerrados y orígenes CORS explícitos sin `null`/`*`. Generar la clave fuera de Git con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Un cambio de clave invalida JWT; ante exposición también revocar las sesiones existentes. Solo se admiten entornos development/test/production.
- Integraciones en producción: HTTPS y verificación TLS obligatoria, incluida la URL independiente de aprovisionamiento UniFi. Instalar una CA interna mediante los CA bundle; no desactivar verificación.
- PostgreSQL: Compose exige contraseñas configuradas y publica solo en loopback. El inicializador crea `netbot_app` sin privilegios administrativos ni propiedad del esquema. `DATABASE_URL` de la API debe usar ese rol. Ejecutar `alembic upgrade head` con una URL del propietario; después arrancar la API con su URL limitada. Codificar contraseñas correctamente en las URLs. El propietario sigue disponible exclusivamente para mantenimiento local.
- **Volúmenes existentes:** el script de inicialización solo corre en volúmenes vacíos. No borrar volúmenes. Rotar contraseñas existentes, aplicar el alta/permisos de `deploy/postgres/10-app-role.sh` mediante el propietario y cambiar la URL del servicio. Verificar que el rol de ejecución no sea superusuario, no posea tablas ni tenga CREATE sobre el esquema. No se corrigen privilegios de servidores externos mediante un push.
- SQLite activa claves foráneas en cada conexión, incluidos motores de pruebas/migración. Antes de actualizar una base existente ejecutar `PRAGMA foreign_key_check` y corregir referencias huérfanas; no ignorarlas. Las migraciones históricas se conservan. Solo la conexión de mantenimiento Alembic suspende FK durante batch: comprueba referencias antes/después y ejecuta DDL en una transacción explícita para conservar filas hijas. Ver [requisitos batch de Alembic](https://alembic.sqlalchemy.org/en/latest/batch.html#dealing-with-referencing-foreign-keys). Detener la API y respaldar antes de migrar; las conexiones de ejecución mantienen FK activas.
- Los tokens del navegador viven solo en memoria: no se guardan en localStorage, sessionStorage ni cookies. Se eliminan valores persistidos de versiones anteriores. Recargar exige login; una XSS activa seguiría siendo peligrosa, por lo que se conserva el escape de contenido externo.
- Un técnico sin permiso global de monitoreo no puede asociar IDs de dispositivos globales a tickets manuales. Continúa pudiendo crear los tickets permitidos sin esa asociación.
- Invitados: QR abierto explícito o recuperación de expositor mediante enlace de correo de un uso y cinco minutos. Administración, Marketing y Servicios están excluidas. Requiere finalidad `expositor`, SMTP y GUEST_EMAIL_RECOVERY_ENABLED/PUBLIC_URL; apagado por defecto. SMS/Telegram pendientes. Ver [autoatención](docs/atencion-invitados.md).
- `core/request_security.py` aplica ventanas de un minuto antes de autenticar o llamar al proveedor: login/refresh 10 por IP y 60 globales; nuevas sesiones invitadas 5 por IP y 120 globales; chat 10 por IP y 60 globales; identificación 5 por IP y 60 globales. Devuelve 429 y Retry-After y limita a 64 KiB el cuerpo recibido en esas rutas antes de analizar JSON. Los contadores son transaccionales y compartidos entre procesos del mismo equipo en `SECURITY_RATE_LIMIT_PATH` (por defecto `netbot-rate-limits.db`, permiso 0600). Comparten el mismo archivo absoluto y clave; no borrar o cambiar el archivo durante operación. Fallos del almacén rechazan con 503. Una IP no agota por sí sola el cupo global; detrás de NAT varios usuarios comparten cuota. Las sesiones invitadas aún requieren un worker por su almacenamiento en memoria.
- Instalación local/rack: usar un volumen local persistente para contadores, nunca NFS. Para réplicas en equipos distintos sustituir este almacén por un limitador centralizado; los archivos locales no comparten cuotas entre máquinas. Configurar el servidor ASGI para confiar cabeceras de proxy solo desde IPs del proxy propio, nunca desde cualquier origen. Limitar también tamaño de cuerpo/concurrencia en el proxy HTTPS. Un atacante con múltiples orígenes aún puede consumir la cuota global; el presupuesto limita consumo, no elimina toda denegación de servicio.
- La verificación Argon2 ocurre fuera del bloqueo global y revalida ID, hash, actividad, bloqueo y permisos antes de emitir sesión. El bloqueo persistente de cinco fallos/15 minutos permanece.
- Secretos, variantes `.env`, claves privadas, bases/copies y metadatos Finder se excluyen mediante `.gitignore` raíz. No se publican valores locales ni se reescribe el historial. Eliminar del índice no borra archivos locales.

Comprobar `/health`, login/logout, recarga de navegador, 429, QR abierto, rechazo de QR privado, certificados incorrectos y permisos reales del rol SQL antes de exponer una instalación. El frontend debe servirse por HTTPS en producción y dirigir `/auth`, `/admin` y `/api` a la API del mismo origen.
