# Frontend

Prototipo del centro de monitoreo de Netbot. Esta primera versión no requiere
dependencias ni build: abre `index.html` directamente en el navegador.

## Estructura

- `index.html`: dashboard principal.
- `styles.css`: sistema visual responsive.
- `app.js`: arranque del compositor; la lógica está en `modules/` por funcionalidad.

## Login

El formulario usa `POST /auth/login`, valida la sesion con `GET /auth/me` y cierra
sesion con `POST /auth/logout`. Por defecto busca la API en `http://localhost:8000`.
Para cambiarla desde la consola del navegador:

```js
localStorage.setItem('netbot_api_url', 'http://localhost:8000')
```

El backend permite por defecto los origenes de desarrollo `localhost:5173`,
`127.0.0.1:5173` y archivos locales (`null`). En otros entornos se puede definir
`CORS_ORIGINS` como una lista separada por comas.

## Chat con Netbot

El panel envía `POST /api/v1/chat/messages` con el ID y la versión de la conversación. El historial se guarda en el servidor, por usuario, y se recupera al iniciar sesión. El selector permite abrir chats anteriores o empezar uno nuevo con una red autorizada. No se envía historial desde el navegador.

Cliente y técnico ven el asistente y sus redes asignadas; el dashboard global se muestra solo con `monitoring:read` (visor/admin). Las herramientas y APIs vuelven a comprobar permisos en el servidor. Las preguntas y los resultados necesarios se procesan en OpenRouter. No enviar contraseñas por el chat.

Ver [contrato, permisos y migración](../docs/chat-roles-y-persistencia.md).

## Reservas VLAN

El panel muestra propuestas de reserva para administrador. Confirmar
envía los campos de evento, propósito y SSID junto a la VLAN elegida; cancelar no
hace ninguna solicitud. Las reservas activas se muestran debajo del chat y el
administrador puede liberarlas manualmente. La API del backend vuelve a validar el
permiso, el inventario OPNsense y la disponibilidad antes de guardar.

## Monitoreo

Tras iniciar sesion, el dashboard consulta cada 5 s los recursos de
`/api/v1/monitoring` (`system`, `interfaces`, `interfaces/traffic`, `clients`,
`firewall/stats` y `firewall/events`) con el token del usuario. Si el token de acceso
vence, lo renueva con `/auth/refresh`. Las fallas parciales (`degraded`/`unavailable`)
se muestran en un aviso sobre los indicadores, sin ocultar los datos que si llegaron.

## Soporte al cliente

El panel Mi acceso y mi red permite comprobar una red autorizada y revelar su acceso Wi-Fi fuera del chat durante un minuto. El chat puede ofrecer ese botón y propuestas de ticket con confirmación explícita. Los tickets persisten en el backend; técnicos asignados y administradores pueden actualizar su estado con notas visibles para el cliente.

Los datos mock se rotulan como demostración; interfaz activa no significa Wi-Fi e Internet comprobados. Ver [configuración de secretos, fuentes y tickets](../docs/soporte-cliente.md).

## Organización del código

El punto de entrada app.js solo crea y arranca modules/dashboard.mjs. El compositor inyecta entorno, API y callbacks a controladores separados: api, session, chat, monitoring, support, tickets y reservations. Las utilidades de vista y formato están en dom/format. No hay dependencias de npm ni paso de compilación.

Cada controlador mantiene estado privado; identidad y época de sesión son el único estado compartido. No añadir lógica de funcionalidad a app.js/dashboard ni importar el compositor desde otro módulo. Usar el cliente API común y preservar los controles que descartan respuestas tardías de otra cuenta/selección.

Las pruebas (`node --test frontend/tests/*.test.mjs`) importan los mismos módulos ES que el navegador con entorno inyectado; no concatenan app.js ni reemplazan sus imports. Ver [guía modular](../docs/arquitectura-modular.md) y [AGENTS.md](../../AGENTS.md).

### Carga CSV

Admin puede validar la [plantilla y contrato CSV](../docs/carga-csv.md), revisar filas y confirmar reservas locales. No crea SSIDs ni modifica infraestructura. Las cargas persisten por propietario y las vistas previas vencen. Producción requiere migración 005.
