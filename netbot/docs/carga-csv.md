# Carga CSV: validación y reservas locales

Estado: primera etapa de la épica 003 implementada en `feature/chatbot`. La ejecución sobre UniFi pertenece a la siguiente etapa; confirmar un CSV solo crea reservas locales de VLAN ya existentes en el inventario.

## Formato y uso

Descargar [la plantilla](../frontend/examples/ssid-reservas.csv) desde el panel del asistente, disponible para admin con permiso `vlan:reserve`. Técnico, operador, visor y cliente no acceden a esta operación global. Cada carga es privada de su propietario, incluso frente a otros administradores.

Columnas obligatorias, sin adicionales: `parent_interface,tag,event_name,purpose,ssid`. Se admite otro orden, UTF-8 con o sin BOM, coma o punto y coma, campos entre comillas y líneas vacías. `tag` debe ser un entero entre 1 y 4094; el SSID ocupa entre 1 y 32 bytes UTF-8. No incluir contraseñas ni columnas de seguridad. Los duplicados de interfaz/VLAN o SSID dentro del archivo invalidan todas sus filas afectadas.

1. Subir el archivo con **Validar CSV**. Se validan estructura, valores, existencia en inventario y reservas activas. No se reservan VLAN en este paso.
2. Revisar los errores por fila y seleccionar las filas válidas deseadas.
3. Confirmar explícitamente. El servidor reautoriza, consulta el inventario mediante el servicio de monitoreo y vuelve a comprobar conflictos. Su caché puede reutilizar datos dentro del límite de antigüedad configurado.
4. Todas las filas seleccionadas se reservan en una transacción o ninguna. Un conflicto exige validar de nuevo. Repetir la confirmación de la misma carga y selección devuelve las reservas originales, sin duplicarlas; otra selección devuelve 409.

La vista previa vence por defecto a los 15 minutos y puede cancelarse. Cerrar sesión no la cancela: se recupera desde Cargas anteriores en la misma cuenta. Confirmar no reserva las filas omitidas. Para cambiar el contenido o añadir filas omitidas, validar un nuevo archivo. Cambiar el contexto del proveedor/sitio impide confirmar la vista anterior. Con inventario indisponible se rechazan las filas que requieren validarlo.

## API y persistencia

Base `/api/v1/changes/csv-imports`:

- `GET /options`: límites; `GET /`: cargas propias, paginadas con limit/offset.
- `POST /?filename=archivo.csv`: cuerpo crudo `text/csv` (también application/csv u octet-stream), devuelve vista previa 201.
- `GET /{id}`: detalle propio.
- `POST /{id}/confirm`: JSON `{"row_numbers":[2,3]}`; números de línea inicial, incluida cabecera. Campos adicionales rechazados.
- `POST /{id}/cancel`: cancela una vista previa sin crear reservas.

El dominio changes posee `CsvImport`, el parser puro y el servicio transaccional. La migración `005_csv_imports` agrega la tabla; en producción ejecutar `alembic upgrade head` antes de arrancar. No aplicar stamp a una base antigua sin conciliar su esquema.

Se conservan filas normalizadas y resultados, no el archivo original. El CSV no se envía al LLM ni a localStorage. La caducidad bloquea confirmaciones, no elimina automáticamente los registros: una política de retención/purga sigue pendiente.

Variables opcionales y valores predeterminados:

| Variable | Valor | Función |
|---|---:|---|
| CSV_MAX_BYTES | 1048576 | Límite del cuerpo, incluso sin Content-Length |
| CSV_MAX_ROWS | 500 | Filas no vacías |
| CSV_PREVIEW_TTL_SECONDS | 900 | Vigencia de vista previa |
| CSV_INVENTORY_MAX_AGE_SECONDS | 60 | Antigüedad máxima aceptada del inventario |

## Próxima etapa y contrato UniFi

Este formato es un contrato de Netbot, no una importación nativa de UniFi. La documentación oficial distingue [redes y VLAN](https://developer.ui.com/network/v10.6.106/createnetwork) de [Wi-Fi broadcasts](https://developer.ui.com/network/v10.6.106/getwifibroadcastpage). Antes de ejecutar cambios hay que validar versión/capacidades del controlador objetivo, sitio, correspondencia de interfaces y redes, seguridad mediante referencia a secretos y SSIDs existentes. Hoy solo se detectan SSIDs duplicados dentro del archivo; no se garantiza unicidad global en UniFi.

El adaptador, los planes, el trabajo durable, la autorización por recurso al ejecutar, la verificación, la compensación y los resultados por operación están implementados (ver las dos secciones siguientes) y pendientes de validación en laboratorio. No convertir la confirmación en una llamada directa desde una herramienta del LLM.

## Verificación

Desde netbot: `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Las pruebas cubren parser, autorización, propiedad, expiración, selección, reintentos y rollback de lotes. No sustituyen pruebas con un controlador real.


## Planes SSID por chat y CSV (rama chatbot)

Admin y técnico/operador pueden preparar creaciones de SSID sobre VLAN existentes, seleccionando AP explícitos. El administrador configura ámbitos por `POST /api/v1/changes/wifi-scopes` (consultar el prefijo vigente en `/docs`): sitio UniFi, evento, AP autorizados, correspondencias Network ID ↔ interfaz/tag OPNsense, perfiles de seguridad y usuarios autorizados. La concesión no deriva de la asignación a una red de soporte. El panel carga únicamente recursos autorizados presentes en ambos inventarios.

Las herramientas del chat consultan ámbitos/opciones y proponen; no escriben infraestructura ni confirman planes. El usuario prepara y confirma desde el panel. Los planes privados persisten con revisión, caducidad, filas seleccionadas y resultados. El CSV SSID conserva `parent_interface,tag,event_name,purpose,ssid`; AP y perfil se eligen explícitamente en el panel. Es independiente de la reserva CSV local previa, que continúa restringida a admin.

Aplicar `alembic upgrade head` (migración 007). Configuración en `.env.example`: `UNIFI_INVENTORY_MODE=mock` permite ensayar propuestas, nunca escribir. En modo `api`, configurar prefijo HTTPS completo, API key y CA si corresponde; inventario paginado y secretos solo en servidor. La ejecución requiere inventarios reales, `UNIFI_WRITE_ENABLED=true`, `UNIFI_API_CONTRACT=10.6.106` y perfiles WPA2 personales privados. El ejecutor verifica `/info` antes de crear y rechaza versiones diferentes; no se presupone la versión por la URL de Atlas. Contrato público: https://developer.ui.com/network/v10.6.106/createwifibroadcast .

Ejecutar explícitamente `python -m app.agents.cli` desde el backend con su entorno configurado (`python -m app.changes.cli` se conserva como alias de una pasada). Confirmar registra aprobación; no inicia un worker en el proceso web. El ejecutor revalida permisos, ámbito, inventario y vigencia, reclama el plan y bloquea simultaneidad por sitio/SSID. Conserva identificador remoto y compara la configuración leída después de crear. `completed` indica configuración coincidente en el controlador: no demuestra difusión efectiva en AP ni conexión a Internet.

Un resultado ambiguo queda `uncertain` con bloqueo durable; una interrupción puede dejar `executing`. No se reintenta: se concilia leyendo el controlador (sección siguiente). Aún no hay edición de SSID existentes en lote ni validación en hardware real. No declarar cerrada la épica de ejecución/verificación completa por estas pruebas locales. La implementación es propia, basada en el contrato público; no incorpora código, direcciones ni secretos de Atlas.


## Excel de feria

En **Aprovisionamiento → Planes de SSID por ámbito**, selecciona el ámbito,
los AP y el perfil de seguridad. Carga el XLSX y pulsa **Revisar propuestas
del archivo**. El archivo admite hasta 1 MiB y usa los límites de filas de
la carga CSV. La API `POST /api/v1/changes/ssid-plans/xlsx` recibe
`scope_id`, `ap_ids`, `security_profile` y `xlsx_base64`.

- La hoja **Histórico** debe tener los encabezados **Evento**, **WiFi / SSID**
  y **N° Vlan** en la primera fila. Las filas sin SSID se omiten.
- Cada VLAN debe identificar una sola red autorizada y existente en el ámbito.
  Se rechazan los SSID repetidos, fuera de evento o ya existentes. La vista previa
  conserva el número de fila de Excel.
- La selección de AP y el perfil del panel se aplican a todas las filas.
  El importador omite contactos, claves y columnas de AP, velocidad y cableado.
  El archivo solo se procesa en memoria. Se guardan las propuestas y errores,
  y solo las filas seleccionadas pasan a aprobación explícita.

## Ejecución, verificación y recuperación

Vigente desde el 14-11-2026 para los tres trabajos que ejecuta el worker (`python -m app.agents.cli`): creación de SSID, cambio de VLAN de un SSID existente y reinicio de un equipo. Todo se probó con controladores simulados.

| Trabajo | Endpoints (`/api/v1/changes`) | Verificación | Si falla |
|---|---|---|---|
| Creación SSID | `ssid-plans` (+`/csv`, `/confirm`, `/cancel`) | Relectura de nombre, red, AP exactos, bandas y tipo de seguridad | Se elimina el SSID creado por ese trabajo. El lote se detiene en la primera falla y conserva las filas ya verificadas (`partial`). |
| Cambio de VLAN | `ssid-vlan-change-plans` (+`/{id}`, `/confirm`, `/cancel`) | Relectura de identidad y red destino | Se restaura la red anterior (`rolled_back`). Si no se aplicó, `failed` sin tocar nada. |
| Reinicio | `device-restart-plans` (+`/{id}`, `/confirm`, `/cancel`) | Espera acotada hasta ver el equipo en línea tras una caída observada o un uptime menor | No se deshace: `failed` y ticket si no vuelve; `uncertain` y bloqueo si sigue en línea sin evidencia de reinicio. |

Reglas comunes:

- **Confirmación**: vinculada al actor y a la `revision` exacta mostrada. Repetirla devuelve el mismo plan; un plan vencido, cancelado o alterado no se ejecuta.
- **Autorización**: se revalida al preparar, confirmar, tomar el trabajo e inmediatamente antes de escribir. Revocar el ámbito bloquea un trabajo aún no ejecutado. El técnico solo reinicia AP de su ámbito; gateway, firewall o equipos que no se acreditan como AP exigen administrador.
- **Exclusión**: bloqueo durable por sitio y SSID, por red VLAN de destino, o por equipo. Un resultado incierto conserva la exclusión del SSID y de su VLAN hasta la conciliación. Ejecución y conciliación del mismo plan comparten además una exclusión entre procesos, independiente de sus commits: un trabajo activo no se recupera aunque lleve mucho tiempo. PostgreSQL requiere conexión directa o pooling de sesión; SQLite usa `flock` local en Unix junto a la base.
- **Cambio de VLAN**: el contrato 10.6.106 solo ofrece `PUT`. Se reenvía el detalle leído sin `id` ni `metadata`, cambiando únicamente la red. Si el controlador entrega la clave censurada o sin seguridad, no se escribe.
- **Precondiciones**: la creación requiere una VLAN existente que coincida en los inventarios de OPNsense y UniFi, y AP autorizados con estado `ONLINE`. La aprobación se invalida si cambia el inventario antes de que el worker tome el trabajo. Para el cambio de VLAN, cuando UniFi devuelve AP explícitos, se comprueba su estado y se vincula su selección a la aprobación. Si UniFi no identifica AP explícitos, la vista previa lo indica. El reinicio exige que el equipo siga coincidiendo con el plan y esté en línea antes de enviar la orden.
- **Prueba de servicio**: el inventario confirma la asociación de VLAN y el estado del AP. La conectividad del trayecto hasta el gateway requiere verificar en terreno que un cliente se asocie, reciba IP y llegue al servicio esperado.
- **Estados inciertos**: una escritura ambigua nunca se repite. Primero se lee el controlador: si el cambio quedó aplicado y verifica, se da por completado; si no se aplicó, `failed`; si otro actor cambió el recurso, `uncertain` sin sobrescribirlo. `uncertain` y `rollback_failed` conservan el bloqueo.
- **Conciliación**: `POST /api/v1/changes/reconcile/{ssid|vlan|restart}/{id}` (solo `networks:manage`) o `python -m app.agents.cli reconcile …`. Solo lee. El worker concilia los `executing` antiguos desde `execution_started_at` y únicamente si consigue su exclusión; la API también rechaza conciliar un plan activo. En un reinicio, un uptime menor que el previo acredita el resultado; estar en línea sin esa evidencia permite liberar el recurso como `unverified`, nunca como reinicio verificado, y no repite la orden.
- **Aprobaciones**: las vencidas salen de la cola como `expired` con auditoría; un rechazo definitivo previo a ejecutar pasa a `rejected` y exige preparar otra propuesta. Un plan ocupado por otro ejecutor conserva su aprobación hasta que pueda tomarse o venza.
- **Escalamiento**: verificación fallida o resultado incierto abren un ticket de criticidad Alta; un rollback fallido, Crítica; un equipo que no vuelve, Alta.
- **Mantenimiento**: durante un reinicio confirmado no se alerta la caída esperada de ese equipo. La ventana vence sola.
- **Reservas**: al confirmar una fila de alta o un cambio individual de VLAN, se guarda el ID de la reserva vigente del mismo actor, evento, SSID e interfaz/VLAN, si existe. El worker comprueba ese ID antes de escribir y marca la reserva como `assigned` al verificar la configuración. Si la reserva vinculada se libera, vence o se reemplaza, la fila se detiene antes de enviar el cambio. Una reserva vigente de otro cambio bloquea la confirmación y la ejecución. Si aparece una reserva después de la confirmación, el plan requiere una nueva revisión. Los planes sobre una VLAN sin reserva conservan el flujo existente sin asignación automática. El cambio individual requiere la migración `023_vlan_change_reservation`. El cierre de feria y la liberación coordinada siguen pendientes.

`completed` significa configuración coincidente en el controlador. No demuestra difusión efectiva, conectividad Wi-Fi ni Internet. Antes de habilitar `UNIFI_WRITE_ENABLED` hay que validar en laboratorio la versión del controlador, el `PUT` de actualización, la acción `RESTART` y qué devuelve el detalle de seguridad.

Para actualizar a `021_execution_ownership`, detener la API y todos los workers, respaldar y ejecutar `alembic upgrade head`; después iniciar ambos procesos con la misma versión. El downgrade se impide mientras haya trabajos en ejecución o pendientes de conciliación. No retirar manualmente archivos de exclusión ni leases para desbloquear una operación.


La relectura de verificación de SSID y VLAN usa `UNIFI_VERIFICATION_ATTEMPTS`, `UNIFI_VERIFICATION_INTERVAL_SECONDS` y `UNIFI_VERIFICATION_TIMEOUT_SECONDS`. El timeout cubre los intentos y sus pausas. Los reintentos son consultas al controlador. Una escritura ambigua sigue el flujo de recuperación o conciliación descrito arriba.

### Cambios de VLAN en lote

En **Aprovisionamiento → Cambio de VLAN y reinicio de equipos**, selecciona el ámbito y completa el SSID, la VLAN destino y el motivo. Usa **Agregar selección al lote** para cada fila y **Revisar lote** para preparar la propuesta. Marca las filas que vas a aprobar y pulsa **Confirmar filas del lote**. El historial y el detalle distinguen aprobación en cola, ejecución, detención, conciliación y verificación completa. Puedes recuperar la propuesta y sus resultados desde **Lotes anteriores del ámbito**, y usar **Retomar cambios pendientes** cuando el primer fallo tenga un resultado resuelto.

`POST /api/v1/changes/ssid-vlan-batches/preview` acepta un ámbito y hasta 50 filas con `broadcast_id`, `network_id` y `purpose`. Cada SSID admite una fila. El resultado conserva el orden e informa por fila el impacto, la VLAN de destino y los errores de validación. La vista previa consulta el inventario y el detalle de los SSID autorizados. La vista previa se guarda con una revisión propia. Consulta el lote mediante `GET /api/v1/changes/ssid-vlan-batches/{batch_id}` y confirma sus filas seleccionadas con `POST /api/v1/changes/ssid-vlan-batches/{batch_id}/confirm`, enviando `revision` y `row_numbers`. La confirmación revalida las filas y registra trabajos en orden en una sola transacción. El worker solo puede tomar la fila siguiente cuando se verificó la anterior. Una falla o un resultado incierto detiene el avance. Con el fallo resuelto, `POST /api/v1/changes/ssid-vlan-batches/{batch_id}/retry` prepara un lote nuevo con la numeración original de las filas pendientes y conserva las verificadas en el lote anterior. La nueva propuesta requiere confirmación. Si alguna fila ya no es válida, usa el error numerado para preparar un listado manual. Esta API requiere la migración `025_vlan_batch_plans`.

### Vencimiento de reservas de VLAN

El worker y las consultas liberan reservas vencidas sin un trabajo activo. Desde el inicio de la operación, el plan protege la reserva contra vencimiento, liberación manual y cierre de feria. Una verificación exitosa la asigna. Un fallo resuelto termina la protección y un resultado incierto la conserva hasta la conciliación. Requiere la migración `026_reservation_execution_hold`. La transición y su evento de auditoría se guardan en la misma transacción. **Mis reservas vencidas** muestra el aviso al solicitante al consultar el panel. La API paginada `GET /api/v1/changes/vlan-reservations/mine/expired` limita la consulta a las reservas del usuario autenticado y excluye liberaciones manuales y cierres de feria.

### Reanudar un lote de altas

En **Recuperar planes**, pulsa **Retomar filas pendientes**. La API `POST /api/v1/changes/ssid-plans/{plan_id}/retry` prepara una vista previa nueva para el propietario de un plan fallido o parcial, con las filas aprobadas que quedaron pendientes y su numeración original. Las filas verificadas permanecen en el plan original. El sistema vuelve a validar inventario, ámbito, AP y perfil antes de crear la propuesta. Si falta acreditar el resultado de una fila, primero hay que conciliar. Si una fila pendiente ya no se puede validar, usa la numeración del error para preparar un archivo nuevo. La propuesta necesita una nueva confirmación y el worker vuelve a comprobar sus reservas antes de escribir.

### Cierre de feria

En **Aprovisionamiento → Planes de SSID por ámbito**, selecciona el ámbito y abre **Revisar cierre del ámbito**. El panel muestra los planes que se cancelarán, los trabajos que deben terminar o conciliarse y las reservas que se liberarán o conservarán. La acción **Confirmar cierre del ámbito** usa la revisión mostrada. Puedes volver a consultar el ámbito después de una conciliación.

`GET /api/v1/changes/wifi-scopes/{scope_id}/closure-preview` requiere permiso de administración de redes. Enumera los planes pendientes, los que siguen activos o requieren conciliación, los resultados que requieren revisión y las reservas activas vinculadas explícitamente a esos planes. El ámbito de feria delimita la consulta. Las reservas históricas sin vínculo requieren revisión antes de incluirlas en una limpieza. La vista previa solo consulta la base local y devuelve una revisión vinculada al administrador. Enviar esa revisión a `POST /api/v1/changes/wifi-scopes/{scope_id}/closure-confirm` bloquea nuevos planes, aprobaciones e inicios de ejecución y cancela los planes indicados que aún no comenzaron. Una revisión desactualizada devuelve 409. Los trabajos activos pueden terminar y los inciertos requieren conciliación. La confirmación libera las reservas explícitamente vinculadas que figuran como liberables. Conserva las asignadas, las compartidas con otros ámbitos y las asociadas a operaciones activas, inciertas o verificadas. Tras conciliar, una nueva vista previa permite confirmar la liberación de las reservas que queden disponibles. El historial se conserva. Requiere la migración `024_fair_accepts_changes`.

Después de bloquear cambios y resolver los trabajos pendientes, un administrador puede abrir el siguiente ámbito desde **Abrir próxima feria** en el panel de cierre. Introduce el nombre del ámbito y del evento, y selecciona el personal que quieres autorizar. El formulario usa `POST /api/v1/changes/wifi-scopes/{scope_id}/successor`. Envía `name`, `event_name`, la `revision` de cierre vigente y, opcionalmente, `user_ids` autorizados para el nuevo evento. Se copian las referencias de sitio, AP, VLAN y perfiles. El nuevo ámbito empieza sin planes ni reservas y solo recibe los usuarios indicados.
