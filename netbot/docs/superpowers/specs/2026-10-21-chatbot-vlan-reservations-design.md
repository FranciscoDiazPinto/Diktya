# Diseño: reservas de VLAN desde el chatbot

**Estado:** aprobado para revisión de especificación  
**Fecha:** 2026-10-21

## Objetivo

Permitir que usuarios `operador` y `admin` soliciten y confirmen desde el panel del chatbot una reserva local en Netbot de una VLAN que ya exista en OPNsense. El chatbot puede consultar y preparar la solicitud, pero no escribe en OPNsense ni confirma por cuenta del usuario.

## Alcance

Incluye:

- Consultar desde OPNsense la configuración de VLAN y normalizar las opciones para el chatbot.
- Identificar cada VLAN por la pareja interfaz padre (`if`) y tag (`tag`). OPNsense documenta que el tag debe ser único por interfaz.
- Comparar el inventario consultado con las reservas activas de Netbot para mostrar opciones libres.
- Recoger el evento, el propósito y el SSID asociado. La identidad del solicitante y las marcas de tiempo provienen del backend.
- Mostrar una propuesta estructurada en el panel y exigir que el usuario pulse **Confirmar reserva**.
- Al confirmar, volver a consultar OPNsense, verificar que la VLAN todavía existe y no está reservada, y crear la reserva local de forma atómica.
- Permitir la liberación manual de una reserva y conservar su historial con el usuario y la hora de liberación.

No incluye crear, editar, asignar, reconfigurar ni eliminar VLAN en OPNsense; cambiar interfaces/firewall; crear SSID en UniFi; reservar VLANs no existentes; vencimiento automático; ni liberar recursos automáticamente.

## Roles y límites de seguridad

- `visor` conserva `CHAT_USE` y `MONITORING_READ`. Puede preguntar por información de monitoreo y VLAN disponibles, pero no puede preparar, confirmar ni liberar reservas.
- `operador` y `admin` pueden preparar, confirmar y liberar reservas mediante el permiso existente `VLAN_RESERVE`. El backend vuelve a comprobar este permiso en cada endpoint y acción; el rol no se acepta desde el cuerpo del request.
- Las herramientas de modelo solo consultan datos o preparan una propuesta sin persistirla. La confirmación de escritura ocurre en una ruta autenticada separada, solo cuando el usuario pulsa el botón.
- No se habilitan llamadas HTTP arbitrarias ni herramientas de escritura de OpenRouter. Las rutas de OPNsense son fijas y usan el cliente existente con TLS verificado.
- La consulta de OPNsense falla de forma cerrada: si el proveedor está desconfigurado, no responde o entrega un formato desconocido, Netbot no presenta VLAN como disponibles ni permite confirmar una reserva.

## Flujo

1. El usuario pide reservar una VLAN en el chat.
2. El backend carga las VLAN desde OPNsense y las reservas activas desde Netbot. El asistente puede guiar al usuario y mostrar opciones normalizadas.
3. El asistente pide los campos faltantes: evento, propósito, SSID asociado y VLAN exacta (interfaz padre + tag). El SSID es metadato de la reserva; no se crea ni verifica en OPNsense.
4. Si el usuario tiene `VLAN_RESERVE`, la API valida la propuesta contra el inventario actual y devuelve un objeto estructurado de propuesta, sin persistir una reserva.
5. El panel muestra el resumen y botones explícitos de confirmar/cancelar. Los valores se renderizan como texto, no como HTML.
6. Al confirmar, el frontend envía los campos de la propuesta a la API de reservas. El backend autentica al usuario, comprueba `VLAN_RESERVE`, vuelve a obtener la VLAN en OPNsense, comprueba disponibilidad y crea la reserva local dentro de una transacción.
7. Si otra solicitud reservó la misma interfaz/tag primero, la restricción de unicidad y la transacción impiden duplicarla; la API devuelve conflicto y pide actualizar la lista.
8. Una reserva activa se libera manualmente con una acción explícita. La API exige `VLAN_RESERVE`, marca quién/cuándo la liberó y no elimina el registro histórico.

## Contratos previstos

Las rutas y modelos definitivos se detallarán en el plan de implementación, manteniendo estas responsabilidades:

- Lectura autenticada de VLAN disponibles desde OPNsense y Netbot.
- Confirmación autenticada de una reserva local.
- Liberación autenticada de una reserva local.
- La respuesta de chat puede incluir una propuesta tipada con interfaz, tag, descripción actual, evento, propósito y SSID; no incluye un token secreto ni constituye una reserva.

Una reserva guardará, como mínimo, la identidad normalizada de la VLAN (`parent_interface`, `tag`), el snapshot legible de la VLAN, evento, propósito, SSID asociado, estado (`reserved` o `released`), usuario/fecha de creación y usuario/fecha de liberación. Debe poder conservar más de una fila histórica para la misma VLAN, pero solo una reserva activa por interfaz/tag.

## OPNsense

La documentación oficial lista `interfaces.vlan_settings` con comandos `get`, `get_item` y `search_item` para lectura, además de comandos de escritura que esta entrega no utilizará. El modelo `Vlan.xml` incluye los campos de interfaz padre, tag, descripción e interfaz VLAN; define el tag entre 1 y 4094 y su unicidad por interfaz.

Referencias:

- [API oficial de interfaces de OPNsense](https://docs.opnsense.org/development/api/core/interfaces.html)
- [Modelo oficial Vlan.xml](https://github.com/opnsense/core/blob/master/src/opnsense/mvc/app/models/OPNsense/Interfaces/Vlan.xml)

La forma exacta del JSON se normalizará en un adaptador y debe verificarse con fixtures y, antes del despliegue conectado a hardware, contra la versión de OPNsense usada por el equipo. La documentación confirma recursos y campos del modelo, pero no sustituye esa validación de integración.

## Datos procesados por OpenRouter

Al igual que el chatbot actual, las preguntas, historial acotado y datos de VLAN necesarios para formular una respuesta se envían a OpenRouter. El evento, propósito y SSID que el usuario comparta también pueden formar parte del historial enviado. El panel mantiene la notificación existente sobre procesamiento externo. No se afirmará una política de retención del proveedor que no se haya verificado.

## Errores y concurrencia

- `401`: sesión ausente o inválida.
- `403`: el usuario no tiene `VLAN_RESERVE` para preparar, confirmar o liberar.
- `409`: VLAN inexistente al confirmar, ya reservada, o estado de reserva incompatible al liberar.
- `422`: campos vacíos, tag inválido, combinación de interfaz/tag ausente o payload inválido.
- `502/503`: OPNsense no responde, está mal configurado o la respuesta no puede normalizarse.
- Ningún error del proveedor incluye credenciales ni cuerpos upstream.
- La disponibilidad se comprueba de nuevo al confirmar y la base impone unicidad de reservas activas por interfaz/tag para resolver carreras.

## Criterios de aceptación

1. El inventario disponible proviene de OPNsense y se normaliza sin exponer credenciales ni payload completo.
2. `visor` puede consultar pero no reservar ni liberar, incluso llamando directamente a los endpoints.
3. `operador` y `admin` pueden preparar propuestas; preparar una propuesta no crea una reserva.
4. Solo una confirmación explícita crea la reserva local; el backend verifica nuevamente el inventario y el permiso.
5. Reservas activas duplicadas para una interfaz/tag se rechazan, incluso con solicitudes concurrentes.
6. Evento, propósito, SSID, VLAN, solicitante y fechas quedan asociados a la reserva; liberar requiere permiso y deja trazabilidad.
7. No se envían métodos de escritura a OPNsense y no se crea ni modifica ninguna VLAN allí.
8. Errores de OPNsense bloquean la reserva con mensajes controlados.
9. El panel muestra la propuesta, permite confirmar/cancelar y liberar una reserva activa, renderizando valores externos con `textContent`.
10. Las pruebas cubren roles, validación, proveedor OPNsense, confirmación, conflicto concurrente, liberación, errores y presentación segura; además, se documenta cómo probar la lectura contra una instancia real.
