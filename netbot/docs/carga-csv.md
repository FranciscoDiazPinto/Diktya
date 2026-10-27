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

Faltan adaptador UniFi, plan de cambios, trabajos durables, autorización por recurso al ejecutar, verificación, compensación y resultados por operación. No convertir la confirmación actual en una llamada directa desde una herramienta del LLM.

## Verificación

Desde netbot: `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Las pruebas cubren parser, autorización, propiedad, expiración, selección, reintentos y rollback de lotes. No sustituyen pruebas con un controlador real.
