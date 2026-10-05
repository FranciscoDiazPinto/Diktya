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
- **Sin autenticación todavía**: `dependencies.require_monitoring_read` es un punto de
  integración vacío hasta que exista la Épica 001 (`Permission.MONITORING_READ`).
  No exponer estos endpoints fuera de la red de desarrollo.
- Mock: `MONITORING_MOCK_SCENARIO=degraded|outage` permite probar el dashboard ante fallos.
