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
- **Exclusión**: bloqueo durable por sitio y SSID, o por equipo. Ejecución y conciliación del mismo plan comparten además una exclusión entre procesos, independiente de sus commits: un trabajo activo no se recupera aunque lleve mucho tiempo. PostgreSQL requiere conexión directa o pooling de sesión; SQLite usa `flock` local en Unix junto a la base.
- **Cambio de VLAN**: el contrato 10.6.106 solo ofrece `PUT`. Se reenvía el detalle leído sin `id` ni `metadata`, cambiando únicamente la red. Si el controlador entrega la clave censurada o sin seguridad, no se escribe.
- **Estados inciertos**: una escritura ambigua nunca se repite. Primero se lee el controlador: si el cambio quedó aplicado y verifica, se da por completado; si no se aplicó, `failed`; si otro actor cambió el recurso, `uncertain` sin sobrescribirlo. `uncertain` y `rollback_failed` conservan el bloqueo.
- **Conciliación**: `POST /api/v1/changes/reconcile/{ssid|vlan|restart}/{id}` (solo `networks:manage`) o `python -m app.agents.cli reconcile …`. Solo lee. El worker concilia los `executing` antiguos desde `execution_started_at` y únicamente si consigue su exclusión; la API también rechaza conciliar un plan activo. En un reinicio, un uptime menor que el previo acredita el resultado; estar en línea sin esa evidencia permite liberar el recurso como `unverified`, nunca como reinicio verificado, y no repite la orden.
- **Aprobaciones**: las vencidas salen de la cola como `expired` con auditoría; un rechazo definitivo previo a ejecutar pasa a `rejected` y exige preparar otra propuesta. Un plan ocupado por otro ejecutor conserva su aprobación hasta que pueda tomarse o venza.
- **Escalamiento**: verificación fallida o resultado incierto abren un ticket de criticidad Alta; un rollback fallido, Crítica; un equipo que no vuelve, Alta.
- **Mantenimiento**: durante un reinicio confirmado no se alerta la caída esperada de ese equipo. La ventana vence sola.
- **Reservas**: una reserva vence a las `VLAN_RESERVATION_TTL_HOURS` si no se usa y pasa a `assigned` cuando el SSID que usa esa VLAN se verifica. El conflicto informa el evento que la reservó y alternativas libres.

`completed` significa configuración coincidente en el controlador. No demuestra difusión efectiva, conectividad Wi-Fi ni Internet. Antes de habilitar `UNIFI_WRITE_ENABLED` hay que validar en laboratorio la versión del controlador, el `PUT` de actualización, la acción `RESTART` y qué devuelve el detalle de seguridad.

Para actualizar a `021_execution_ownership`, detener la API y todos los workers, respaldar y ejecutar `alembic upgrade head`; después iniciar ambos procesos con la misma versión. El downgrade se impide mientras haya trabajos en ejecución o pendientes de conciliación. No retirar manualmente archivos de exclusión ni leases para desbloquear una operación.
