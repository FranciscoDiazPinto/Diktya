# Soporte al cliente: acceso Wi-Fi, estado y tickets

Esta entrega implementa el bloque de atención al cliente sobre las asignaciones y conversaciones privadas existentes. No aplica cambios a UniFi ni OPNsense. La ejecución de operaciones de red sigue en etapas posteriores del plan.

## Capacidades por rol

| Rol | Acceso |
|---|---|
| cliente | Revelar acceso Wi-Fi de sus redes asignadas, comprobar su estado disponible, preparar/confirmar tickets y consultar sus propios tickets. |
| tecnico / operador | Acceso y diagnóstico de redes asignadas; consulta y gestión de tickets de esas redes, incluidos los abiertos por sus clientes. |
| admin | Lo anterior para todas las redes; configuración local del soporte y consulta de auditoría. No obtiene acceso a chats ajenos. |
| visor | Conserva monitoreo global de lectura. No recibe acceso a claves Wi-Fi ni a tickets de clientes. |

Los roles suman permisos y las asignaciones acotan recursos. La identidad se obtiene de la sesión; las herramientas no aceptan un propietario elegido por el modelo. Revocar una red elimina también acceso a sus claves y tickets. El estado se reautoriza después de consultar la fuente de monitoreo.

## Configuración del acceso Wi-Fi

Las claves no se guardan en la base de datos. Configurarlas únicamente en el entorno privado del backend o mediante el mecanismo de inyección de secretos del despliegue. Nunca subir claves reales al repositorio.

`WIFI_ACCESS_CREDENTIALS_JSON` contiene un objeto por referencia opaca. Ejemplo de estructura, con un valor que debe reemplazarse en el entorno privado:

```json
{
  "stand-a": {
    "site": "evento-santiago",
    "external_id": "id-real-de-la-red",
    "ssid": "Stand-A",
    "security": "wpa2-personal",
    "passphrase": "CAMBIAR_EN_EL_ENTORNO"
  }
}
```

Valores admitidos de security: `wpa2-personal`, `wpa3-personal` y `open`. Para red abierta se omite passphrase. Se aceptan claves personales de 8–63 caracteres; para WPA2 también 64 dígitos hexadecimales. No se implementan todavía accesos Enterprise/RADIUS ni vouchers. No usar credenciales del controlador o firewall en este mapa.

El admin registra la red y sus asignaciones como se describe en [roles y persistencia](chat-roles-y-persistencia.md), y configura su referencia con:

`PUT /admin/networks/{network_id}/support`

```json
{"credential_ref": "stand-a", "monitoring_interface_id": "opt1"}
```

Este PUT reemplaza ambos campos; usar null para deshabilitar uno. `GET` en la misma ruta permite consultar la configuración. No se aceptan contraseñas en esta API. Antes de entregar acceso, el backend exige que site, external_id y SSID del secreto coincidan con la red registrada. Una referencia equivocada, un secreto mal formado o configuración ausente devuelve 503 sin divulgar los valores.

Los ajustes de entorno se cargan al arrancar; reiniciar el backend después de cambiar o rotar claves. Esta entrega no configura ni modifica secretos reales en el entorno del usuario.

## Entrega protegida

`POST /api/v1/networks/{network_id}/access` vuelve a comprobar permiso y asignación, registra `wifi_access.revealed` y devuelve SSID, security y passphrase. La respuesta tiene `Cache-Control: no-store, private` y `Pragma: no-cache`.

El modelo solo dispone de `offer_wifi_access`: devuelve una acción con network_id/SSID y nunca la clave. La interfaz revela el acceso fuera de los mensajes, lo oculta al minuto, al cambiar de red/conversación o al cerrar sesión, y descarta respuestas tardías de otra cuenta. No lo guarda en localStorage ni en el historial del chat.

El texto libre que el usuario escriba en chat, tickets o notas sí se procesa/persiste según ese flujo: no pegar contraseñas en esos campos. La protección descrita evita que el sistema envíe al LLM o persista las claves que entrega mediante el botón.

## Estado comprobable de la red

Definir `MONITORING_SITE_ID` igual al site de las redes atendidas por la instancia actual de monitoreo. La interfaz se vincula explícitamente por su `interface_id` lógico (por ejemplo opt1), no por coincidencias de nombre, SSID o número de VLAN.

`GET /api/v1/networks/{network_id}/status` devuelve solo el diagnóstico de la red autorizada. No entrega IPs, dispositivos, interfaces de otras redes ni resultados crudos del firewall.

| state | Significado |
|---|---|
| partially_verified | La interfaz asociada está activa; Wi-Fi e Internet aún no están verificados. |
| issue_detected | La interfaz asociada aparece caída; se puede solicitar revisión técnica. |
| unknown | Falta configuración, no corresponde el sitio/fuente, hay datos incompletos, ambiguos, antiguos o no disponibles. No significa caída confirmada. |

La lectura incluye checked_at, observed_at, source y simulated. Las lecturas mock se marcan como demostración. `NETWORK_STATUS_MAX_AGE_SECONDS` (60 por defecto) limita la antigüedad admisible; tampoco se acepta una fecha significativamente futura. Una interfaz activa o una concesión DHCP no demuestran que el SSID, un AP o Internet estén operativos. La verificación de esos componentes depende de la siguiente integración UniFi y de pruebas de conectividad adicionales.

Actualmente hay una sola instancia de monitoreo; redes de otros sitios quedan en estado unknown. No hay selección de URLs externas desde solicitudes del cliente.

## Tickets persistentes

El usuario puede reportar un problema aunque falte telemetría. Se guarda una comprobación del estado disponible al crear el ticket, identificada en la interfaz como una lectura histórica, junto con el solicitante y la red.

- `POST /api/v1/tickets`: crear ticket confirmado.
- `GET /api/v1/tickets?limit=50&offset=0&network_id=1&status=open`: listar tickets autorizados; filtros opcionales.
- `GET /api/v1/tickets/{id}`: detalle y seguimiento público.
- `PATCH /api/v1/tickets/{id}`: cambiar estado con nota; solo técnico asignado o admin.

Ejemplo de creación:

```json
{
  "network_id": 1,
  "summary": "No aparece mi red",
  "description": "Solicito revisión de conectividad.",
  "request_key": "uuid-generado-por-el-cliente"
}
```

El UUID real se genera en el navegador. Una misma request_key por usuario devuelve el mismo ticket en reintentos. Si se reutiliza con otros datos devuelve 409. No se acepta created_by_id ni estado inicial desde el cliente. Los clientes no pueden consultar tickets ajenos, incluso si comparten una red. Los técnicos solo pueden consultar y gestionar los tickets de redes que tengan asignadas.

Cambio de estado:

```json
{"status": "in_progress", "version": 0, "note": "Estamos revisando la conectividad."}
```

Transiciones: open → in_progress/resolved; in_progress → open/resolved; resolved → in_progress/closed; closed → open. Cada transición requiere versión vigente y nota, crea un evento y se audita. Un conflicto devuelve 409 y obliga a recargar. Las notas son visibles para el solicitante; no hay notas privadas en esta entrega.

En el chat, `prepare_support_ticket` devuelve una propuesta. El botón Crear ticket confirma mediante la API y solo entonces muestra el número creado. Cancelar no guarda nada. `list_support_tickets` consulta hasta cinco tickets autorizados dentro del ámbito de la conversación. El panel Tickets muestra los 50 más recientes; el resto está disponible por paginación de API.

Son tickets internos de Netbot; no se conecta una mesa de ayuda externa.

## Tickets de incidentes y notificaciones (Épica 005)

`tickets/agent.py` corre en el lifespan cada `TICKET_AGENT_INTERVAL_SECONDS`. Es una tarea en memoria de una instancia, no una cola durable. Convierte alertas activas en tickets, resuelve los que se normalizaron, escala los desatendidos y envía correos. Una alerta genera su ticket en un ciclo; sumado al colector de monitoreo queda dentro de los 2 minutos pedidos.

**Un incidente, un ticket.** Un índice único impide dos tickets sin cerrar con la misma clave. Un nuevo evento se anota en el ticket existente; si estaba resuelto, se reabre. Después de cerrado, una repetición abre otro ticket. `tickets.agent.open_incident()` es la entrada común: la Épica 004 puede usarla para verificación o rollback fallidos, aún sin conectar porque esa épica no existe.

**Criticidad.** Se clasifica por reglas, no con el LLM: son deterministas y comprobables.

| Tipo de incidente | Criticidad |
|---|---|
| `source_unavailable`, `rollback_failed` | Crítica |
| `device_offline`, `verification_failed` | Alta |
| `device_degraded`, `device_missing`, `source_degraded` | Media |

Un gateway o firewall fuera de línea es Crítica. Con `TICKET_MASS_INCIDENT_DEVICES` (3) o más incidentes del mismo tipo a la vez se sube un nivel. Un tipo sin regla queda en Media con `needs_review`. `TICKET_CRITICALITY_RULES_JSON` sustituye reglas: `{"device_offline":"critica"}`. La cantidad de usuarios afectados no entra en el cálculo: el inventario no la registra.

**Notificaciones.** Cada creación, escalamiento, reapertura o resolución se notifica a técnicos y administradores activos. Los tickets de una red solo llegan a administradores y técnicos asignados a ella, para no revelar datos de un cliente. La entrega interna se guarda junto con el ticket, así que un fallo de correo no la afecta. El correo requiere `SMTP_HOST`; sin él solo se notifica en la aplicación. Se reintenta con espera progresiva hasta `NOTIFICATION_EMAIL_MAX_ATTEMPTS`, se cancela si el usuario fue desactivado, y Alta y Crítica salen primero y se destacan. Cada entrega registra estado, intentos, envío y lectura.

**Seguimiento.** Un ticket abierto y sin responsable que supera su tiempo máximo reenvía la notificación y sube de criticidad. `TICKET_ATTENTION_MINUTES_JSON` lo define por criticidad: Crítica 15, Alta 30, Media 120 y Baja 480 minutos. Si la alerta se normaliza, el ticket pasa a Resuelto y espera el cierre de un técnico. Cerrar exige un motivo de al menos 5 caracteres.

**Acceso.** Los tickets de infraestructura no pertenecen a una red: técnicos y administradores los gestionan, y `visor` (Supervisor de Evento) los consulta en modo lectura mediante `monitoring:read`. Los clientes no los ven. No se agregaron permisos, porque un permiso nuevo cambiaría la huella de autorización y ocultaría conversaciones existentes.

| Endpoint | Función |
|---|---|
| `GET /api/v1/tickets?status=&criticality=&assignee_id=&network_id=` | Listado con filtros. |
| `POST /api/v1/tickets/manual` | Ticket de técnico o administrador; red y dispositivo opcionales. |
| `POST /api/v1/tickets/{id}/assign` | Autoasignación, con `version`. |
| `POST /api/v1/tickets/{id}/comments` | Comentario, sin cambiar el estado. |
| `PATCH /api/v1/tickets/{id}/criticality` | Ajuste con motivo; quita `needs_review`. |
| `GET /api/v1/notifications` | Bandeja propia y cantidad sin leer. |
| `POST /api/v1/notifications/{id}/read` | Marca como leída, solo la propia. |

La migración `008_ticket_incidents` agrega columnas a tickets y la tabla `notifications`. Revertirla borra los tickets de infraestructura, que no caben en el esquema anterior. Enviar correo no se ha probado contra un servidor SMTP real.

## Auditoría y migración

El admin puede consultar `GET /admin/networks/{network_id}/support-audit?limit=50&offset=0`. Se registran actor, red, acción y fecha para configuración de soporte, entrega de acceso, creación y cambios de estado de tickets. Las claves no forman parte de la auditoría. El detalle de seguimiento de cada ticket conserva además el actor internamente, estado y nota de cada evento.

Con el backend detenido, aplicar `alembic upgrade head` antes de arrancar la nueva versión. La migración 004 crea network_support_config, support_audit, tickets y ticket_events. Se verificó upgrade → downgrade a 003 → upgrade en SQLite temporal y generación de DDL PostgreSQL sin conexión; no se aplicó a la base del usuario ni se probó contra hardware real.

Validación: `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Incluye aislamiento, revocación durante diagnóstico, idempotencia, transiciones, estado parcial/desconocido, claves fuera del contexto LLM y descarte de respuestas tardías.

## Mantenimiento modular

Ver [arquitectura vigente](arquitectura-modular.md) antes de extender este flujo. Autorización en auth/access y networks/access; diagnóstico en networks/diagnostics; claves en networks/credentials; consultas de tickets en tickets/service. El chat usa esos contratos, no sus tablas. Los errores públicos se traducen a HTTP en una frontera común. No se modificó el esquema SQL ni el contrato público por esta reorganización.

La migración 009 amplía la configuración de soporte con `unifi_site_id` y `unifi_ap_ids`, ambos administrables solo por admin. La vista técnica `/api/v1/networks/{id}/telemetry` exige `networks:read:details`, asignación vigente y vinculación explícita; clientes e invitados no pueden consultar AP. Se conservan estados antiguos marcados y no se usan para afirmar disponibilidad actual. Ver [monitoreo por red](epica-002-monitoreo.md#api-y-autorización).
