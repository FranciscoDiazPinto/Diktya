# Frontend

Prototipo del centro de monitoreo de Netbot. Esta primera versión no requiere
dependencias ni build: abre `index.html` directamente en el navegador.

## Estructura

- `index.html`: dashboard principal.
- `styles.css`: sistema visual responsive.
- `app.js`: login contra la API, sesión local, interacciones del dashboard y panel de chat.

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
