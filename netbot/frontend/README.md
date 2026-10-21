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

El panel envía `POST /api/v1/chat/messages` con el token de sesión. Los usuarios
`visor`, `operador` y `admin` pueden preguntar por el estado del sistema, interfaces,
clientes y firewall. El historial se mantiene solo en memoria hasta cerrar sesión o
recargar la página; el frontend no guarda conversaciones ni la clave de OpenRouter.
Las preguntas y los resultados de monitoreo necesarios para responder se procesan en OpenRouter.

El resto del dashboard conserva datos visuales de demostración. Las consultas actuales
del chatbot sí usan la API de monitoreo.
# Reservas VLAN

El panel muestra propuestas de reserva para operador y administrador. Confirmar
envía los campos de evento, propósito y SSID junto a la VLAN elegida; cancelar no
hace ninguna solicitud. Las reservas activas se muestran debajo del chat y el
operador puede liberarlas manualmente. La API del backend vuelve a validar el
permiso, el inventario OPNsense y la disponibilidad antes de guardar.
