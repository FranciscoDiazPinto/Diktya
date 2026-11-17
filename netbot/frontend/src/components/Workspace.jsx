import { useId, useLayoutEffect, useRef } from "react";
import { useMobileNavigation } from "../hooks/useMobileNavigation.jsx";
import * as Markup from "./FeatureMarkup.jsx";
import { mountFeatures } from "../runtime/features.mjs";
import { navId, useNavigation, VIEWS } from "../hooks/useNavigation.jsx";
import { useMonitoring } from "../hooks/useMonitoring.jsx";
import {
  MonitoringOverview,
  MonitoringNotices,
  Interfaces,
  Clients,
  Firewall,
} from "./Monitoring.jsx";
const PANELS = [
  ["devices", "DevicesMarkup"],
  ["alerts", "AlertsMarkup"],
  ["wireless", "WirelessMarkup"],
  ["coverage", "CoverageMarkup"],
  ["access-points-panel", "AccessPointsMarkup"],
  ["support-panel", "SupportMarkup"],
  ["tickets-panel", "TicketsMarkup"],
  ["provisioning", "ProvisioningMarkup"],
  ["audit", "AuditMarkup"],
  ["users", "UsersMarkup"],
  ["system", "SystemMarkup"],
  ["account", "AccountMarkup"],
];
const COUNTS = {
  alerts: "nav-alerts",
  interfaces: "nav-interfaces",
  clients: "nav-clients",
  firewall: "nav-blocked",
};
export function Workspace({ runtime }) {
  const { user } = runtime.state,
    root = useRef(null),
    features = useRef(null);
  const { view, navigate, allowed } = useNavigation(user),
    mobile = useMobileNavigation();
  const headingId = useId();
  const global = user.permissions?.includes("monitoring:read"),
    monitoring = useMonitoring(runtime, global);
  const heading = useRef(null);
  runtime.currentView = view;
  const route = useRef(navigate);
  route.current = navigate;
  useLayoutEffect(() => {
    features.current = mountFeatures(root.current, runtime, (key) =>
      route.current(key),
    );
    return () => {
      features.current.dispose();
      features.current = null;
    };
  }, [runtime]);
  useLayoutEffect(() => {
    if (view !== "support-panel") features.current?.support.clearWifiAccess();
    mobile.close(false);
    heading.current?.focus({ preventScroll: true });
    document.title = `${VIEWS.find((v) => v[0] === view)?.[1] || "Resumen"} | Netbot`;
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view, mobile.close]);
  const canView = (key) => allowed.some((v) => v[0] === key),
    name = user.full_name || user.email.split("@")[0],
    source = monitoring.data.system?.source;
  const resources = Object.values(monitoring.data);
  const stale = resources.some((r) => r.stale);
  const health =
    monitoring.error ||
    !resources.length ||
    resources.some((r) => r.status === "unavailable")
      ? "unavailable"
      : stale || resources.some((r) => r.status !== "ok")
        ? "degraded"
        : "ok";
  const counts = {
    interfaces: monitoring.data.interfaces?.data?.length,
    clients: monitoring.data.clients?.data?.filter((c) => c.active).length,
    firewall: monitoring.data.events?.data?.filter((e) => e.action === "block")
      .length,
  };
  const monitoringView =
    global && ["overview", "interfaces", "clients", "firewall"].includes(view);
  return (
    <div className="app-shell" id="app-shell" ref={root}>
      <a
        className="skip-link"
        href={"#" + headingId}
        onClick={(event) => {
          event.preventDefault();
          mobile.close(false);
          heading.current?.focus();
          heading.current?.scrollIntoView({ block: "start" });
        }}
      >
        Saltar al contenido
      </a>
      <aside
        id="workspace-navigation"
        ref={mobile.sidebar}
        hidden={mobile.small && !mobile.open}
        className={"sidebar" + (mobile.open ? " open" : "")}
      >
        <button
          type="button"
          className="navigation-close"
          ref={mobile.closeButton}
          hidden={!mobile.small}
          onClick={() => mobile.close()}
        >
          Cerrar navegación
        </button>
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <strong>netbot</strong>
            <small>network intelligence</small>
          </div>
        </div>
        <nav className="main-nav" aria-label="Navegación principal">
          <p className="nav-label">Workspace</p>
          {VIEWS.map(([key, title]) => (
            <a
              key={key}
              id={navId(key)}
              className={"nav-item" + (view === key ? " active" : "")}
              href={"#" + key}
              hidden={!canView(key)}
              aria-current={view === key ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(key);
                mobile.close(false);
                heading.current?.focus();
              }}
            >
              {title}
              {COUNTS[key] && <b id={COUNTS[key]}>{counts[key] ?? "–"}</b>}
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="connection-status">
            <span className={"status-dot " + (global ? health : "")} />
            <span>
              <strong>
                {global
                  ? source === "mock"
                    ? "Simulador"
                    : source || "Sin fuente"
                  : "Acceso personal"}
              </strong>
              <small>
                {global
                  ? stale
                    ? "Datos anteriores"
                    : health === "ok"
                      ? "Última lectura disponible"
                      : "Fuente parcial o sin datos"
                  : "Solo redes autorizadas"}
              </small>
            </span>
          </div>
          <div className="user-profile">
            <div className="avatar">{name.slice(0, 2).toUpperCase()}</div>
            <span>
              <strong>{name}</strong>
              <small>{user.roles.join(", ")}</small>
            </span>
            <button
              className="icon-button"
              aria-label="Cerrar sesión"
              onClick={() => runtime.signOut("Sesión cerrada")}
            >
              ↪
            </button>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar">
          <button
            className="mobile-menu"
            aria-label="Abrir navegación"
            aria-expanded={mobile.small && mobile.open}
            aria-controls="workspace-navigation"
            ref={mobile.trigger}
            onClick={mobile.toggle}
          >
            ☰
          </button>
          <div className="breadcrumbs">
            <span>Workspace</span>
            <i>/</i>
            <strong>{VIEWS.find((v) => v[0] === view)?.[1]}</strong>
          </div>
          <div className="topbar-actions">
            <button
              className="refresh-button"
              id="notifications-button"
              type="button"
              hidden
              aria-expanded="false"
              aria-controls="notifications-panel"
            >
              Notificaciones{" "}
              <b className="alert-count" id="notifications-count">
                0
              </b>
            </button>
            {monitoringView && (
              <>
                <span className="last-sync">
                  Última consulta{" "}
                  <strong>
                    {monitoring.lastSync?.toLocaleTimeString("es-CL") || "–"}
                  </strong>
                </span>
                <button
                  className="refresh-button"
                  disabled={monitoring.busy}
                  onClick={monitoring.refresh}
                >
                  Actualizar
                </button>
              </>
            )}
          </div>
        </header>
        <div className="content-wrap">
          <Markup.NotificationsMarkup />
          <section className="page-heading">
            <div>
              <p className="eyebrow">
                {new Date().toLocaleDateString("es-CL", {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                })}
              </p>
              <h1 id={headingId} ref={heading} tabIndex={-1}>
                {view === "overview"
                  ? `Hola, ${name}`
                  : VIEWS.find((v) => v[0] === view)?.[1]}
              </h1>
              <p className="heading-copy">
                {view === "overview"
                  ? "Tu infraestructura, conversaciones y solicitudes autorizadas."
                  : ""}
              </p>
            </div>
            {global && view === "overview" && (
              <div
                className="period-picker"
                role="group"
                aria-label="Ventana del gráfico"
              >
                {[
                  [300, "5 min"],
                  [900, "15 min"],
                  [3600, "1 h"],
                ].map(([v, label]) => (
                  <button
                    key={v}
                    className={
                      "period" +
                      (monitoring.windowSeconds === v ? " active" : "")
                    }
                    aria-pressed={monitoring.windowSeconds === v}
                    onClick={() => monitoring.setWindow(v)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </section>
          {monitoringView && <MonitoringNotices monitoring={monitoring} />}
          <section hidden={view !== "overview"} aria-label="Resumen">
            <div
              className={"overview-with-chat" + (!global ? " personal" : "")}
            >
              <div hidden={!global} className="overview-monitoring">
                <Markup.InventorySummary />
                {global && <MonitoringOverview monitoring={monitoring} />}
              </div>
              {!global && (
                <div className="overview-shortcuts">
                  {allowed
                    .filter((v) => v[0] !== "overview")
                    .map(([key, title]) => (
                      <a
                        key={key}
                        className="overview-shortcut"
                        href={"#" + key}
                      >
                        <strong>{title}</strong>
                      </a>
                    ))}
                </div>
              )}
              <div
                className="chat-host"
                hidden={!user.permissions?.includes("chat:use")}
              >
                <Markup.ChatMarkup />
              </div>
            </div>
          </section>
          {PANELS.map(([key, component]) => {
            const Panel = Markup[component];
            return (
              <div key={key} hidden={view !== key || !canView(key)}>
                <Panel
                  canReserve={user.permissions?.includes("vlan:reserve")}
                />
              </div>
            );
          })}
          {global && (
            <>
              <section hidden={view !== "interfaces"}>
                <Interfaces monitoring={monitoring} />
              </section>
              <section hidden={view !== "clients"}>
                <Clients monitoring={monitoring} />
              </section>
              <section hidden={view !== "firewall"}>
                <Firewall monitoring={monitoring} />
              </section>
            </>
          )}
          <footer className="page-footer">
            <span>Netbot</span>
            <span>
              {global
                ? source === "mock"
                  ? "DEMOSTRACIÓN · Fuente simulada"
                  : "Lecturas de red sujetas a frescura y disponibilidad"
                : "Acceso por ámbito autorizado"}
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
