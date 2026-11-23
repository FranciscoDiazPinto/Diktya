// Static React views. Controllers own only their isolated form/list contents.
import { memo } from "react";

export const GuestMarkup = memo(function GuestMarkup() {
  return (
    <section
      id="guest-screen"
      className="guest-screen"
      aria-labelledby="guest-heading"
    >
      {"\n      "}
      <header className="guest-header">
        <a className="guest-brand" href="./">
          {"netbot"}
          <span>{"autoatención"}</span>
        </a>
        <button id="guest-login" type="button">
          {"Iniciar sesión · Equipo"}
        </button>
      </header>
      {"\n      "}
      <main className="guest-layout">
        {"\n        "}
        <div className="guest-welcome">
          <p className="eyebrow">{"ESTAMOS PARA AYUDARTE"}</p>
          <h1 id="guest-heading">
            {"Conéctate."}
            <br />
            {"Nosotros te guiamos."}
          </h1>
          <p>
            {
              "Consulta cómo conectarte al portal de invitados. Para recuperar credenciales de expositor, verifica tu correo mediante un enlace de confirmación."
            }
          </p>
          <p className="guest-privacy">
            {
              "Tu atención y el QR se limpian después de un minuto sin respuesta. No ingreses contactos ni contraseñas en el chat. Las consultas generales al asistente se procesan en OpenRouter."
            }
          </p>
        </div>
        {"\n        "}
        <section className="panel guest-chat" aria-label="Chat de invitados">
          {"\n          "}
          <div className="panel-heading">
            <h2>{"Hola, soy Netbot"}</h2>
            <span className="chat-scope">{"Sin cuenta"}</span>
          </div>
          {"\n          "}
          <div
            id="guest-messages"
            className="chat-messages"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
          ></div>
          {"\n          "}
          <form
            id="guest-identify-form"
            className="reservation-card"
            hidden
            autoComplete="off"
          >
            {"\n            "}
            <label htmlFor="guest-contact">
              {"Correo registrado para recuperar acceso de expositor"}
            </label>
            {"\n            "}
            <input
              id="guest-contact"
              type="email"
              maxLength="320"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck="false"
              placeholder="expositor@ejemplo.cl"
              required
            />
            {"\n            "}
            <p>
              {
                "Si tienes acceso de expositor habilitado, enviaremos un enlace al correo registrado. Debes confirmarlo para ver el QR. No necesitas una cuenta de Netbot."
              }
            </p>
            {"\n            "}
            <button id="guest-identify-submit" type="submit">
              {"Enviar enlace de confirmación"}
            </button>
            {"\n            "}
            <p id="guest-identify-error" role="status"></p>
            {"\n          "}
          </form>
          {"\n          "}
          <div id="guest-wifi" className="reservation-card" hidden>
            {"\n            "}
            <label htmlFor="guest-network">
              {"Red disponible para esta atención"}
            </label>
            <select id="guest-network"></select>
            {"\n            "}
            <button id="guest-show-qr" type="button">
              {"Mostrar QR para conectarme"}
            </button>
            {"\n            "}
            <div id="guest-qr" aria-live="polite"></div>
            {"\n          "}
          </div>
          {"\n          "}
          <div id="guest-resolution" className="guest-resolution" hidden>
            <p id="guest-question"></p>
            <div className="reservation-actions">
              <button id="guest-yes" type="button">
                {"Sí, se resolvió"}
              </button>
              <button id="guest-no" type="button">
                {"Necesito más ayuda"}
              </button>
            </div>
          </div>
          {"\n          "}
          <form id="guest-form" className="chat-form">
            <label className="visually-hidden" htmlFor="guest-message">
              {"Tu consulta"}
            </label>
            <textarea
              id="guest-message"
              maxLength="2000"
              rows="2"
              placeholder="Ej.: ¿Cómo me conecto al Wi-Fi?"
              required
            ></textarea>
            <button id="guest-send" className="chat-send" type="submit">
              {"Enviar →"}
            </button>
          </form>
          {"\n          "}
          <p id="guest-status" className="chat-status" role="status"></p>
          {"\n          "}
          <div className="guest-actions">
            <button id="guest-wifi-button" type="button">
              {"Recuperar mi acceso Wi-Fi"}
            </button>
            <button id="guest-portal-button" type="button">
              {"Portal de invitados"}
            </button>
            <button id="guest-finish" type="button">
              {"Finalizar atención"}
            </button>
          </div>
          {"\n        "}
        </section>
        {"\n      "}
      </main>
      {"\n    "}
    </section>
  );
});

export const ChatMarkup = memo(function ChatMarkup() {
  return (
    <section
      className="panel chat-panel"
      id="chat"
      aria-labelledby="chat-heading"
    >
      {"\n            "}
      <div className="panel-heading">
        {"\n              "}
        <div>
          <p className="panel-kicker">{"ASISTENTE DE REDES"}</p>
          <h2 id="chat-heading">{"Conversa con Netbot"}</h2>
        </div>
        {"\n              "}
        <span className="chat-scope" id="chat-scope">
          {"Asistente"}
        </span>
        {"\n            "}
      </div>
      {"\n            "}
      <p className="chat-intro">
        {
          "Consulta las redes que tienes autorizadas. Tus conversaciones se guardan en tu cuenta. Las consultas y los datos necesarios se procesan en OpenRouter. No envíes contraseñas por el chat."
        }
      </p>
      {"\n\n            "}
      <div className="chat-controls">
        {"\n              "}
        <label htmlFor="chat-conversation">{"Conversación"}</label>
        {"\n              "}
        <select id="chat-conversation">
          <option value="">{"Nueva conversación"}</option>
        </select>
        {"\n              "}
        <label htmlFor="chat-network">{"Red para nueva conversación"}</label>
        {"\n              "}
        <select id="chat-network">
          <option value="">{"Mis redes autorizadas"}</option>
        </select>
        {"\n              "}
        <button id="chat-new" type="button">
          {"Nueva"}
        </button>
        {"\n            "}
      </div>
      {"\n            "}
      <button id="chat-older" type="button" hidden>
        {"Ver mensajes anteriores"}
      </button>
      {"\n            "}
      <div
        className="chat-messages"
        id="chat-messages"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        {"\n              "}
        <p className="chat-empty" id="chat-empty">
          {"Selecciona una conversación o escribe para comenzar."}
        </p>
        {"\n            "}
      </div>
      {"\n\n            "}
      <form className="chat-form" id="chat-form">
        {"\n              "}
        <label className="visually-hidden" htmlFor="chat-message">
          {"Mensaje para el asistente"}
        </label>
        {"\n              "}
        <textarea
          id="chat-message"
          name="message"
          rows="2"
          maxLength="2000"
          placeholder="Ej.: ¿Qué interfaces están caídas?"
          required
        ></textarea>
        {"\n              "}
        <button className="chat-send" id="chat-send" type="submit">
          {"Enviar "}
          <span aria-hidden="true">{"→"}</span>
        </button>
        {"\n            "}
      </form>
      {"\n            "}
      <p
        className="chat-status"
        id="chat-status"
        role="status"
        aria-live="polite"
      ></p>
      {"\n          "}
    </section>
  );
});

export const InventorySummary = memo(function InventorySummary() {
  return (
    <article className="panel wide-panel" id="inventory">
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"INVENTARIO"}</p>
          <h2>{"Estado de la red"}</h2>
        </div>
        <span className="last-sync">
          {"Actualizado "}
          <strong id="inventory-updated">{"–"}</strong>
        </span>
      </div>
      <p
        className="inventory-stale"
        id="inventory-stale"
        role="status"
        hidden
      ></p>
      <div className="fw-summary inventory-kpis" id="inventory-kpis"></div>
      <div
        className="inventory-sources"
        id="inventory-sources"
        aria-label="Estado de las integraciones"
      ></div>
    </article>
  );
});

export const DevicesMarkup = memo(function DevicesMarkup() {
  return (
    <section id="view-devices" className="app-view" aria-label="devices">
      <article className="panel wide-panel" id="devices">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"INFRAESTRUCTURA"}</p>
            <h2>{"Dispositivos"}</h2>
          </div>
          <div className="panel-tools">
            <label className="toggle-option" htmlFor="devices-state">
              {"Estado"}
            </label>
            <select id="devices-state">
              <option value="">{"Todos"}</option>
              <option value="online">{"En línea"}</option>
              <option value="degraded">{"Degradado"}</option>
              <option value="offline">{"Fuera de línea"}</option>
              <option value="maintenance">{"Mantención"}</option>
              <option value="unknown">{"Desconocido"}</option>
            </select>
            <label className="toggle-option" htmlFor="devices-type">
              {"Tipo"}
            </label>
            <select id="devices-type">
              <option value="">{"Todos"}</option>
              <option value="ap">{"AP"}</option>
              <option value="switch">{"Switch"}</option>
              <option value="gateway">{"Gateway"}</option>
              <option value="firewall">{"Firewall"}</option>
              <option value="unknown">{"Desconocido"}</option>
            </select>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{"Nombre"}</th>
                <th>{"Tipo"}</th>
                <th>{"IP"}</th>
                <th>{"Estado"}</th>
                <th>{"Última vez visto"}</th>
              </tr>
            </thead>
            <tbody id="devices-body">
              <tr>
                <td colSpan="5" className="empty-state">
                  {"Cargando dispositivos…"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="inventory-pager">
          <button id="devices-prev" type="button">
            {"Anterior"}
          </button>
          <span id="devices-page"></span>
          <button id="devices-next" type="button">
            {"Siguiente"}
          </button>
        </div>
      </article>
    </section>
  );
});

export const AlertsMarkup = memo(function AlertsMarkup() {
  return (
    <section id="view-alerts" className="app-view" aria-label="alerts">
      <article className="panel wide-panel" id="alerts">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"INCIDENTES"}</p>
            <h2>{"Alertas activas"}</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{"Severidad"}</th>
                <th>{"Dispositivo"}</th>
                <th>{"Mensaje"}</th>
                <th>{"Detectada"}</th>
              </tr>
            </thead>
            <tbody id="alerts-body">
              <tr>
                <td colSpan="4" className="empty-state">
                  {"Cargando alertas…"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
});

export const WirelessMarkup = memo(function WirelessMarkup() {
  return (
    <section id="view-wireless" className="app-view" aria-label="wireless">
      <article className="panel wide-panel" id="wireless">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"REDES"}</p>
            <h2>{"SSID y VLAN"}</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{"SSID"}</th>
                <th>{"Estado"}</th>
                <th>{"Seguridad"}</th>
                <th>{"VLAN"}</th>
              </tr>
            </thead>
            <tbody id="ssids-body"></tbody>
          </table>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{"VLAN"}</th>
                <th>{"Nombre"}</th>
                <th>{"Fuente"}</th>
              </tr>
            </thead>
            <tbody id="vlans-body"></tbody>
          </table>
        </div>
      </article>
    </section>
  );
});

export const CoverageMarkup = memo(function CoverageMarkup() {
  return (
    <section id="view-coverage" className="app-view" aria-label="coverage">
      <article className="panel wide-panel" id="coverage">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"RECINTO"}</p>
            <h2>{"Planos de cobertura"}</h2>
          </div>
          <div className="panel-tools">
            <label className="toggle-option" htmlFor="plan-select">
              {"Plano"}
            </label>
            <select id="plan-select">
              <option value="">{"Selecciona un plano"}</option>
            </select>
            <button id="plan-delete" type="button" hidden>
              {"Eliminar plano"}
            </button>
          </div>
        </div>
        <form id="plan-form" className="chat-controls" hidden>
          <label htmlFor="plan-name">{"Nombre"}</label>
          <input id="plan-name" maxLength="120" required />
          <label htmlFor="plan-file">{"Imagen PNG o JPEG"}</label>
          <input
            id="plan-file"
            type="file"
            accept="image/png,image/jpeg"
            required
          />
          <button id="plan-upload" type="submit">
            {"Cargar plano"}
          </button>
        </form>
        <p id="plan-status" role="status"></p>
        <div className="plan-layout">
          <div className="plan-stage" id="plan-stage" hidden>
            <img id="plan-image" alt="Plano del recinto" />
            <div id="plan-markers"></div>
          </div>
          <aside className="plan-side">
            <h3>{"Sin ubicar"}</h3>
            <div id="plan-unplaced"></div>
            <h3>{"AP seleccionado"}</h3>
            <div id="plan-detail">
              <p className="empty-state">{"Selecciona un AP."}</p>
            </div>
          </aside>
        </div>
      </article>
    </section>
  );
});

export const AccessPointsMarkup = memo(function AccessPointsMarkup() {
  return (
    <section
      id="view-access-points-panel"
      className="app-view"
      aria-label="Puntos de acceso"
    >
      {"\n"}
      <section
        className="panel support-panel"
        id="access-points-panel"
        hidden
        aria-labelledby="ap-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"UNIFI · SOLO LECTURA"}</p>
            <h2 id="ap-heading">{"Puntos de acceso"}</h2>
          </div>
          <button id="ap-refresh" type="button">
            {"Actualizar AP"}
          </button>
        </div>
        {"\n            "}
        <div className="chat-controls">
          <label id="ap-network-label" htmlFor="ap-network">
            {"Red autorizada "}
            <select id="ap-network">
              <option value="">{"Selecciona una red"}</option>
            </select>
          </label>
        </div>
        {"\n            "}
        <p id="ap-status" role="status"></p>
        <p id="ap-interface-summary"></p>
        {"\n            "}
        <p>
          {
            "Estado reportado por el controlador. No demuestra conexión Wi-Fi ni salida a Internet. El heartbeat remoto puede no estar disponible."
          }
        </p>
        {"\n            "}
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{"AP / modelo"}</th>
                <th>{"Estado reportado"}</th>
                <th>{"Heartbeat remoto"}</th>
                <th>{"Tiempo encendido"}</th>
                <th>{"Telemetría"}</th>
              </tr>
            </thead>
            <tbody id="ap-body"></tbody>
          </table>
        </div>
        {"\n            "}
        <div id="ap-pagination" className="chat-controls" hidden>
          <button id="ap-previous" type="button">
            {"Anterior"}
          </button>
          <span id="ap-page"></span>
          <button id="ap-next" type="button">
            {"Siguiente"}
          </button>
        </div>
        {"\n          "}
      </section>
      {"\n          "}
    </section>
  );
});

export const SupportMarkup = memo(function SupportMarkup() {
  return (
    <section id="view-support-panel" className="app-view" aria-label="Mi red">
      {"\n"}
      <section
        className="panel support-panel"
        id="support-panel"
        hidden
        aria-labelledby="support-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"SOPORTE"}</p>
            <h2 id="support-heading">{"Mi acceso y mi red"}</h2>
          </div>
        </div>
        {"\n            "}
        <div className="chat-controls">
          {"\n              "}
          <label htmlFor="support-network">{"Red autorizada"}</label>
          <select id="support-network">
            <option value="">{"Selecciona una red"}</option>
          </select>
          {"\n              "}
          <button id="support-status" type="button">
            {"Comprobar estado"}
          </button>
          {"\n              "}
          <button id="support-access" type="button">
            {"Ver acceso Wi-Fi"}
          </button>
          {"\n            "}
        </div>
        {"\n            "}
        <p id="support-result" role="status"></p>
        {"\n            "}
        <div
          id="wifi-access-panel"
          className="reservation-card"
          hidden
          aria-live="polite"
        ></div>
        {"\n            "}
        <form id="ticket-form" className="support-form">
          {"\n              "}
          <h3>{"Solicitar ayuda técnica"}</h3>
          {"\n              "}
          <label htmlFor="ticket-summary">{"Resumen"}</label>
          <input
            id="ticket-summary"
            minLength="3"
            maxLength="160"
            required
            placeholder="No puedo conectarme a mi red"
          />
          {"\n              "}
          <label htmlFor="ticket-description">
            {"Describe el problema, sin contraseñas"}
          </label>
          <textarea
            id="ticket-description"
            maxLength="2000"
            required
            rows="3"
          ></textarea>
          {"\n              "}
          <button id="ticket-submit" type="submit">
            {"Crear ticket"}
          </button>
          {"\n            "}
        </form>
        {"\n            "}
        <p id="ticket-feedback" role="status"></p>
        {"\n          "}
      </section>
      {"\n"}
      <section
        className="panel support-panel"
        id="wifi-recipients-panel"
        hidden
        aria-labelledby="wifi-recipients-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"ADMINISTRACIÓN"}</p>
            <h2 id="wifi-recipients-heading">
              {"Destinatarios de credenciales Wi-Fi"}
            </h2>
          </div>
        </div>
        {"\n            "}
        <p className="chat-intro">
          {
            "Administra el registro de destinatarios. Solo las redes clasificadas para expositores admiten recuperación por correo. Administración, Marketing y Servicios quedan excluidas."
          }
        </p>
        {"\n            "}
        <form id="wifi-recipients-form" className="support-form">
          {"\n              "}
          <label htmlFor="wifi-recipients-network">{"Red del cliente"}</label>
          <select id="wifi-recipients-network">
            <option value="">{"Selecciona una red"}</option>
          </select>
          {"\n              "}
          <label htmlFor="wifi-recovery-purpose">
            {"Finalidad de la red para recuperación"}
          </label>
          {"\n              "}
          <select id="wifi-recovery-purpose">
            <option value="disabled">{"No habilitada"}</option>
            <option value="expositor">{"Expositores"}</option>
            <option value="administracion">
              {"Administración · excluida"}
            </option>
            <option value="marketing">{"Marketing · excluida"}</option>
            <option value="servicios">{"Servicios · excluida"}</option>
          </select>
          {"\n              "}
          <button id="wifi-recovery-save" type="button" disabled>
            {"Guardar finalidad de la red"}
          </button>
          {"\n              "}
          <label htmlFor="wifi-recipients-contacts">
            {"Destinatarios: una línea por cliente, correo;teléfono"}
          </label>
          {"\n              "}
          <textarea
            id="wifi-recipients-contacts"
            rows="5"
            maxLength="200000"
            placeholder="cliente@ejemplo.cl;+56912345678\notro@ejemplo.cl;\n;+56987654321"
          ></textarea>
          {"\n              "}
          <p>
            {
              "Se requiere correo o teléfono en cada línea. Teléfonos con código de país. Guardar reemplaza la lista de la red seleccionada; una lista vacía revoca su recuperación."
            }
          </p>
          {"\n              "}
          <button id="wifi-recipients-save" type="submit" disabled>
            {"Guardar destinatarios de esta red"}
          </button>
          {"\n            "}
        </form>
        {"\n            "}
        <p id="wifi-recipients-status" role="status"></p>
        {"\n          "}
      </section>
      {"\n          "}
    </section>
  );
});

export const TicketsMarkup = memo(function TicketsMarkup() {
  return (
    <section id="view-tickets-panel" className="app-view" aria-label="Tickets">
      {"\n"}
      <section
        className="panel support-panel"
        id="tickets-panel"
        hidden
        aria-labelledby="tickets-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"SEGUIMIENTO"}</p>
            <h2 id="tickets-heading">{"Tickets autorizados"}</h2>
          </div>
          <div className="panel-tools">
            <label className="toggle-option" htmlFor="tickets-status">
              {"Estado"}
            </label>
            <select id="tickets-status">
              <option value="">{"Todos"}</option>
              <option value="open">{"Abierto"}</option>
              <option value="in_progress">{"En progreso"}</option>
              <option value="resolved">{"Resuelto"}</option>
              <option value="closed">{"Cerrado"}</option>
            </select>
            <label className="toggle-option" htmlFor="tickets-criticality">
              {"Criticidad"}
            </label>
            <select id="tickets-criticality">
              <option value="">{"Todas"}</option>
              <option value="critica">{"Crítica"}</option>
              <option value="alta">{"Alta"}</option>
              <option value="media">{"Media"}</option>
              <option value="baja">{"Baja"}</option>
            </select>
            <label className="toggle-option">
              <input type="checkbox" id="tickets-mine" />
              {" Asignados a mí"}
            </label>
            <button id="tickets-refresh" type="button">
              {"Actualizar"}
            </button>
          </div>
        </div>
        {"\n            "}
        <form id="ticket-manual-form" className="support-form" hidden>
          {"\n              "}
          <h3>{"Crear ticket técnico"}</h3>
          {"\n              "}
          <label htmlFor="manual-summary">{"Resumen"}</label>
          <input id="manual-summary" minLength="3" maxLength="160" required />
          {"\n              "}
          <label htmlFor="manual-description">{"Descripción"}</label>
          <textarea
            id="manual-description"
            maxLength="2000"
            required
            rows="2"
          ></textarea>
          {"\n              "}
          <label htmlFor="manual-criticality">{"Criticidad"}</label>
          <select id="manual-criticality" defaultValue="media">
            <option value="baja">{"Baja"}</option>
            <option value="media">{"Media"}</option>
            <option value="alta">{"Alta"}</option>
            <option value="critica">{"Crítica"}</option>
          </select>
          {"\n              "}
          <button id="manual-submit" type="submit">
            {"Crear ticket técnico"}
          </button>
          {"\n              "}
          <p id="manual-feedback" role="status"></p>
          {"\n            "}
        </form>
        {"\n            "}
        <div id="tickets-list" className="reservation-list"></div>
        {"\n          "}
      </section>
      {"\n          "}
    </section>
  );
});

export const ProvisioningMarkup = memo(function ProvisioningMarkup({
  canReserve = false,
}) {
  return (
    <section
      id="view-provisioning"
      className="app-view"
      aria-label="Aprovisionamiento"
    >
      {"\n"}
      <section
        className="panel support-panel"
        id="ssid-panel"
        hidden
        aria-labelledby="ssid-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"APROVISIONAMIENTO · PROPUESTAS"}</p>
            <h2 id="ssid-heading">{"Planes de SSID por ámbito"}</h2>
          </div>
          <button id="ssid-refresh" type="button">
            {"Recuperar planes"}
          </button>
        </div>
        {"\n            "}
        <p className="chat-intro">
          {
            "Prepara una creación o carga CSV con AP concretos y VLAN existentes. Confirmar registra la aprobación. Un ejecutor separado aplica los cambios solo si está configurado; recupera los planes para consultar su estado."
          }
        </p>
        {"\n            "}
        <form id="ssid-form" className="support-form">
          {"\n              "}
          <label htmlFor="ssid-scope">{"Ámbito autorizado"}</label>
          <select id="ssid-scope">
            <option value="">{"Selecciona un ámbito"}</option>
          </select>
          {"\n              "}
          <p id="ssid-source" role="status"></p>
          {"\n              "}
          <fieldset>
            <legend>{"AP que difundirán el SSID (selección explícita)"}</legend>
            <div id="ssid-aps"></div>
          </fieldset>
          {"\n              "}
          <label htmlFor="ssid-profile">
            {"Perfil de seguridad (sin contraseñas en el chat)"}
          </label>
          <select id="ssid-profile">
            <option value="">{"Selecciona un perfil"}</option>
          </select>
          {"\n              "}
          <label htmlFor="ssid-network">{"Red / VLAN existente"}</label>
          <select id="ssid-network">
            <option value="">{"Selecciona una red"}</option>
          </select>
          {"\n              "}
          <label htmlFor="ssid-name">{"Nuevo SSID"}</label>
          <input id="ssid-name" maxLength="32" placeholder="Clientes-Feria" />
          {"\n              "}
          <label htmlFor="ssid-purpose">{"Motivo"}</label>
          <input
            id="ssid-purpose"
            maxLength="500"
            placeholder="Acceso del cliente durante el evento"
          />
          {"\n              "}
          <button id="ssid-prepare" type="submit" disabled>
            {"Preparar creación individual"}
          </button>
          {"\n              "}
          <label htmlFor="ssid-csv">
            {"Cargar CSV de reservas o Excel de feria"}
          </label>
          <input id="ssid-csv" name="ssid-file" type="file" accept=".csv,.xlsx" aria-describedby="ssid-file-help" />
          <p id="ssid-file-help">
            Del Excel se leen Evento, WiFi / SSID y N° Vlan de la hoja Histórico.
            Se usan los AP y el perfil seleccionados arriba para todas las filas.
          </p>
          {"\n              "}
          <button id="ssid-upload" type="button" disabled>
            {"Revisar propuestas del archivo"}
          </button>
          {"\n            "}
        </form>
        {"\n            "}
        <section id="fair-closure" hidden aria-labelledby="fair-closure-heading">
          <h3 id="fair-closure-heading">Cierre de feria</h3>
          <button id="fair-closure-preview" type="button" disabled>
            Revisar cierre del ámbito
          </button>
          <div id="fair-closure-summary"></div>
          <button id="fair-closure-confirm" type="button" hidden>
            Confirmar cierre del ámbito
          </button>
        </section>
        <p id="ssid-status" role="status"></p>
        {"\n            "}
        <div id="ssid-plan-list" className="reservation-list"></div>
        {"\n          "}
      </section>
      {"\n"}
      <section
        className="panel support-panel"
        id="changes-panel"
        hidden
        aria-labelledby="changes-heading"
      >
        {"\n            "}
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">{"CAMBIOS CONTROLADOS · PROPUESTAS"}</p>
            <h2 id="changes-heading">
              {"Cambio de VLAN y reinicio de equipos"}
            </h2>
          </div>
          <button id="changes-refresh" type="button">
            {"Actualizar estado"}
          </button>
        </div>
        {"\n            "}
        <p className="chat-intro">
          {
            "Prepara la propuesta, revisa su impacto y confírmala. Sin confirmación no se ejecuta nada. Un ejecutor separado aplica el cambio, lo verifica y, si falla, restaura el estado anterior o abre un ticket. Un reinicio no se puede deshacer."
          }
        </p>
        {"\n            "}
        <div className="support-form">
          <label htmlFor="changes-scope">{"Ámbito autorizado"}</label>
          <select id="changes-scope">
            <option value="">{"Selecciona un ámbito"}</option>
          </select>
          <p id="changes-source" role="status"></p>
        </div>
        {"\n            "}
        <form id="vlan-change-form" className="support-form">
          {"\n              "}
          <h3>{"Cambiar la VLAN de un SSID existente"}</h3>
          {"\n              "}
          <label htmlFor="vlan-change-ssid">{"SSID"}</label>
          <select id="vlan-change-ssid">
            <option value="">{"Selecciona un SSID"}</option>
          </select>
          {"\n              "}
          <label htmlFor="vlan-change-network">
            {"Red / VLAN destino (existente)"}
          </label>
          <select id="vlan-change-network">
            <option value="">{"Selecciona la red destino"}</option>
          </select>
          {"\n              "}
          <label htmlFor="vlan-change-purpose">{"Motivo"}</label>
          <input
            id="vlan-change-purpose"
            maxLength="500"
            placeholder="Mover a los expositores a su VLAN"
          />
          {"\n              "}
          <button id="vlan-change-prepare" type="submit" disabled>
            {"Preparar cambio de VLAN"}
          </button>
          {"\n            "}
        </form>
        {"\n            "}
        <section aria-labelledby="vlan-batch-heading" className="support-form">
          <h3 id="vlan-batch-heading">Cambios de VLAN en lote</h3>
          <button id="vlan-batch-add" type="button" disabled>Agregar selección al lote</button>
          <ol id="vlan-batch-draft"></ol>
          <button id="vlan-batch-preview" type="button" disabled>Revisar lote</button>
          <label htmlFor="vlan-batch-history">Lotes anteriores del ámbito</label>
          <select id="vlan-batch-history" disabled>
            <option value="">Selecciona un lote</option>
          </select>
          <div id="vlan-batch-detail"></div>
        </section>
        <form id="restart-form" className="support-form">
          {"\n              "}
          <h3>{"Reiniciar un equipo"}</h3>
          {"\n              "}
          <label htmlFor="restart-device">{"Punto de acceso del ámbito"}</label>
          <select id="restart-device">
            <option value="">{"Selecciona un AP"}</option>
          </select>
          {"\n              "}
          <div id="restart-device-id-field" hidden>
            <label htmlFor="restart-device-id">
              {
                "O identificador de otro equipo del sitio (solo administración; gateway y firewall interrumpen toda la red)"
              }
            </label>
            <input id="restart-device-id" maxLength="160" autoComplete="off" />
          </div>
          {"\n              "}
          <label htmlFor="restart-purpose">{"Motivo"}</label>
          <input
            id="restart-purpose"
            maxLength="500"
            placeholder="El AP dejó de responder"
          />
          {"\n              "}
          <button id="restart-prepare" type="submit" disabled>
            {"Preparar reinicio"}
          </button>
          {"\n            "}
        </form>
        {"\n            "}
        <p id="changes-status" role="status" aria-live="polite"></p>
        {"\n            "}
        <div id="changes-plan-list" className="reservation-list"></div>
        {"\n          "}
      </section>
      {"\n"}
      <section
        id="csv-panel"
        className="csv-panel"
        hidden
        aria-labelledby="csv-heading"
      >
        {"\n              "}
        <h3 id="csv-heading">{"Carga de SSIDs y reservas por CSV"}</h3>
        {"\n              "}
        <p>
          {
            "Valida el archivo y confirma las filas que deseas reservar. Esta acción guarda reservas locales; no crea SSIDs ni modifica la red."
          }
        </p>
        {"\n              "}
        <a href="./examples/ssid-reservas.csv" download>
          {"Descargar plantilla CSV"}
        </a>
        {"\n              "}
        <p id="csv-limits">
          {"UTF-8, separado por coma o punto y coma. Sin contraseñas."}
        </p>
        {"\n              "}
        <form id="csv-form" className="chat-controls">
          {"\n                "}
          <label htmlFor="csv-file">{"Archivo CSV"}</label>
          <input id="csv-file" type="file" accept=".csv,text/csv" required />
          {"\n                "}
          <button id="csv-upload" type="submit">
            {"Validar CSV"}
          </button>
          {"\n              "}
        </form>
        {"\n              "}
        <div className="chat-controls">
          <label htmlFor="csv-history">{"Cargas anteriores"}</label>
          <select id="csv-history">
            <option value="">{"Selecciona una carga"}</option>
          </select>
        </div>
        {"\n              "}
        <p id="csv-status" role="status" aria-live="polite"></p>
        {"\n              "}
        <div id="csv-preview" hidden>
          {"\n                "}
          <p id="csv-summary"></p>
          {"\n                "}
          <label className="toggle-option">
            <input type="checkbox" id="csv-select-all" />
            {" Seleccionar todas las filas válidas"}
          </label>
          {"\n                "}
          <div className="table-wrap">
            <table className="data-table">
              <caption className="visually-hidden">
                {"Validación del CSV por fila"}
              </caption>
              <thead>
                <tr>
                  <th>{"Seleccionar"}</th>
                  <th>{"Fila"}</th>
                  <th>{"Interfaz"}</th>
                  <th>{"VLAN"}</th>
                  <th>{"SSID"}</th>
                  <th>{"Evento"}</th>
                  <th>{"Propósito"}</th>
                  <th>{"Validación"}</th>
                </tr>
              </thead>
              <tbody id="csv-rows"></tbody>
            </table>
          </div>
          {"\n                "}
          <p id="csv-selection"></p>
          {"\n                "}
          <div className="chat-controls">
            <button id="csv-confirm" type="button">
              {"Confirmar reservas seleccionadas"}
            </button>
            <button id="csv-cancel" type="button">
              {"Cancelar carga"}
            </button>
          </div>
          {"\n                "}
          <div id="csv-results" aria-live="polite"></div>
          {"\n              "}
        </div>
        {"\n            "}
      </section>
      {"\n"}
      <article
        className="panel support-panel"
        id="reservations-summary"
        hidden={!canReserve}
      >
        <div className="panel-heading">
          <h2>{"Reservas VLAN activas"}</h2>
        </div>
        <section
          id="vlan-reservations"
          className="reservation-list"
          hidden
          aria-label="Reservas VLAN activas"
        ></section>
      </article>
      {"\n          "}
    </section>
  );
});

export const AuditMarkup = memo(function AuditMarkup() {
  return (
    <section
      className="panel support-panel"
      id="view-audit"
      aria-labelledby="audit-heading"
    >
      {"\n  "}
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"TRAZABILIDAD"}</p>
          <h2 id="audit-heading">{"Auditoría"}</h2>
        </div>
      </div>
      {"\n  "}
      <p>
        {
          "Eventos de identidad, soporte, tickets, reservas y planes. Los estados actuales son instantáneas: su fecha corresponde a la creación del plan, no a su ejecución. No se incluyen conversaciones, contactos ni credenciales."
        }
      </p>
      {"\n  "}
      <form id="audit-filters" className="audit-filters">
        {"\n    "}
        <label>
          {"Actor (ID)"}
          <input id="audit-actor" type="number" min="1" step="1" />
        </label>
        {"\n    "}
        <label>
          {"Origen"}
          <select id="audit-source">
            <option value="">{"Todos"}</option>
            <option value="auth">{"Identidad"}</option>
            <option value="support">{"Soporte"}</option>
            <option value="tickets">{"Tickets"}</option>
            <option value="reservations">{"Reservas"}</option>
            <option value="csv">{"CSV"}</option>
            <option value="ssid">{"Planes SSID"}</option>
          </select>
        </label>
        {"\n    "}
        <label>
          {"Acción exacta"}
          <input
            id="audit-action"
            maxLength="80"
            placeholder="Ej.: auth.login"
          />
        </label>
        {"\n    "}
        <label>
          {"Resultado o estado exacto"}
          <input id="audit-outcome" maxLength="32" placeholder="Ej.: success" />
        </label>
        {"\n    "}
        <label>
          {"Desde (hora local)"}
          <input id="audit-since" type="datetime-local" />
        </label>
        {"\n    "}
        <label>
          {"Hasta (hora local)"}
          <input id="audit-until" type="datetime-local" />
        </label>
        {"\n    "}
        <button type="submit">{"Aplicar filtros"}</button>
        <button id="audit-clear" type="button">
          {"Limpiar"}
        </button>
        {"\n  "}
      </form>
      {"\n  "}
      <div className="chat-controls">
        <button id="audit-export" type="button">
          {"Exportar CSV filtrado"}
        </button>
        <span>{"Máximo 5000 registros por exportación."}</span>
      </div>
      {"\n  "}
      <p id="audit-scope-note" className="chat-intro"></p>
      {"\n  "}
      <p id="audit-status" role="status" aria-live="polite"></p>
      {"\n  "}
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">
            {"Registro unificado de auditoría"}
          </caption>
          <thead>
            <tr>
              <th>{"Fecha local"}</th>
              <th>{"Origen"}</th>
              <th>{"Actor (ID)"}</th>
              <th>{"Acción"}</th>
              <th>{"Resultado / estado"}</th>
              <th>{"Recurso"}</th>
              <th>{"Tipo de registro"}</th>
            </tr>
          </thead>
          <tbody id="audit-body"></tbody>
        </table>
      </div>
      {"\n  "}
      <div className="chat-controls">
        <button id="audit-prev" type="button" disabled>
          {"Anterior"}
        </button>
        <span id="audit-page"></span>
        <button id="audit-next" type="button" disabled>
          {"Siguiente"}
        </button>
      </div>
      {"\n"}
    </section>
  );
});

export const UsersMarkup = memo(function UsersMarkup() {
  return (
    <section
      className="panel support-panel"
      id="view-users"
      aria-labelledby="users-heading"
    >
      {"\n  "}
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"ADMINISTRACIÓN"}</p>
          <h2 id="users-heading">{"Usuarios y roles"}</h2>
        </div>
        <button id="users-refresh" type="button">
          {"Actualizar"}
        </button>
      </div>
      {"\n  "}
      <p className="chat-intro">
        {
          "Un usuario desactivado no puede iniciar sesión y conserva su historial. No se eliminan cuentas. Siempre debe quedar al menos un administrador activo."
        }
      </p>
      {"\n  "}
      <form id="user-form" className="support-form" autoComplete="off">
        {"\n    "}
        <h3 id="user-form-title">{"Nuevo usuario"}</h3>
        {"\n    "}
        <label htmlFor="user-email">{"Correo"}</label>
        <input id="user-email" type="email" maxLength="254" required />
        {"\n    "}
        <label htmlFor="user-full-name">{"Nombre"}</label>
        <input id="user-full-name" maxLength="160" />
        {"\n    "}
        <label htmlFor="user-password">{"Contraseña"}</label>
        <input
          id="user-password"
          type="password"
          maxLength="128"
          autoComplete="new-password"
        />
        {"\n    "}
        <p id="user-password-hint" className="chat-intro"></p>
        {"\n    "}
        <fieldset>
          <legend>{"Roles"}</legend>
          <div id="user-roles"></div>
        </fieldset>
        {"\n    "}
        <label>
          <input id="user-active" type="checkbox" defaultChecked />
          {" Cuenta activa"}
        </label>
        {"\n    "}
        <div className="chat-controls">
          <button id="user-save" type="submit">
            {"Guardar"}
          </button>
          <button id="user-cancel" type="button" hidden>
            {"Cancelar edición"}
          </button>
        </div>
        {"\n  "}
      </form>
      {"\n  "}
      <p id="users-status" role="status" aria-live="polite"></p>
      {"\n  "}
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">
            {"Usuarios del sistema"}
          </caption>
          <thead>
            <tr>
              <th>{"Correo"}</th>
              <th>{"Nombre"}</th>
              <th>{"Roles"}</th>
              <th>{"Estado"}</th>
              <th>{"Acciones"}</th>
            </tr>
          </thead>
          <tbody id="users-body"></tbody>
        </table>
      </div>
      {"\n"}
    </section>
  );
});

export const SystemMarkup = memo(function SystemMarkup() {
  return (
    <section
      className="panel support-panel"
      id="view-system"
      aria-labelledby="system-heading"
    >
      {"\n  "}
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"OPERACIÓN"}</p>
          <h2 id="system-heading">{"Agentes y servicios"}</h2>
        </div>
        <button id="system-refresh" type="button">
          {"Actualizar"}
        </button>
      </div>
      {"\n  "}
      <p id="system-status" role="status" aria-live="polite"></p>
      {"\n  "}
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">
            {"Estado de los agentes en segundo plano"}
          </caption>
          <thead>
            <tr>
              <th>{"Agente"}</th>
              <th>{"Estado"}</th>
              <th>{"Último ciclo correcto"}</th>
              <th>{"Errores"}</th>
            </tr>
          </thead>
          <tbody id="agents-body"></tbody>
        </table>
      </div>
      {"\n  "}
      <h3>{"Proveedor de IA"}</h3>
      {"\n  "}
      <p id="llm-health" role="status"></p>
      {"\n"}
    </section>
  );
});

export const AccountMarkup = memo(function AccountMarkup() {
  return (
    <section
      className="panel support-panel"
      id="view-account"
      aria-labelledby="account-heading"
    >
      {"\n  "}
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"CUENTA"}</p>
          <h2 id="account-heading">{"Mi cuenta"}</h2>
        </div>
      </div>
      {"\n  "}
      <p className="chat-intro">
        {"Sesión de "}
        <strong id="account-email"></strong>
        {
          ". Al cambiar la contraseña se cierran todas tus sesiones y deberás ingresar de nuevo."
        }
      </p>
      {"\n  "}
      <form id="account-form" className="support-form">
        {"\n    "}
        <label htmlFor="account-current">{"Contraseña actual"}</label>
        <input
          id="account-current"
          type="password"
          maxLength="128"
          autoComplete="current-password"
          required
        />
        {"\n    "}
        <label htmlFor="account-new">
          {"Nueva contraseña (mínimo 12 caracteres)"}
        </label>
        <input
          id="account-new"
          type="password"
          minLength="12"
          maxLength="128"
          autoComplete="new-password"
          required
        />
        {"\n    "}
        <label htmlFor="account-repeat">{"Repite la nueva contraseña"}</label>
        <input
          id="account-repeat"
          type="password"
          minLength="12"
          maxLength="128"
          autoComplete="new-password"
          required
        />
        {"\n    "}
        <button id="account-save" type="submit">
          {"Cambiar contraseña"}
        </button>
        {"\n  "}
      </form>
      {"\n  "}
      <p id="account-status" role="status" aria-live="polite"></p>
      {"\n"}
    </section>
  );
});

export const NotificationsMarkup = memo(function NotificationsMarkup() {
  return (
    <section
      className="panel support-panel"
      id="notifications-panel"
      hidden
      aria-labelledby="notifications-heading"
    >
      {"\n            "}
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">{"EQUIPO TÉCNICO"}</p>
          <h2 id="notifications-heading">{"Notificaciones"}</h2>
        </div>
      </div>
      {"\n            "}
      <div id="notifications-list" className="reservation-list"></div>
      {"\n          "}
    </section>
  );
});
