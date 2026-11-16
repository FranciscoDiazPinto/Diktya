# Frontend React

La entrada es el chat temporal de invitados. `modules/guest.mjs` controla el QR, la confirmación y la limpieza a los 60 segundos, sin almacenamiento del navegador. El compositor cambia entre invitados, login y dashboard. Ver [configuración de autoatención](../docs/atencion-invitados.md).

Aplicación React 19 con Vite. Requiere Node 24 LTS y npm. Las versiones exactas se conservan en `package-lock.json`.

```sh
npm ci
npm run dev
npm test
npm run build
```

Desarrollo: `http://127.0.0.1:5173`, con proxy a `http://127.0.0.1:8000`. Para otro puerto de API, definir `NETBOT_DEV_API_TARGET` al iniciar Vite. La aplicación llama rutas del mismo origen, sin claves de integración en variables Vite. Producción sirve exclusivamente `dist/`; `npm run preview` permite revisar la compilación local. No servir las fuentes con `http.server`.

## Estructura

- `index.html`: entrada de Vite y política CSP de producción.
- `src/main.jsx` y `src/App.jsx`: raíz React, límites de error y pantallas públicas/autenticadas.
- `src/hooks/`: sesión, navegación por hash y consultas de métricas.
- `src/components/`: login, workspace, dashboard y vistas JSX.
- `src/runtime/`: montaje de controladores de las funcionalidades, limpieza de timers/listeners y aislamiento de sesión.
- `modules/`: controladores de chat, soporte, CSV, planes, inventario, tickets y administración reutilizados por los componentes.
- `public/examples/`: plantilla CSV que se copia a `dist`.
- `styles.css`: sistema visual responsive.
- `Dockerfile`: compilación con Node y servicio estático nginx.

## Login

El formulario usa `POST /auth/login`, valida la sesion con `GET /auth/me` y cierra
sesion con `POST /auth/logout`. La aplicación usa rutas del mismo origen. Vite las envía al backend de desarrollo en `127.0.0.1:8000`. Si usa el puerto 8001, configurar `NETBOT_DEV_API_TARGET=http://127.0.0.1:8001` al iniciar Vite.
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

React controla composición, autenticación, navegación y el dashboard de métricas. Los controladores de las demás funcionalidades conservan su estado privado e interfaces existentes; `FeatureMarkup.jsx` define sus formularios y zonas de resultados como componentes estables. `runtime/features.mjs` los conecta por callbacks dentro de un `useLayoutEffect`. No es una reescritura declarativa de todos los controladores: ese trabajo puede realizarse por módulo sin cambiar contratos de API.

`controller-scope.mjs` acota consultas al árbol montado, retira listeners, cancela timers y expone una época de sesión inválida al desmontar. Así el montaje de comprobación de StrictMode no duplica intervalos ni recupera respuestas de una sesión anterior. Las vistas autenticadas permanecen montadas al navegar para conservar conversaciones y formularios; salir de Mi red limpia las credenciales. Logout desmonta todo el árbol autenticado.

Los módulos históricos `dashboard.mjs`, `session.mjs`, `navigation.mjs` y `monitoring.mjs` se conservan exclusivamente para pruebas de regresión de los contratos previos. No forman parte de la entrada ni del bundle de producción. Su fixture está en `tests/fixtures/controller-layout.html`. Las pruebas de React importan la aplicación real con sus controladores, verifican las vistas montadas y prueban polling, expiración, permisos y respuestas tardías. Ejecutar ambas suites con `npm test`.

### Carga CSV

Admin puede validar la [plantilla y contrato CSV](../docs/carga-csv.md), revisar filas y confirmar reservas locales. No crea SSIDs ni modifica infraestructura. Las cargas persisten por propietario y las vistas previas vencen. Producción requiere migración 005.


## Navegación por vistas

El menú muestra una vista a la vez: Resumen y chat, Dispositivos, Alertas, SSID y VLAN, Planos, Puntos de acceso, Interfaces, Clientes, Firewall, Mi red, Tickets y Aprovisionamiento, según permisos. `src/hooks/useNavigation.jsx` controla navegación por hash, con enlaces directos, recarga y Atrás/Adelante sin reinstanciar controladores ni perder conversaciones. Los módulos conservan sus controles de autorización y estado privado; el backend sigue autorizando cada solicitud.

Resumen reúne el chat con indicadores/gráficos para roles globales y accesos a funciones permitidas para otros usuarios. En escritorio se muestran monitoreo y chat en columnas; en pantallas estrechas se apilan. El enlace antiguo `#chat` abre esta vista combinada. CSV, planes SSID y reservas se agrupan en Aprovisionamiento. Acceso Wi-Fi y destinatarios se ubican en Mi red; salir de esa vista oculta credenciales y descarta respuestas pendientes. Los botones de propuestas del chat abren la vista correspondiente. Una respuesta tardía de preparación SSID no cambia de página si el usuario ya salió del chat.

Para desarrollo, iniciar Vite con `npm run dev`: las rutas `#chat`, `#clients`, etc. no requieren reescrituras del servidor. Para publicar una modificación hay que reconstruir `dist` o la imagen del proxy. Vite recarga los cambios durante desarrollo.

Las notificaciones del equipo permanecen accesibles desde la barra superior en cualquier vista; sus enlaces abren Tickets. Los módulos inventory y notifications provienen del desarrollo de monitoreo/tickets integrado y conservan sus contratos de API.

## Auditoría

Administradores con `audit:read` disponen de la vista Auditoría: filtros exactos por actor, origen, acción y resultado, rango de fechas en hora local, paginación y descarga CSV con los filtros aplicados (máximo 5000 registros). Los cambios escritos en el formulario se aplican con «Aplicar filtros». Al cerrar sesión se limpian registros y filtros; las respuestas tardías no pueden restaurarlos. Las filas «Estado actual» son instantáneas, con fecha de creación del plan; no son eventos de ejecución. Ver [contrato y límites](../docs/arquitectura-modular.md#auditoría-unificada--hu013).

## Cambios controlados, usuarios, cuenta y estado del sistema

- **Aprovisionamiento** incorpora `change-plans.mjs`: cambio de VLAN de un SSID y reinicio de un equipo. Preparar muestra el impacto; confirmar es una solicitud aparte vinculada a la revisión; el resultado lo informa el worker. Los estados inciertos no se reintentan desde el navegador: solo un administrador puede conciliarlos.
- **Usuarios** (`users.mjs`, permiso `users:manage`): alta, edición, roles, desactivación y desbloqueo. No hay eliminación de cuentas.
- **Mi cuenta** (`account.mjs`): cambio de contraseña propia; al terminar se cierra la sesión.
- **Estado del sistema** (`system-status.mjs`, permiso `monitoring:read`): agentes en segundo plano y salud del proveedor de IA; avisa si el ejecutor de cambios no está activo.
- **Auditoría**: sin `audit:read`, un técnico ve únicamente sus propias acciones y no puede exportar.
- El chat puede mostrar propuestas de cambio de VLAN y reinicio; el plan solo se crea cuando el usuario pulsa «Preparar revisión en el panel».

Las pruebas de marcado verifican los IDs de las vistas JSX. Las pruebas de React montan los paneles reales, incluyendo permisos y navegación. El recorrido local en Chromium se hizo con datos ficticios y fuentes simuladas, sin escrituras sobre equipos reales.


## Inicio de sesión con Google Workspace

El login muestra el botón oficial de Google cuando la API responde `enabled=true` en `/auth/google/config`. La configuración reside exclusivamente en el backend (`GOOGLE_LOGIN_ENABLED`, `GOOGLE_CLIENT_ID`, `GOOGLE_ALLOWED_DOMAINS`), sin client secret ni credenciales en Vite. Seguir la [configuración y política de acceso](../docs/epica-001-autenticacion-roles.md#acceso-con-google-workspace-rama-frontend-react).

`GoogleSignIn.jsx` obtiene un desafío de cinco minutos, configura el nonce de Google Identity Services y entrega su credencial a `useSession.loginGoogle`. Un callback cancelado, duplicado o vencido no se acepta. Volver a invitados o iniciar otra sesión invalida las respuestas anteriores. Ante un fallo se necesita un desafío nuevo, y el acceso con contraseña permanece disponible. El SDK solo se carga cuando la API habilita Google.
