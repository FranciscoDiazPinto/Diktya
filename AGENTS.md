# Guía de trabajo para desarrolladores y asistentes de IA

## Antes de modificar código

1. Leer `netbot/docs/arquitectura-modular.md`: describe el código actual y los contratos entre módulos.
2. Consultar `Arquitectura/LEEME_PRIMERO_ARQUITECTURA.md` para contexto y diseño futuro. Su sección histórica no demuestra que una función esté implementada.
3. Revisar `git status` y conservar cambios ajenos, documentos, `.DS_Store`, bases y secretos locales.
4. Trabajar en una rama de la tarea. Mantener el alcance solicitado por el usuario; no publicar ni integrar ramas como consecuencia automática de una refactorización.

## Ramas y documentación de entrega

- Mantener pocos Markdown: actualizar secciones de las guías existentes y consolidar notas internas en `netbot/docs/contexto-desarrollo.md`. Crear un documento nuevo solo cuando tenga una finalidad independiente y duradera; no crear un MD por tarea, conversación o hallazgo. La estructura académica final aún no está definida: no reorganizar carpetas por suposición.

- Mantener las guías internas, incluido este archivo y `CLAUDE.md`, en el flujo de `dev`: editar en una rama de tarea e integrar a `dev`. No crear commits de instrucciones internas directamente en `main`.
- `main` corresponde a una entrega revisada. Antes de promover desde `dev`, consultar `netbot/docs/contexto-desarrollo.md#organizacion` y revisar el manifiesto de entrega conforme a la guía académica; no asumir que un merge separa automáticamente documentación interna y entregable.
- No excluir todos los Markdown. Conservar README, instalación, arquitectura, contratos, evidencias, licencias y declaraciones de herramientas/aportes requeridas. Clasificar por finalidad del documento, no por menciones a IA.
- No borrar archivos ya presentes en `main`, reescribir historial, reorganizar fases ni instalar filtros de exportación por esta instrucción. La estructura institucional exacta aún debe verificarse; preservar cambios y evidencias existentes.

## Contexto académico y referencia externa

- Este repositorio es el desarrollo académico; `diktya-atlas` es un producto independiente del autor para el cliente. Para integraciones, cambios de red o decisiones de arquitectura leer `netbot/docs/contexto-desarrollo.md#contexto`, `netbot/docs/contexto-desarrollo.md#integraciones` y `netbot/docs/contexto-desarrollo.md#continuidad`. La procedencia por archivo/símbolo está en `netbot/docs/contexto-desarrollo.md#evidencias`.
- Usar esa síntesis como conocimiento de interoperabilidad y casos que deben probarse. Implementar contratos propios en Python y verificar la API oficial de la versión objetivo; no portar ni traducir código, pruebas, prompts, migraciones o interfaz de la referencia, ni importarla como dependencia.
- No trasladar `.env`, claves, contactos, inventarios, direcciones, dominios operativos, planos o respaldos del cliente a este repo, fixtures, commits o prompts. La revisión documental no autoriza conectar equipos, ejecutar scripts de otro proyecto o alterar su despliegue.
- No heredar reglas operativas del cliente como arquitectura de Netbot. La referencia mezcla una integración histórica directa con una migración parcial a otra plataforma ATLAS; esa API no es una dependencia acordada del desarrollo académico.
- Separar código observado, pruebas inspeccionadas, validaciones históricas declaradas y objetivos pendientes. Un README, un mock que crea SSID o una nota de «validado en vivo» no demuestra la capacidad del cliente real ni su vigencia actual. Verificar contrato oficial y versión antes de habilitar escrituras; registrar por separado la validación de laboratorio.

## Próximo bloque: SSID, AP y VLAN existentes

- Alcance confirmado por el usuario: técnico/operador y admin podrán solicitar creación/modificación de SSID, elegir AP concretos y asociar **VLAN existentes** después del CSV. No crear VLAN nuevas, DHCP, NAT o reglas OPNsense en este bloque. Creación mediante planes, inventario y CLI implementada; edición, compensación y laboratorio pendientes; ver `netbot/docs/contexto-desarrollo.md#ssid`.
- El sitio, evento, AP, WLAN y Network/VLAN son recursos distintos. Una asignación a una red existente no concede implícitamente aprovisionamiento de todo el sitio. Diseñar autorización por recurso y revalidarla al preparar, confirmar y ejecutar, también tras esperas externas y cambios de rol.
- Herramientas LLM de consulta/propuesta; confirmación humana por API vinculada al actor y plan exacto; después trabajo durable, idempotente, con control de concurrencia, relectura y compensación por operación. No exponer al modelo herramientas que puedan encadenar por sí solas reserva/aplicación ni presentar «encolado» como «desplegado».
- La referencia usa Integration API de UniFi OS; su escritura real revisada solo reasocia WLAN y Network existentes. Crear SSID y elegir AP para el despliegue son desarrollo nuevo. No asumir versión exacta de Network, soporte de creación ni permisos por conocer el tipo histórico de consola.
- Comprobar listado frente a detalle, paginación, VLAN nativa/específica y difusión AP/tags; datos no resolubles permanecen desconocidos. No usar VLAN por defecto, difusión a todos los AP o Wi-Fi abierto como sustitutos silenciosos.
- Mantener TLS/CA, timeouts, secretos fuera del LLM y errores tipados del cliente OPNsense de Netbot. No reemplazarlo por el contrato Wi-Fi o los defaults de TLS del otro producto. Auto-remediación y reinicio/readopción automática no forman parte de este bloque.

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
- Invitados usan atención temporal y recuperación por contacto registrado fuera del LLM, sin permisos técnicos; conservar limpieza/expiración y aislamiento. La coincidencia correo/teléfono no equivale a OTP, voucher ni credencial individual. El registro de destinatarios requiere la migración 006; ver `netbot/docs/atencion-invitados.md`.
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

Pendientes reales: UniFi, creación/modificación de SSID y selección aplicada de AP con VLAN existentes, trabajos durables, verificación/compensación, administración por chat y aprovisionamiento CSV en UniFi. La validación CSV, reserva local y atención temporal/QR/recuperación por contactos están implementadas; consultar `netbot/docs/carga-csv.md` y `netbot/docs/atencion-invitados.md`. La síntesis de Atlas es documentación, no una integración implementada.

Estado SSID actual: consultar `netbot/docs/carga-csv.md` para ámbitos, migración 007, ejecutor separado y bloqueo de resultados inciertos. No confundir aprobación con despliegue ni pruebas simuladas con validación física.
