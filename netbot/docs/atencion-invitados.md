# Autoatención y recuperación de acceso Wi-Fi

La entrada es un chat sin cuenta. «Iniciar sesión · Equipo» abre el login y lleva al dashboard. Cerrar sesión vuelve al chat vacío. Hay dos flujos separados: recuperar el acceso de un cliente registrado y conectarse al Wi-Fi abierto con portal de invitados.

## Recuperar credenciales de cliente

El expositor ingresa su **correo registrado** en el formulario, fuera del chat. El servidor responde de forma uniforme exista o no el contacto; envía un enlace solo si hay redes explícitamente habilitadas para expositores. Teléfono, SMS y Telegram quedan pendientes: un número con formato válido no acredita posesión.

El enlace caduca a los cinco minutos. Abrirlo por GET no consume ni revela datos: hay que pulsar **Confirmar y mostrar mi QR**. El QR aparece en el dispositivo que abrió el correo, no en el tótem, y se limpia de la página tras un minuto. El token es aleatorio, su hash es lo único almacenado y el consumo es atómico de un solo uso. El fragmento de URL evita enviar el token en la petición GET o en Referer. El cliente nunca recibe el enlace desde la respuesta de solicitud.

Administración, Marketing y Servicios están excluidas, aunque coincida el contacto o alguien intente publicar esas redes como abiertas. La configuración `guest_recovery_purpose` debe ser `expositor` y el nombre/SSID no puede indicar una categoría interna bloqueada. Por defecto todas las redes tienen `disabled`. El listado y las asignaciones actuales se revalidan al consumir el enlace, dentro de la misma exclusión transaccional que su modificación. Cambiar la categoría o retirar al destinatario invalida enlaces pendientes. Se incluyen solo las redes autorizadas al solicitar y aún autorizadas al confirmar.

Configurar SMTP (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`) y `GUEST_EMAIL_RECOVERY_ENABLED=true`, `GUEST_EMAIL_RECOVERY_PUBLIC_URL=https://dominio-api.example` (origen sin ruta). Producción exige HTTPS y STARTTLS. Sin configuración no se habilita la recuperación. La URL debe ser accesible desde el dispositivo que recibe el correo: localhost solo sirve para pruebas en el mismo equipo.

Aplicar migración **012_wifi_email_recovery**. En el panel de destinatarios el administrador selecciona y guarda la finalidad de la red. La API dedicada es `PATCH /admin/networks/{id}/recovery-policy` con `{purpose: "expositor"}`; también forma parte del DTO de soporte. No se habilitan redes antiguas automáticamente.

Las solicitudes tienen límites por origen/global y como máximo dos envíos pendientes por correo en cinco minutos. Las respuestas no muestran si existe el destinatario. Fallos SMTP se registran sin destinatarios, enlaces ni credenciales; no existe un worker durable de reintentos: solicitar otro enlace o contactar al equipo si no llega. Los registros caducados se eliminan al procesar una nueva solicitud; el acceso caduca aunque no se haya ejecutado esa limpieza.

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

Cada red debe tener su `credential_ref` configurado mediante `PUT /admin/networks/{id}/support` y el secreto correspondiente en `WIFI_ACCESS_CREDENTIALS_JSON`. `site`, `external_id` y `ssid` deben coincidir exactamente; ver [soporte por red](soporte-cliente.md). No guardar secretos reales en Git. Las redes de cliente **no** se agregan a `GUEST_WIFI_NETWORK_IDS`; registrar destinatarios por sí solo no habilita recuperación: también se requiere la finalidad expositor y confirmar el enlace.

## Portal de invitados

«Portal de invitados» muestra exclusivamente redes **abiertas** incluidas expresamente en `GUEST_WIFI_NETWORK_IDS`, vacío por defecto. La referencia del secreto debe declarar `security: open` y no tener contraseña. Escanear ese QR conecta a la red abierta; el portal cautivo sigue gestionando su propio acceso. Netbot no elimina ni evita ese portal.

Las redes WPA2/WPA3 no entregan QR anónimamente aunque se hayan incluido por error en esa lista: requieren acceso autenticado autorizado o el enlace de correo confirmado de una red de expositor; conocer un contacto no las habilita. Se admiten redes abiertas, WPA2 Personal y WPA3 Personal; no Wi-Fi Enterprise ni credenciales individuales de portal/vouchers. El escaneo y conexión deben probarse con teléfonos y redes reales, especialmente WPA3. El QR se genera localmente con `qrcode`; no se envían claves a generadores externos ni al modelo.

## Resolución y limpieza

El backend devuelve `state`: `needs_information` para preguntas o aclaraciones, `answered` para una explicación o derivación completa y `closed` cuando el usuario expresa que terminó. El modelo solo propone los dos primeros mediante JSON validado; una respuesta que contiene preguntas continúa como aclaración. Texto sin clasificación se trata de forma conservadora como `needs_information`, y JSON inválido se rechaza sin mostrar metadatos. `needs_clarification` se conserva por compatibilidad.

La interfaz ofrece «¿Se resolvió tu duda?» únicamente tras `answered` (o mostrar el QR), una vez por bloque de ayuda. Ignorar esa pregunta y seguir conversando no la repite en cada respuesta. «Necesito más ayuda» vuelve a habilitarla para la siguiente explicación completa. Fallos de conexión o del proveedor no disparan una pregunta de resolución.

Expresiones completas como «ya funciona» o «gracias, ya funciona» señalan intención de terminar; «gracias» solo se interpreta así después de una respuesta completa. «Gracias, pero no funciona» continúa la conversación. La clasificación no certifica conectividad ni resolución real. Si el usuario confirma resolución, solicita confirmar la limpieza. Confirmar borra inmediatamente mensajes, formulario de contacto, red seleccionada, QR y token. «Seguir consultando» conserva la atención; «Finalizar atención» abre la confirmación.

Tras 60 segundos sin actividad se limpia automáticamente, incluso sin responder la confirmación. Al volver a una pestaña suspendida se comprueba el vencimiento. Las respuestas tardías de chat, identificación y QR no pueden aparecer en otra atención.

Los tokens, contactos identificados e historial de invitados viven en RAM, sin cookies ni localStorage/sessionStorage. El servidor elimina la sesión y el contacto a los 60 segundos sin actividad, con un barrido cada segundo. El frontend también solicita eliminación al limpiar, pasar al login, autenticarse o abandonar la página; si falla, sigue aplicando el vencimiento del servidor. El registro administrativo de destinatarios permanece: la limpieza elimina la atención, no los contactos del negocio.

Las consultas generales se envían a OpenRouter y están sujetas a la retención del proveedor. Limpiar el QR no revoca la contraseña Wi-Fi ni desconecta dispositivos ya asociados. El panel de acceso autenticado mantiene sus permisos y también muestra QR temporal.

## API de autoatención

Prefijo `/api/v1/guest`. Respuestas de éxito con `Cache-Control: no-store, private`.

| Método y ruta | Contrato |
|---|---|
| `POST /sessions` | Token aleatorio y `expires_in: 60`. |
| `POST /recovery/email` | `{email}`; requiere sesión temporal, responde 202 uniforme y envía enlace si corresponde. |
| `GET /recovery/approve` | Página de confirmación; no requiere sesión y no consume tokens. |
| `POST /recovery/approve` | Token en cuerpo y Origin configurado; devuelve QR solo tras consumo válido. |
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

La página de confirmación de correo incluye una tarjeta adaptable a móvil, estados de carga/error y un QR por red. Sus estilos se sirven desde `/api/v1/guest/recovery/approval.css`, con CSP limitada al mismo origen y sin caché; conserva confirmación explícita y limpieza del QR a los 60 segundos.
