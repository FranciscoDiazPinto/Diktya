# Épica 002 · Monitoreo de red (OPNsense, UniFi y dashboard)

Cubre las historias 004 (integración), 005 (dashboard) y 006 (alertas y planos). Toda la
lectura es de solo consulta: ningún adaptador tiene métodos de escritura sobre la red.

## Arquitectura

```
router (FastAPI)  ->  MonitoringService  ->  NetworkMonitoringProvider (ABC)
 /api/v1/monitoring    caché + estado          |- OPNsenseMonitoringProvider -> OPNsenseClient (httpx)
                                               |        '- DhcpLeaseProvider: Dnsmasq | Kea
                                               '- MockMonitoringProvider    '- MockDhcpLeaseProvider
```

- `providers/opnsense/mappers.py` y `providers/unifi/mappers.py` son los **únicos** módulos que
  conocen el formato de cada fuente. El resto del sistema solo ve los modelos de `schemas.py`.
- Las fuentes reales son el valor por defecto. El simulador exige `MONITORING_PROVIDER=mock`.
- OPNsense, UniFi y el simulador implementan la interfaz común `InfrastructureSource`.

### Inventario persistido

`inventory.InventoryCollector` corre en el lifespan: cada `MONITORING_INVENTORY_INTERVAL_SECONDS`
pide `collect_inventory()` a cada fuente, por separado, y guarda APs, switches, VLAN y SSID.
Es una tarea en memoria de una instancia, no una cola durable: ejecutar un solo worker.

- **Fallos**: se registran y se reintenta con espera progresiva (`intervalo × 2^n`, tope
  `MONITORING_RETRY_MAX_SECONDS`) sin detener el backend ni las demás fuentes.
- **Datos desactualizados**: una sección que no se obtuvo conserva sus filas. Pasado
  `MONITORING_INVENTORY_MAX_AGE_SECONDS` sin lectura válida, la API las marca con `stale: true`.
- **Desconocido no es cero**: un equipo sin `features` queda `unknown`, y una referencia de red
  rota deja el SSID sin VLAN en vez de asignarle la red por defecto.
- **Disponibilidad**: tiempo en línea sobre tiempo observado, por hora. Un silencio mayor a tres
  intervalos no suma: no es línea ni caída.

### Cuando no hay información

Nunca se recurre a datos inventados. Según el caso:

| Situación | Comportamiento |
|---|---|
| Faltan credenciales | La API arranca, `/health` indica `not_configured` y qué variables faltan. Sin alerta: no hay conexión perdida. |
| La fuente nunca respondió | Los recursos en vivo responden 503; el dashboard muestra «sin datos», no ceros. |
| La fuente dejó de responder | Último dato conocido con `stale: true`, reintentos y alerta de conexión perdida. |
| Falla una sección | Esa sección conserva sus datos; el resto se actualiza. |

### Alertas

`alerts.py` deriva alertas de dispositivos (fuera de línea, degradado, ausente del inventario) y
de fuentes (conexión perdida tras `MONITORING_SOURCE_FAILURE_THRESHOLD` fallos, datos parciales).
Un índice único parcial impide duplicar una condición activa. Al normalizarse pasa a resuelta
sola. Una fuente caída no resuelve las alertas de sus equipos: lo no observado no cambia nada.
No genera tickets: eso pertenece a la épica 005.

### Planos de cobertura

PNG o JPEG, validados por contenido (no por extensión; SVG rechazado) y limitados por
`MONITORING_PLAN_MAX_BYTES`. Cargar, eliminar y ubicar APs exige `networks:manage`. La posición
se guarda relativa (0–1). Un AP sin ubicación aparece en `unplaced`. Ubicar un AP en el plano es
planificación: no configura el equipo ni mide cobertura.

## Contrato de respuesta

Todos los endpoints devuelven el mismo envoltorio:

| Campo | Significado |
|---|---|
| `status` | `ok` · `degraded` (falló algo no opcional, hay datos parciales) · `unavailable` (sin datos) |
| `source` | `opnsense` o `mock` |
| `collected_at` | Momento real de la recolección (útil si la respuesta vino de caché) |
| `data` | Modelo normalizado, o `null` |
| `issues` | Incidentes por componente: `component`, `kind`, `message`, `optional` |

### Historial de tráfico

`GET /interfaces/traffic?window=300` (10–3600 s) devuelve, por interfaz, puntos con
`timestamp`, `bytes_in_per_second` y `bytes_out_per_second`. Una tarea en segundo plano
(arrancada en el lifespan) lee los contadores cada `MONITORING_SAMPLE_INTERVAL_SECONDS` y
guarda `MONITORING_HISTORY_SECONDS` en memoria; la velocidad es la diferencia entre lecturas
consecutivas (se descartan los saltos negativos por reinicio de contadores). El historial se
pierde al reiniciar la API.

HTTP 200 para `ok`/`degraded`; **503** (mismo formato) para `unavailable`. Cada recurso es
un endpoint independiente, de modo que la caída de uno no afecta a los demás. Un incidente
con `optional: true` (p. ej. sensor de temperatura no soportado) no degrada el estado.

### Inventario, alertas y planos

Bajo `/api/v1/monitoring`, con `monitoring:read`. Se leen de la base, no de la fuente.

| Endpoint | Contenido |
|---|---|
| `GET /health` | Estado de cada integración: último intento y éxito, fallos seguidos, error público, próximo intento. |
| `GET /summary` | APs en línea/fuera de línea, VLAN y SSID activos, disponibilidad, alertas, última actualización. |
| `GET /devices?state=&type=&limit=&offset=` | Listado paginado con nombre, tipo, IP, estado y última vez visto. |
| `GET /devices/{id}` | Detalle y alertas activas del equipo. |
| `GET /vlans`, `GET /ssids` | Inventario paginado. Nunca incluye claves. |
| `GET /alerts?active=true&limit=&offset=` | Mayor severidad primero. `active=false` lista las resueltas. |
| `GET /plans`, `GET /plans/{id}`, `GET /plans/{id}/image` | Planos, APs ubicados, APs sin ubicar e imagen. |
| `POST /plans?name=`, `DELETE /plans/{id}` | Requiere `networks:manage`. Imagen como cuerpo crudo. |
| `PUT` y `DELETE /plans/{id}/placements/{device_id}` | Requiere `networks:manage`. `{"x": 0.5, "y": 0.25}`. |

## UniFi Network

Se usa la API oficial con API key (cabecera `X-API-Key`), contrastada con el
[OpenAPI 10.6.106](https://developer.ui.com/network/v10.6.106/openapi.json). `UNIFI_TRANSPORT=direct`
consulta la consola; `connector` pasa por Site Manager y requiere WAN. Ambos usan la ruta base
`/proxy/network/integration` que declara ese OpenAPI.

| Recurso | Llamada |
|---|---|
| Sitio | `GET /v1/sites` (por UUID o `internalReference` en `UNIFI_SITE`) |
| Versión | `GET /v1/info` (opcional) |
| Dispositivos | `GET /v1/sites/{id}/devices` |
| Redes/VLAN | `GET /v1/sites/{id}/networks` |
| SSID | `GET /v1/sites/{id}/wifi/broadcasts` |

Todos los listados se recorren por completo; una paginación incoherente es un error, no un
truncamiento silencioso. `CONNECTION_INTERRUPTED` e `ISOLATED` se presentan como degradado.

## Endpoints OPNsense utilizados

| Recurso | Llamadas | Opcional |
|---|---|---|
| `/system` | `cpu_usage/stream` (SSE; se lee solo el primer evento), `system_resources`, `system_information`, `system_time` | `system_temperature` |
| `/interfaces` | `interfaces/overview/interfaces_info`, `diagnostics/traffic/interface` | `get_interface_statistics` (respaldo de contadores/IP) |
| `/clients` | `dnsmasq/leases/search` o `kea/leases4/search` | — |
| `/firewall/stats` | `firewall/pf_statistics/interfaces`, `firewall/pf_statistics/info` | — |
| `/firewall/events` | `firewall/log?limit=N` | — |

## Estado de verificación

**Contrastado con fuentes oficiales**, sin hardware: el código de OPNsense core (rama `master`, sus
controladores de API y scripts) y el OpenAPI de UniFi Network 10.6.106. Eso corrigió tres supuestos:

1. `firewall/stats` agrupa el log, no entrega paquetes; pass/block salen de `pf_statistics/interfaces`,
   sumando solo dispositivos, porque pfctl también lista grupos como `all`.
2. `pf_statistics/info` publica `{"total": N, "rate": R}` con claves como `current-entries`, y no
   incluye `Status`: `pf_enabled` queda nulo en vez de suponerse.
3. `firewall/log` entrega hora local sin zona: se interpreta con `OPNSENSE_TIMEZONE`.

**Sin validar contra equipos reales.** Las pruebas usan respuestas simuladas con esas formas. Antes
de dar por cerrada la historia 004 hay que correr una lectura contra la versión que se vaya a
desplegar, y registrar versiones y resultado. Tampoco se probó el transporte `connector`.

## Notas

- Los contadores de tráfico son **acumulados desde el arranque**, no velocidad. Para bps el
  consumidor debe calcular deltas entre lecturas.
- Eventos con acción distinta de `block`/`pass` (p. ej. `rdr`) se omiten por no encajar en el modelo.
- **Autenticación**: todos los endpoints exigen un token Bearer de un usuario con el permiso
  `monitoring:read` (roles admin, operador y visor). Sin token: 401; sin permiso: 403.
- Mock: con `MONITORING_PROVIDER=mock`, `MONITORING_MOCK_SCENARIO=degraded|outage` permite probar el dashboard ante fallos.


## Integración con trabajo local (02-11-2026)

El inventario persistido, alertas, disponibilidad y planos de esta épica son la base de la integración. Se conserva retención acotada de lecturas del firewall (`MONITORING_STALE_RETENTION_SECONDS`, por defecto 300 s) con timestamp original y marca `stale`; esas lecturas no habilitan cambios. `GET /access-points` usa el proveedor normalizado UniFi compartido y devuelve DTO mínimos paginados; CPU/RAM/heartbeat quedan desconocidos cuando no se recolectan. No se mantiene un segundo adaptador de estadísticas.

`GET /api/v1/networks/{id}/telemetry` requiere `networks:read:details`, asignación y vinculación explícita de sitio/AP/interfaz. No concede monitoreo global al técnico. Su configuración requiere la migración 009; la revisión 010 une esta historia con monitoreo/tickets. Dashboard y chat se mantienen juntos, con vistas separadas de dispositivos, alertas, SSID/VLAN y planos. Hardware real sigue pendiente de validación.


## Mantenimiento declarado y recursos inactivos (14-11-2026)

- `maintenance.open_window()` declara la caída esperada de un equipo (lo usa el reinicio confirmado). Mientras la ventana está vigente ese equipo no genera alertas; no oculta fallas de la fuente ni de otros equipos, y vence sola. Tabla `monitoring_maintenance`, migración 018.
- Un SSID o VLAN que desaparece del inventario, o que pasa de habilitado a deshabilitado, genera una alerta de severidad media (`ssid_missing`, `ssid_disabled`, `vlan_missing`, `vlan_disabled`) que se resuelve al normalizarse. Se alerta la transición, durante `MONITORING_INACTIVE_ALERT_HOURS` (24 por defecto): un recurso que nunca estuvo activo o una baja deliberada no quedan como alerta permanente.
- El colector y el agente de tickets corren bajo el orquestador; su último ciclo y sus errores se consultan en `GET /api/v1/agents/status` y en la vista Estado del sistema.
