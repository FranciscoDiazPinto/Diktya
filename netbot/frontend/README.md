# Frontend

La entrada es el chat temporal de invitados. `modules/guest.mjs` controla el QR, la confirmación y la limpieza a los 60 segundos, sin almacenamiento del navegador. El compositor cambia entre invitados, login y dashboard. Ver [configuración de autoatención](../docs/atencion-invitados.md).

Prototipo del centro de monitoreo de Netbot. Esta primera versión no requiere
dependencias ni build: servir con HTTP local, o con HTTPS en producción.

## Estructura

- `index.html`: dashboard principal.
- `styles.css`: sistema visual responsive.
- `app.js`: arranque del compositor; la lógica está en `modules/` por funcionalidad.

## Login

El formulario usa `POST /auth/login`, valida la sesion con `GET /auth/me` y cierra
sesion con `POST /auth/logout`. Por defecto busca la API en `http://localhost:8000`.
En producción usa la API del mismo origen mediante proxy HTTPS. La URL no se lee de localStorage. Los tokens viven únicamente en memoria; recargar o cerrar la página exige iniciar sesión de nuevo. El arranque borra tokens y URL base persistidos por versiones anteriores. El refresh explícito conserva rotación y aislamiento de sesión; no hay renovación automática ni cookies de autenticación.

CORS admite por defecto `localhost:5173` y `127.0.0.1:5173`, sin `null`. En producción usar `CORS_ORIGINS` explícitos.

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
vence, limpia la sesión y muestra el login; no renueva automáticamente ni repite escrituras. Las fallas parciales (`degraded`/`unavailable`)
se muestran en un aviso sobre los indicadores, sin ocultar los datos que si llegaron.

El módulo `inventory.mjs` consulta cada 15 s el resumen, los dispositivos con filtros por estado y
tipo, las alertas y los SSID/VLAN, y avisa si los datos están desactualizados o si se perdió la API.
También muestra los planos: cada AP con color según su estado y los demás como «sin ubicar».
Cargar planos y ubicar APs solo aparece con `networks:manage`.

## Tickets y notificaciones

El panel de tickets filtra por estado, criticidad y responsable. Quien gestiona tickets puede asignárselos, comentar, ajustar la criticidad y crear tickets técnicos; `visor` solo consulta los de infraestructura. `notifications.mjs` muestra la bandeja del equipo técnico cada 20 s y destaca Alta y Crítica.

## Soporte al cliente

El panel Mi acceso y mi red permite comprobar una red autorizada y revelar su acceso Wi-Fi fuera del chat durante un minuto. El chat puede ofrecer ese botón y propuestas de ticket con confirmación explícita. Los tickets persisten en el backend; técnicos asignados y administradores pueden actualizar su estado con notas visibles para el cliente.

Los datos mock se rotulan como demostración; interfaz activa no significa Wi-Fi e Internet comprobados. Ver [configuración de secretos, fuentes y tickets](../docs/soporte-cliente.md).

## Organización del código

El punto de entrada app.js solo crea y arranca modules/dashboard.mjs. El compositor inyecta entorno, API y callbacks a controladores separados: api, session, chat, monitoring, inventory, notifications, support, tickets y reservations. Las utilidades de vista y formato están en dom/format. No hay dependencias de npm ni paso de compilación.

Cada controlador mantiene estado privado; identidad y época de sesión son el único estado compartido. No añadir lógica de funcionalidad a app.js/dashboard ni importar el compositor desde otro módulo. Usar el cliente API común y preservar los controles que descartan respuestas tardías de otra cuenta/selección.

Las pruebas (`node --test frontend/tests/*.test.mjs`) importan los mismos módulos ES que el navegador con entorno inyectado; no concatenan app.js ni reemplazan sus imports. Ver [guía modular](../docs/arquitectura-modular.md) y [AGENTS.md](../../AGENTS.md).

### Carga CSV

Admin puede validar la [plantilla y contrato CSV](../docs/carga-csv.md), revisar filas y confirmar reservas locales. No crea SSIDs ni modifica infraestructura. Las cargas persisten por propietario y las vistas previas vencen. Producción requiere migración 005.


## Navegación por vistas

El menú muestra una vista a la vez: Resumen y chat, Dispositivos, Alertas, SSID y VLAN, Planos, Puntos de acceso, Interfaces, Clientes, Firewall, Mi red, Tickets y Aprovisionamiento, según permisos. `modules/navigation.mjs` controla únicamente wrappers y navegación por hash, con enlaces directos, recarga y Atrás/Adelante sin reinstanciar controladores ni perder conversaciones. Los módulos conservan sus controles de autorización y estado privado; el backend sigue autorizando cada solicitud.

Resumen reúne el chat con indicadores/gráficos para roles globales y accesos a funciones permitidas para otros usuarios. En escritorio se muestran monitoreo y chat en columnas; en pantallas estrechas se apilan. El enlace antiguo `#chat` abre esta vista combinada. CSV, planes SSID y reservas se agrupan en Aprovisionamiento. Acceso Wi-Fi y destinatarios se ubican en Mi red; salir de esa vista oculta credenciales y descarta respuestas pendientes. Los botones de propuestas del chat abren la vista correspondiente. Una respuesta tardía de preparación SSID no cambia de página si el usuario ya salió del chat.

Para desarrollo, servir `frontend` normalmente: las rutas `#chat`, `#clients`, etc. no requieren reescrituras del servidor. Tras actualizar módulos estáticos en una demo ya abierta, recargar sin caché si el navegador conserva la versión anterior.

Las notificaciones del equipo permanecen accesibles desde la barra superior en cualquier vista; sus enlaces abren Tickets. Los módulos inventory y notifications provienen del desarrollo de monitoreo/tickets integrado y conservan sus contratos de API.
