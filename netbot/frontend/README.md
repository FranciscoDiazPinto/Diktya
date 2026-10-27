# Frontend

Prototipo visual del centro de monitoreo de Netbot. Esta primera version no requiere
dependencias ni build: abre `index.html` directamente en el navegador.

## Estructura

- `index.html`: dashboard principal.
- `styles.css`: sistema visual responsive.
- `app.js`: login contra la API, sesion local e interacciones del prototipo.

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

## Monitoreo

Tras iniciar sesion, el dashboard consulta cada 5 s los recursos de
`/api/v1/monitoring` (`system`, `interfaces`, `interfaces/traffic`, `clients`,
`firewall/stats` y `firewall/events`) con el token del usuario. Si el token de acceso
vence, lo renueva con `/auth/refresh`. Las fallas parciales (`degraded`/`unavailable`)
se muestran en un aviso sobre los indicadores, sin ocultar los datos que si llegaron.
