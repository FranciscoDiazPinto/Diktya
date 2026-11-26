import { useState } from "react";
import {
  formatRate,
  formatBytes,
  formatCount,
  formatDuration,
  clockTime,
  endpoint,
} from "../../modules/format.mjs";
export function TrafficChart({ series, unavailableReason }) {
  const points = series?.find((s) => s.interface_id === "wan")?.points || [];
  if (points.length < 2)
    return <p className="empty-state">{unavailableReason || "Recolectando muestras de tráfico…"}</p>;
  const max =
    Math.max(
      ...points.flatMap((p) => [p.bytes_in_per_second, p.bytes_out_per_second]),
    ) * 1.15 || 1;
  const start = new Date(points[0].timestamp).getTime(),
    span = new Date(points.at(-1).timestamp).getTime() - start || 1;
  const line = (key) =>
    "M" +
    points
      .map(
        (p) =>
          `${((new Date(p.timestamp).getTime() - start) / span) * 760},${190 - (p[key] / max) * 180}`,
      )
      .join(" L");
  return (
    <>
      <div className="chart-area">
        <div className="y-axis">
          {[1, 0.75, 0.5, 0.25, 0].map((f) => (
            <span key={f}>{formatRate(max * f)}</span>
          ))}
        </div>
        <div className="chart">
          <svg
            viewBox="0 0 760 190"
            preserveAspectRatio="none"
            role="img"
            aria-label="Tráfico WAN de entrada y salida"
          >
            <path
              className="area-fill"
              d={line("bytes_in_per_second") + " L760,190 L0,190 Z"}
            />
            <path
              className="line inbound-line"
              d={line("bytes_in_per_second")}
            />
            <path
              className="line outbound-line"
              d={line("bytes_out_per_second")}
            />
          </svg>
          <div className="x-axis">
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <span key={f}>{clockTime(start + span * f)}</span>
            ))}
          </div>
        </div>
      </div>
      <details className="traffic-data">
        <summary>Ver datos del tráfico WAN</summary>
        <Table
          caption="Muestras del tráfico WAN"
          head={["Hora", "Entrada", "Salida"]}
          rows={points.map((p) => [
            new Date(p.timestamp).toLocaleString("es-CL"),
            formatRate(p.bytes_in_per_second),
            formatRate(p.bytes_out_per_second),
          ])}
        />
      </details>
    </>
  );
}
function Table({ caption, head, rows, empty = "Sin datos disponibles." }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length ? (
            rows.map((row, i) => (
              <tr key={i}>
                {row.map((c, j) => (
                  <td key={j}>{c ?? "–"}</td>
                ))}
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={head.length} className="empty-state">
                {empty}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
const RESOURCE_LABELS = {
  system: "Estado del sistema",
  interfaces: "Interfaces",
  traffic: "Tráfico WAN",
  clients: "Clientes DHCP",
  stats: "Estadísticas del firewall",
  events: "Eventos del firewall",
};

const denied = (resource) => resource?.issues?.some((issue) => issue.kind === "permission");
const missingPermission = (resource) =>
  resource?.source === "opnsense" ? "Permiso insuficiente en OPNsense." :
    resource?.source === "noc" ? "Permiso insuficiente en el NOC." : "Permiso insuficiente en la fuente.";

export function MonitoringNotices({ monitoring }) {
  const resources = Object.entries(monitoring.data),
    problems = resources.filter(([, r]) => r.status !== "ok" || r.stale);
  return (
    <>
      {monitoring.error && (
        <p className="issues-banner critical" role="alert">
          {monitoring.error}
        </p>
      )}
      {problems.length > 0 && (
        <div className="issues-banner" role="status">
          <strong>Datos parciales o anteriores</strong>
          <ul>
            {problems.map(([key, r]) => (
              <li key={key}>
                {RESOURCE_LABELS[key] || key} · {r.stale ? "Datos anteriores" :
                  r.status === "degraded" ? "Lectura parcial" : "No disponible"}
                {denied(r) ? " · " + missingPermission(r) : ""}
                {r.collected_at ? " · " + clockTime(r.collected_at) : ""}
                {r.source === "mock" ? " · Simulación" : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
export function MonitoringOverview({ monitoring }) {
  const d = monitoring.data,
    interfaces = d.interfaces?.data,
    clients = d.clients?.data,
    stats = d.stats?.data,
    sys = d.system?.data;
  const wan = d.traffic?.data
    ?.find((s) => s.interface_id === "wan")
    ?.points?.at(-1);
  const cards = [
    [
      "INTERFACES ACTIVAS",
      interfaces
        ? `${interfaces.filter((i) => i.status === "up").length} / ${interfaces.length}`
        : "–",
      d.interfaces,
    ],
    [
      "TRÁFICO WAN",
      wan
        ? formatRate(wan.bytes_in_per_second + wan.bytes_out_per_second)
        : "–",
      d.traffic,
    ],
    [
      "CLIENTES ACTIVOS",
      clients ? clients.filter((c) => c.active).length : "–",
      d.clients,
    ],
    d.stats?.source === "noc"
      ? ["BLOQUEOS REGISTRADOS · 5 MIN", formatCount(stats?.logged_blocked_packets_5m), d.stats]
      : ["PAQUETES BLOQUEADOS", formatCount(stats?.packets_blocked), d.stats],
  ];
  const labels = ["lime", "orange", "blue", "red"];
  return (
    <>
      <section className="stats-grid" aria-label="Indicadores principales">
        {cards.map(([label, value, resource], i) => (
          <article className={"stat-card accent-" + labels[i]} key={label}>
            <div className="stat-top">
              <span className="stat-label">{label}</span>
            </div>
            <div className="stat-value">{value}</div>
            <div className="stat-meta">
              {resource?.stale
                ? "Datos anteriores"
                : resource?.status === "ok"
                  ? "Última lectura disponible"
                  : denied(resource)
                    ? missingPermission(resource)
                    : "Sin datos completos"}
              {resource?.source === "mock" ? " · Simulación" : ""}
            </div>
          </article>
        ))}
      </section>
      <section className="dashboard-grid">
        <article className="panel traffic-panel">
          <div className="panel-heading">
            <h2>Uso de red WAN</h2>
            <span>Entrada / salida{d.traffic?.source === "noc" ? " · NOC" : ""}</span>
          </div>
          <TrafficChart
            series={d.traffic?.data}
            unavailableReason={denied(d.traffic) ? missingPermission(d.traffic) :
              d.traffic?.status === "unavailable" ? "Tráfico WAN no disponible." : undefined}
          />
        </article>
        <article className="panel system-panel">
          <div className="panel-heading">
            <h2>Estado del sistema</h2>
          </div>
          {sys ? (
            <dl className="system-list">
              {[
                ["Equipo", sys.hostname],
                ["CPU", sys.cpu_percent == null ? "–" : sys.cpu_percent + " %"],
                [
                  "Memoria",
                  sys.memory?.used_percent == null
                    ? "–"
                    : sys.memory?.used_percent + " %",
                ],
                [
                  "Temperatura",
                  sys.temperature?.available &&
                  sys.temperature.value_celsius != null
                    ? sys.temperature.value_celsius + " °C"
                    : "No disponible",
                ],
                ["Tiempo encendido", formatDuration(sys.uptime_seconds)],
                ["Versión", sys.version],
              ].map(([k, v]) => (
                <div className="system-row" key={k}>
                  <dt>{k}</dt>
                  <dd>{v ?? "–"}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="empty-state">Sistema no disponible.</p>
          )}
        </article>
        <article className="panel activity-panel">
          <div className="panel-heading">
            <h2>Actividad reciente</h2>
            <a href="#firewall">Ver todo</a>
          </div>
          <ul className="activity-list">
            {(d.events?.data || []).slice(0, 6).map((e, i) => (
              <li key={i}>
                {clockTime(e.timestamp)} ·{" "}
                {e.action === "block" ? "Bloqueado" : "Permitido"} ·{" "}
                {endpoint(e.source_ip, e.source_port)} →{" "}
                {endpoint(e.destination_ip, e.destination_port)}
              </li>
            ))}
          </ul>
        </article>
      </section>
    </>
  );
}
export function Interfaces({ monitoring }) {
  return (
    <article className="panel wide-panel">
      <div className="panel-heading">
        <h2>Interfaces</h2>
      </div>
      <Table
        caption="Interfaces de red"
        head={[
          "Interfaz",
          "Estado",
          "Direcciones IP",
          "Tráfico acumulado",
          "Errores",
        ]}
        rows={(monitoring.data.interfaces?.data || []).map((i) => [
          i.description || i.name,
          i.status,
          (i.ip_addresses || []).join(", "),
          i.traffic?.bytes_in != null && i.traffic?.bytes_out != null
            ? formatBytes(i.traffic.bytes_in + i.traffic.bytes_out)
            : "–",
          i.traffic?.errors_in != null && i.traffic?.errors_out != null
            ? i.traffic.errors_in + i.traffic.errors_out
            : "–",
        ])}
      />
    </article>
  );
}
export function Clients({ monitoring }) {
  const [query, setQuery] = useState(""),
    [active, setActive] = useState(false);
  const clients = (monitoring.data.clients?.data || []).filter(
    (c) =>
      (!active || c.active) &&
      [c.hostname, c.ip_address, c.mac_address, c.interface].some((v) =>
        String(v || "")
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
  );
  return (
    <article className="panel wide-panel">
      <div className="panel-heading">
        <h2>Clientes DHCP</h2>
      </div>
      <div className="chat-controls">
        <label>
          Buscar cliente
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
          />{" "}
          Solo activos
        </label>
      </div>
      <Table
        caption="Clientes DHCP"
        head={["Equipo", "IP", "MAC", "Interfaz", "Vencimiento", "Estado"]}
        rows={clients.map((c) => [
          c.hostname || "Sin nombre",
          c.ip_address,
          c.mac_address,
          c.interface,
          c.expires_at
            ? new Date(c.expires_at).toLocaleString("es-CL")
            : "Estática",
          c.active ? "Activo" : "Vencido",
        ])}
      />
    </article>
  );
}
export function Firewall({ monitoring }) {
  const [action, setAction] = useState(""),
    stats = monitoring.data.stats?.data;
  const events = (monitoring.data.events?.data || [])
    .filter((e) => !action || action === e.action)
    .slice(0, 50);
  return (
    <article className="panel wide-panel">
      <div className="panel-heading">
        <h2>Firewall</h2>
        {monitoring.data.stats?.source === "noc" && <span>Estadísticas del NOC</span>}
      </div>
      <label>
        Filtrar eventos
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">Todos</option>
          <option value="block">Bloqueados</option>
          <option value="pass">Permitidos</option>
        </select>
      </label>
      <div className="fw-summary">
        {[
          [
            "Filtro pf",
            stats?.pf_enabled == null
              ? "Desconocido"
              : stats.pf_enabled
                ? "Activo"
                : "Inactivo",
          ],
          ["Estados", formatCount(stats?.states?.current_entries)],
          ["Permitidos", formatCount(stats?.packets_passed)],
          monitoring.data.stats?.source === "noc"
            ? ["Bloqueos registrados · 5 min", formatCount(stats?.logged_blocked_packets_5m)]
            : ["Bloqueados", formatCount(stats?.packets_blocked)],
        ].map(([k, v]) => (
          <div key={k}>
            <small>{k}</small>
            <strong>{v}</strong>
          </div>
        ))}
      </div>
      <Table
        caption="Eventos del firewall"
        head={["Hora", "Acción", "Interfaz", "Origen", "Destino", "Protocolo"]}
        rows={events.map((e) => [
          clockTime(e.timestamp),
          e.action === "block" ? "Bloqueado" : "Permitido",
          e.interface,
          endpoint(e.source_ip, e.source_port),
          endpoint(e.destination_ip, e.destination_port),
          e.protocol,
        ])}
      />
    </article>
  );
}
