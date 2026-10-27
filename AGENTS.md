# Guía de trabajo para desarrolladores y asistentes de IA

## Antes de modificar código

1. Leer `netbot/docs/arquitectura-modular.md`: describe el código actual y los contratos entre módulos.
2. Consultar `Arquitectura/LEEME_PRIMERO_ARQUITECTURA.md` para contexto y diseño futuro. Su sección histórica no demuestra que una función esté implementada.
3. Revisar `git status` y conservar cambios ajenos, documentos, `.DS_Store`, bases y secretos locales.
4. Trabajar en una rama de la tarea. Mantener el alcance solicitado por el usuario; no publicar ni integrar ramas como consecuencia automática de una refactorización.

## Límites del backend

- `main.py`, `routes.py`, `lifecycle.py`, `bootstrap.py` y `model_registry.py` son composición; ningún dominio importa `main`, `routes` o `lifecycle`.
- La CLI puede usar `bootstrap`; no debe cargar FastAPI ni la aplicación HTTP.
- Routers: contratos HTTP, autenticación, inyección y delegación. No SQL, commits, flush ni reglas de negocio.
- Servicios/casos de uso: validan permisos y ámbito, aplican reglas y controlan la transacción. También deben autorizar cuando se llaman sin HTTP.
- Cada módulo posee sus tablas. Entre módulos usar funciones públicas y schemas/DTOs; no importar modelos ni armar consultas sobre tablas ajenas.
- Excepción actual: `auth.models.User` es el contrato de identidad de la sesión. No extender esta excepción a otras tablas.
- Errores de aplicación en `core/errors.py`; traducción HTTP en `http_errors.py`. FastAPI pertenece a routers/dependencias/composición.
- La auditoría agregada por un colaborador no hace commit: confirma el caso de uso que posee la operación.
- Registrar nuevos modelos en `model_registry.py`; Alembic y el arranque usan ese registro. No modificar migraciones ya aplicadas: agregar otra.
- Producción requiere `alembic upgrade head` antes de arrancar. Solo development/test pueden usar create_all; no agregar creación automática de tablas a otros entornos.

## Seguridad y chat

- Identidad, roles, asignaciones e historial provienen del servidor. No confiar en IDs de propietario, permisos o historial enviados por navegador/modelo.
- Cliente: redes asignadas y tickets propios. Técnico/operador: redes y tickets asignados. Admin no obtiene acceso a conversaciones ajenas.
- Reautorizar después de esperas externas y antes de una escritura. Conservar controles de versión e idempotencia.
- Herramientas del LLM: consultar o preparar propuestas. Confirmar tickets/reservas por API; no convertir una propuesta en ejecución implícita.
- Credenciales Wi-Fi solo mediante la respuesta protegida; nunca en herramientas, historial, auditoría o localStorage. No leer/imprimir claves reales para depurar.
- Interfaz activa no prueba Wi-Fi ni Internet. Conservar estados parcial/desconocido y etiquetas de simulación.

## Frontend

- `frontend/app.js` solo arranca el compositor `modules/dashboard.mjs`.
- Cambiar la funcionalidad en su módulo: api, session, chat, monitoring, support, tickets, reservations o csv-imports.
- Cada controlador conserva su estado privado; solo identidad y época de sesión se comparten. Comunicar módulos mediante APIs/callbacks inyectados por el compositor.
- No crear un objeto global de negocio ni importar el compositor desde una funcionalidad.
- Usar el cliente de API compartido para autenticación/renovación. Ignorar resultados tardíos de otra sesión o selección.
- Mantener texto externo con textContent o escape explícito. Conservar limpieza y caducidad del panel de acceso Wi-Fi.

## Verificación y documentación

Desde `netbot/`:

```sh
.venv/bin/python -m pytest -q
node --test frontend/tests/*.test.mjs
```

`tests/test_architecture.py` comprueba límites, CLI independiente y arranque de producción. Las pruebas de interfaz importan módulos ES reales y cubren aislamiento de sesión y claves. Para cambios visuales, revisar también la interfaz en navegador.

Actualizar README y guías afectadas al cambiar contratos, permisos, módulos o arranque. Mantener rutas y comandos ejecutables. Los documentos de `docs/superpowers/specs` y `plans` son antecedentes históricos, no instrucciones vigentes para implementar sin revisar el estado actual.

Pendientes reales: UniFi, operaciones AP/SSID/VLAN, trabajos durables, verificación/compensación, administración por chat y aprovisionamiento CSV en UniFi. La validación CSV y reserva local están implementadas; consultar `netbot/docs/carga-csv.md`. No documentarlos como terminados.
