# Autoatención y recuperación de acceso Wi-Fi

La entrada es un chat sin cuenta. «Iniciar sesión · Equipo» abre el login y lleva al dashboard. Cerrar sesión vuelve al chat vacío. Hay dos flujos separados: recuperar el acceso de un cliente registrado y conectarse al Wi-Fi abierto con portal de invitados.

## Recuperar credenciales de cliente

La entrega privada a invitados está **suspendida**: conocer un correo o teléfono no prueba posesión. El botón deriva al equipo del recinto y no recolecta contactos. `POST /identify` devuelve un rechazo uniforme sin consultar el registro; `guest_wifi_qr` rechaza toda red privada incluso si una sesión conserva un contacto anterior.

Para rehabilitarla se requiere OTP, enlace de un solo uso o voucher verificable: hash en servidor, TTL, límite de intentos, vinculación a la sesión y consumo atómico. Esa verificación todavía no está implementada. El QR del portal abierto y el acceso autenticado autorizado siguen disponibles. Los contactos reconocibles escritos por error en el chat no se muestran ni se envían al LLM.

## Registro de destinatarios en Netbot

Primero aplicar `alembic upgrade head`: la migración `006_network_recipients` agrega el registro, independiente de `users`. No modificar ni borrar bases existentes para aplicar este cambio.

En el dashboard, el administrador dispone de **Destinatarios de credenciales Wi-Fi**. Seleccionar una red y editar una línea por cliente: `correo;teléfono`. Se admite dejar uno vacío, pero no ambos. Ejemplos ficticios:

```text
cliente@example.com;+56912345678
otro@example.com;
;+56987654321
```

Guardar reemplaza la lista completa de esa red; una lista vacía revoca su recuperación. No se crean usuarios ni contraseñas de Netbot. No se envían correos automáticamente: registrar los mismos contactos que recibieron las credenciales. Los contactos se almacenan en `network_recipients`; solo administradores con `networks:manage` pueden leer o modificar ese registro. La auditoría registra la actualización sin copiar contactos ni claves.

Contratos administrativos:

- `GET /admin/networks/{id}/recipients`: contactos de esa red.
- `PUT /admin/networks/{id}/recipients`: `{"recipients":[{"email":"cliente@example.com","phone":"+56912345678"}]}`. Máximo 500 filas por solicitud. Reemplaza la lista.

Los correos se comparan sin distinguir mayúsculas, con validación de formato. En teléfonos se eliminan espacios, guiones y paréntesis; `00` se normaliza a `+`. No se infiere el país ni se comparan solo los últimos dígitos. Las respuestas administrativas llevan `Cache-Control: no-store, private`.

Cada red debe tener su `credential_ref` configurado mediante `PUT /admin/networks/{id}/support` y el secreto correspondiente en `WIFI_ACCESS_CREDENTIALS_JSON`. `site`, `external_id` y `ssid` deben coincidir exactamente; ver [soporte por red](soporte-cliente.md). No guardar secretos reales en Git. Las redes de cliente **no** se agregan a `GUEST_WIFI_NETWORK_IDS`; registrar destinatarios no habilita su recuperación privada.

## Portal de invitados

«Portal de invitados» muestra exclusivamente redes **abiertas** incluidas expresamente en `GUEST_WIFI_NETWORK_IDS`, vacío por defecto. La referencia del secreto debe declarar `security: open` y no tener contraseña. Escanear ese QR conecta a la red abierta; el portal cautivo sigue gestionando su propio acceso. Netbot no elimina ni evita ese portal.

Las redes WPA2/WPA3 no entregan QR anónimamente aunque se hayan incluido por error en esa lista: requieren acceso autenticado autorizado; conocer un contacto no las habilita. Se admiten redes abiertas, WPA2 Personal y WPA3 Personal; no Wi-Fi Enterprise ni credenciales individuales de portal/vouchers. El escaneo y conexión deben probarse con teléfonos y redes reales, especialmente WPA3. El QR se genera localmente con `qrcode`; no se envían claves a generadores externos ni al modelo.

## Resolución y limpieza

Tras responder o mostrar el QR, Netbot pregunta «¿Se resolvió tu duda?». Si responde que sí, solicita confirmar la limpieza. Confirmar borra inmediatamente mensajes, formulario de contacto, red seleccionada, QR y token. «Seguir consultando» conserva la atención; «Finalizar atención» abre la confirmación.

Tras 60 segundos sin actividad se limpia automáticamente, incluso sin responder la confirmación. Al volver a una pestaña suspendida se comprueba el vencimiento. Las respuestas tardías de chat, identificación y QR no pueden aparecer en otra atención.

Los tokens, contactos identificados e historial de invitados viven en RAM, sin cookies ni localStorage/sessionStorage. El servidor elimina la sesión y el contacto a los 60 segundos sin actividad, con un barrido cada segundo. El frontend también solicita eliminación al limpiar, pasar al login, autenticarse o abandonar la página; si falla, sigue aplicando el vencimiento del servidor. El registro administrativo de destinatarios permanece: la limpieza elimina la atención, no los contactos del negocio.

Las consultas generales se envían a OpenRouter y están sujetas a la retención del proveedor. Limpiar el QR no revoca la contraseña Wi-Fi ni desconecta dispositivos ya asociados. El panel de acceso autenticado mantiene sus permisos y también muestra QR temporal.

## API de autoatención

Prefijo `/api/v1/guest`. Respuestas de éxito con `Cache-Control: no-store, private`.

| Método y ruta | Contrato |
|---|---|
| `POST /sessions` | Token aleatorio y `expires_in: 60`. |
| `POST /identify` | `{contact}`. Rechazo uniforme HTTP 403; recuperación privada suspendida. |
| `POST /messages` | Solo `{message}`; historial del servidor, sin identidad ni permisos del navegador. |
| `GET /networks` | Redes abiertas publicadas para el portal de invitados. |
| `POST /networks/{id}/access` | SSID y QR como data URL solo para redes abiertas publicadas. |
| `POST /session/activity` | Renueva el minuto de actividad. |
| `DELETE /session` | Elimina sesión, contacto e historial. |

Excepto la creación, requieren `X-Guest-Session`. Ese token no permite entrar a endpoints de usuarios autenticados. No registrar este encabezado ni los cuerpos de `/identify` o `/recipients` en proxies o trazas. Los invitados no tienen herramientas del LLM, monitoreo, tickets ni cambios de infraestructura.

## Operación y verificación

Instalar dependencias actualizadas con `pip install -r requirements.txt`, aplicar migración 006 y reiniciar la API. Las sesiones están en memoria de **una instancia/proceso**: ejecutar un solo worker. Para réplicas hace falta almacenamiento efímero compartido con TTL y revocación coherente. Reiniciar termina las atenciones temporales, pero conserva los destinatarios en la base.

Además del control compartido descrito en el README, límites por proceso: 200 sesiones simultáneas, 60 creaciones/minuto, 120 consultas o comprobaciones de contacto/minuto; 30 consultas al modelo y 5 identificaciones por atención. Una consulta al modelo en curso por sesión. El exceso de frecuencia usa HTTP 429. Se mantienen límites de mensaje, historial, salida y timeout.

Pruebas desde `netbot/`: `.venv/bin/python -m pytest -q` y `node --test frontend/tests/*.test.mjs`. Cubren rechazo de recuperación privada por contacto conocido/desconocido, registro administrativo, portal abierto, aislamiento del LLM, vencimiento y respuestas tardías. Las pruebas visuales usan datos ficticios, sin conexión Wi-Fi real.
