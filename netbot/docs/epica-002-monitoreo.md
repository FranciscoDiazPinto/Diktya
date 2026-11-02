# Épica 002 · Monitoreo de red (backend, OPNsense)

## Arquitectura

```
router (FastAPI)  ->  MonitoringService  ->  NetworkMonitoringProvider (ABC)
 /api/v1/monitoring    caché + estado          |- OPNsenseMonitoringProvider -> OPNsenseClient (httpx)
                                               |        '- DhcpLeaseProvider: Dnsmasq | Kea
                                               '- MockMonitoringProvider    '- MockDhcpLeaseProvider
```

- `providers/opnsense/mappers.py` es el **único** módulo que conoce el formato de OPNsense.
  El resto del sistema (y el futuro frontend) solo ve los modelos de `schemas.py`.
- Cambiar entre real y simulado es solo configuración (`MONITORING_PROVIDER`).

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

## Endpoints OPNsense utilizados

| Recurso | Llamadas | Opcional |
|---|---|---|
| `/system` | `cpu_usage/stream` (SSE; se lee solo el primer evento), `system_resources`, `system_information`, `system_time` | `system_temperature` |
| `/interfaces` | `interfaces/overview/interfaces_info`, `diagnostics/traffic/interface` | `get_interface_statistics` (respaldo de contadores/IP) |
| `/clients` | `dnsmasq/leases/search` o `kea/leases4/search` | — |
| `/firewall/stats` | `firewall/stats`, `firewall/pf_statistics/info` | — |
| `/firewall/events` | `firewall/log?limit=N` | — |

## Estado de verificación de los formatos de respuesta

**Verificado** contra documentación/código de OPNsense: nombres de endpoints, Basic Auth con
key/secret, `system_resources` (`memory.total`/`memory.used` en bytes), y que `cpu_usage/stream`
es un stream.

**Inferido (contrastar con un OPNsense real antes de dar por cerrado el sprint)**: forma exacta de
`system_time` (uptime y fechas), `system_temperature`, `interfaces_info`, `traffic/interface`,
`get_interface_statistics`, filas de leases (Dnsmasq/Kea), `firewall/log`, `firewall/stats`.
Los mapeadores son tolerantes (ante campos desconocidos devuelven `null`, no fallan), y los
fixtures de `tests/monitoring/fixtures.py` documentan la forma asumida: si un payload real
difiere, se ajusta `mappers.py` y su fixture.

Dos puntos concretos a confirmar:
1. `pf_statistics` requiere una *sección* en la ruta; se usa `info` (equivale a `pfctl -si`).
   Está en la constante `PATH_PF_STATISTICS`.
2. `firewall/stats` no tiene mapeo conocido de campos: hoy se suman contadores cuyo nombre
   contiene `pass`/`block` + `packets`; si no hay coincidencias el valor es `null`.

## Notas

- Los contadores de tráfico son **acumulados desde el arranque**, no velocidad. Para bps el
  consumidor debe calcular deltas entre lecturas.
- Eventos con acción distinta de `block`/`pass` (p. ej. `rdr`) se omiten por no encajar en el modelo.
- **Autenticación**: todos los endpoints exigen un token Bearer de un usuario con el permiso
  `monitoring:read` (roles admin y visor; técnico/operador consulta solo su red mediante /networks/{id}/telemetry). Sin token: 401; sin permiso: 403.
- Mock: `MONITORING_MOCK_SCENARIO=degraded|outage` permite probar el dashboard ante fallos.


## Avance HU004/HU005 · 30-10-2026

Implementado en `feature/epica-002-monitoreo`, actualizado desde `main` 9ac2a2e. El adaptador Python es propio; Atlas se revisó solo como referencia de separación inventario/telemetría, campos y endpoints. No se copiaron código, pruebas, direcciones, claves ni configuración. No se contactó infraestructura del cliente.

### Antigüedad y disponibilidad

El envoltorio incorpora `stale` y `last_attempt_at`. Ante una falla conserva el último dato conocido hasta `MONITORING_STALE_RETENTION_SECONDS` (300 por defecto, 0 deshabilita), con estado `degraded`, `stale=true`, `collected_at` original e incidencias de la consulta fallida. El último intento NO es una nueva observación. Si nunca hubo dato o vence la retención: `unavailable`, `data=null`; los endpoints globales responden 503. Una lectura posterior válida elimina el estado antiguo.

La caché es por recurso y fuente, con TTL máximo configurable de 60 segundos; la conservación de datos antiguos no renueva ese dato ni extiende indefinidamente la retención. Sigue siendo memoria de esta instancia y se pierde al reiniciar. Tráfico no agrega muestras con lecturas antiguas y no presenta historial viejo como lectura actual. Dashboard y política de chat distinguen datos anteriores de estado vigente. Los flujos de reserva y planes CSV/SSID rechazan inventarios antiguos: conservar para consulta no autoriza cambios.

### Lectura UniFi

`UNIFI_MONITORING_MODE=disabled|mock|api` es independiente de `UNIFI_INVENTORY_MODE` y nunca habilita escrituras. En `api`: URL HTTPS completa hasta el prefijo de Integration API, API key en `X-API-Key`, CA opcional, sitio explícito en `UNIFI_MONITORING_SITE_ID`, timeout y redirecciones deshabilitadas. No hay fallback a API clásica ni a cloud ni desactivación TLS. El despliegue local en rack usa la ruta de administración accesible desde ese equipo; no necesita incorporar la dirección de Atlas al código.

Contrato consultado: [UniFi Network 10.6.106 OpenAPI](https://developer.ui.com/network/v10.6.106/openapi.json). Se consultan `GET /info`, `/sites/{siteId}/devices` paginado y `/sites/{siteId}/devices/{deviceId}/statistics/latest` como objeto directo. El primer recurso expone inventario; el último, datos opcionales por AP. Solo se clasifican como AP equipos con feature explícita `accessPoint`. Estado desconocido o interrumpido permanece desconocido; no se infiere conexión por IP, modelo o uptime.

Se preservan uptime, CPU/RAM y `lastHeartbeatAt` cuando existen. La hora de consulta nunca se utiliza como heartbeat. Campos ausentes permanecen nulos, no ceros. Una falla de estadísticas no elimina el inventario; se indica telemetría no disponible e incidencia opcional. Listados detectan duplicados, páginas incompletas, totales cambiantes y exceso de límites, sin truncamiento silencioso. Estadísticas: máximo 5 consultas concurrentes y presupuesto total configurable, 5 segundos por defecto. Inventario tiene límite temporal de 30 segundos; `UNIFI_MONITORING_MAX_APS` limita AP de esta instancia.

Revisión de compatibilidad OPNsense: la [documentación oficial de Diagnostics](https://docs.opnsense.org/development/api/core/diagnostics.html) conserva `system_information`. Se mantiene ese endpoint de Netbot y sus errores tipados; la ruta histórica `systeminformation` observada en Atlas no se impone como reemplazo. Continúa pendiente contrastar payloads específicos con la versión de laboratorio.

### API y autorización

- `GET /api/v1/monitoring/access-points?limit=50&offset=0`: admin/visor con `monitoring:read`; `data={items,total_count,offset,limit}`. Máximo 100 filas/página, con metadatos de antigüedad del snapshot completo.
- `GET /api/v1/networks/{network_id}/telemetry`: técnico/operador/admin con `networks:read:details` y acceso vigente a esa red. Devuelve únicamente AP explícitos y la interfaz vinculada. Cliente e invitado no reciben inventario técnico.
- `PUT /admin/networks/{network_id}/support`: admin vincula `unifi_site_id` y `unifi_ap_ids`, junto con `monitoring_interface_id` y `credential_ref` existentes. Es PUT de configuración completa: conservar los otros valores al editar. Sin AP vinculados no se devuelven todos por defecto. Sitio no coincidente o AP ausentes se informa como incompleto.
- Se revalidan identidad, rol, asignación y vinculación después de esperas externas. Una revocación descarta la respuesta; un cambio de vinculación no entrega datos del ámbito anterior. La concesión de aprovisionamiento SSID no sustituye esta vinculación de lectura.

Requiere migración **009_network_monitoring_scope**. Agrega sitio y lista de AP a `network_support_config`; las configuraciones previas conservan sus datos y empiezan sin AP. Producción exige `alembic upgrade head` antes del arranque.

Ejemplo ficticio de configuración (reemplazar IDs usando inventario autorizado):

```json
{"credential_ref":null,"monitoring_interface_id":"opt1","unifi_site_id":"demo-site","unifi_ap_ids":["demo-ap-1","demo-ap-3"]}
```

El panel «Puntos de acceso» tiene paginación para la vista global y selección de red para el técnico. Conserva fechas visibles, distingue simulación/antigüedad, ignora respuestas de otra sesión o red y limpia su contenido al salir. El técnico no obtiene clientes, firewall ni métricas globales por esta ampliación.

### Evidencia y límites de cierre

Pruebas: `tests/monitoring/test_resilience.py`, `test_unifi.py`, `tests/test_network_telemetry.py` y `frontend/tests/access-points.test.mjs`; se conservan las suites previas. Verifican fallas, retención/vencimiento/recuperación, ausencia de escrituras con datos antiguos, paginación, serialización segura, estadísticas opcionales y revocación durante consultas. La migración 008→009 se probó en PostgreSQL 16 temporal, preservando datos y auditoría; las suites prueban también SQLite y arranque de producción migrado.

HU004/HU005 avanzan con estos contratos, pero no se acreditan como cerradas sin laboratorio y revisión del equipo. **HU006 sigue pendiente:** alertas persistentes con severidad/deduplicación/resolución y planos con ubicación de AP. Los banners de error y la lista de AP no reemplazan ese ciclo ni representan cobertura RF. Tampoco se acredita HA, disponibilidad Wi-Fi, Internet ni despliegue por observar un AP ONLINE en UniFi.

Validación de esta revisión: **339 pruebas backend y 43 frontend aprobadas**. Revisión en navegador con datos ficticios de técnico/admin y desconexión simulada. Los avisos de antigüedad se aplican también a cada KPI e interfaz para no conservar etiquetas de disponibilidad actual.
