# Chat: roles, redes asignadas e historial privado

## Estado de esta entrega

Implementa los bloques 2 y 3 del plan: asignaciones a redes, aislamiento por usuario y persistencia de conversaciones. El almacenamiento usa SQLAlchemy y la base configurada en `DATABASE_URL` (PostgreSQL para despliegue; SQLite para desarrollo y pruebas).

No se habilitan todavía credenciales Wi-Fi, diagnóstico operativo por red, tickets ni operaciones UniFi. El inventario local no comprueba conectividad. Ninguna reserva local equivale a crear una VLAN o un SSID en la infraestructura.

## Roles efectivos

| Rol | Acceso actual por chat/API |
|---|---|
| cliente | Chat propio y resumen de redes asignadas (nombre, evento, SSID). Sin inventario técnico global, credenciales ni cambios. |
| tecnico | Chat propio y detalle técnico de redes asignadas. Operaciones AP/SSID/VLAN pendientes de integración y autorización por recurso. |
| operador | Nombre anterior del rol técnico; mismos límites que tecnico. |
| visor | Consulta interna del monitoreo global; no representa a un cliente final. |
| admin | Monitoreo global, reservas VLAN locales, gestión de usuarios/roles y registro/asignación de redes mediante API. Administración por chat pendiente. |

**Cambio de compatibilidad:** operador pierde `monitoring:read`, las reservas globales y los permisos generales de cambios/tickets. No se deben conservar permisos globales para simular acceso técnico acotado. Sus futuras operaciones deben validar las redes asignadas. Las reservas globales existentes siguen disponibles para admin. Visor conserva su significado interno; no asignarlo a clientes finales.

Los roles de una cuenta suman permisos. Asignar visor o admin a un cliente le concede expresamente capacidades adicionales; no existe un descenso automático por tener también cliente. Los permisos se leen de la base en cada solicitud, no de los roles contenidos en un JWT antiguo. Los permisos de roles personalizados siguen sin ser configurables: los roles conocidos se definen en código.

## Registro y asignación de redes

Primero crear usuarios con `POST /admin/users` y roles `cliente` o `tecnico`. El admin registra una red local con `POST /admin/networks`:

```json
{
  "name": "Stand A",
  "site": "evento-santiago",
  "event_name": "Feria",
  "external_id": "identificador-de-red-en-controlador",
  "ssid": "Stand-A",
  "vlan_tag": 20
}
```

Esto registra metadatos; **no escribe en UniFi ni OPNsense**. `site` + `external_id` identifica una red de forma única. No se reciben ni guardan contraseñas en este registro.

- `PUT /admin/networks/{network_id}/users/{user_id}`: asignar una red (idempotente).
- `DELETE /admin/networks/{network_id}/users/{user_id}`: revocar asignación.
- `GET /admin/networks/{network_id}/users`: listar los IDs de usuarios asignados; solo admin.
- `GET /api/v1/networks`: redes autorizadas de la cuenta; admin puede consultar todas.
- `GET /api/v1/networks/{network_id}`: red autorizada o 404. Cliente no recibe IDs de controlador ni VLAN.

No se asignan redes automáticamente por nombre, SSID, texto del chat o conocimiento de un ID. La herramienta `get_assigned_networks` recibe contexto filtrado por el servidor y no acepta parámetros para cambiar usuario o red.

## Contrato del chat

Crear conversación: `POST /api/v1/chat/conversations` con `{"network_id": 1}` o `{}` para las redes autorizadas de la cuenta. La red elegida debe estar autorizada. Su ámbito es inmutable.

Enviar mensaje: `POST /api/v1/chat/messages`:

```json
{
  "message": "¿Qué red tengo asignada?",
  "conversation_id": "uuid-devuelto-al-crear-la-conversacion",
  "version": 0
}
```

La respuesta incluye `answer`, `tools_used`, `reservation_proposal`, `conversation_id` y la nueva `version`. Si se omite conversation_id se crea una conversación nueva; para continuar una existente hay que enviar su ID. `version` permite detectar un navegador desactualizado antes de contactar al proveedor; el servidor también comprueba concurrencia al guardar aunque se omita.

El endpoint HTTP ya no acepta `history`, roles, permisos ni propietario enviados por el cliente (422). El historial para el modelo se obtiene de la base y se recorta según los límites de configuración. Se guardan mensaje y respuesta juntos; un fallo del proveedor no guarda un intercambio parcial. Las respuestas del modelo no conceden permisos.

- `GET /api/v1/chat/conversations?limit=100&offset=0`: conversaciones propias accesibles, más recientes primero.
- `GET /api/v1/chat/conversations/{id}?limit=100`: últimos mensajes en orden cronológico.
- `GET /api/v1/chat/conversations/{id}?limit=100&before_id={id_mensaje}`: página anterior.

El frontend recupera la última conversación al iniciar sesión, permite cambiar de conversación, comenzar una nueva y cargar mensajes anteriores. El selector muestra las 100 conversaciones más recientes; las restantes están disponibles por paginación de API. No guarda historial en localStorage.

## Aislamiento y cambios de acceso

Incluso admin recibe 404 al intentar leer o continuar una conversación ajena. No se ha concedido un permiso para inspeccionar chats de otros usuarios.

Cada conversación registra una huella de roles, permisos y redes accesibles. Cuando cambia ese conjunto, los chats del contexto anterior se conservan en la base pero se ocultan y no se envían al modelo. Esto es conservador: también un aumento de acceso exige iniciar un chat nuevo. Una conversación vuelve a ser accesible si se restablece exactamente el mismo contexto de autorización. No se elimina historial automáticamente.

Al completar la llamada al proveedor se vuelven a comprobar usuario activo y contexto de autorización. Una revocación durante la consulta descarta la respuesta (403). Dos respuestas concurrentes no sobrescriben el historial: la segunda actualización incompatible se rechaza con 409. Las herramientas actuales son de consulta o propuesta; antes de habilitar escrituras habrá que reautorizar también cada ejecución en la cola de trabajos.

Cerrar sesión o cambiar de cuenta invalida respuestas pendientes en la interfaz, limpia mensajes y propuestas visibles e impide que una renovación tardía sustituya tokens de otra cuenta. Las llamadas simultáneas comparten una sola renovación de token.

## Migración y validación

Con el backend detenido, ejecutar `alembic upgrade head` desde `netbot/` **antes de arrancar la nueva versión**. La migración `003_scoped_chat` crea redes/asignaciones/conversaciones/mensajes y los roles cliente/tecnico. El arranque de desarrollo también crea tablas faltantes con create_all, pero no sustituye el historial de Alembic; no ejecutar migraciones sobre tablas creadas previamente sin conciliar primero el estado de esa base.

No se ha aplicado la migración a la base local del usuario. Se verificó upgrade → downgrade a 002 → upgrade en una base temporal. El downgrade conserva los roles y sus asignaciones a usuarios.

Pruebas: `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Cubren acceso cruzado (incluido admin), APIs globales denegadas, contexto enviado al modelo, persistencia en una conexión nueva, revocaciones, errores del proveedor, concurrencia y respuestas tardías al cambiar de cuenta.

## Siguiente bloque

Atención al cliente con entrega protegida de acceso Wi-Fi propio, telemetría específica de su red y tickets persistentes. Después, operaciones técnicas UniFi con confirmación, ejecución durable, verificación y auditoría. La carga CSV queda para la etapa posterior acordada.
