// Inventario persistido: resumen, dispositivos, alertas, SSID/VLAN y planos de cobertura.
// Solo lectura salvo la gestión de planos. El texto externo se inserta con textContent.
const PAGE_SIZE = 25;
const POLL_MS = 15000;
const STATE_LABELS = { online: 'En línea', degraded: 'Degradado', offline: 'Fuera de línea', maintenance: 'Mantención', unknown: 'Desconocido' };
const TYPE_LABELS = { ap: 'AP', switch: 'Switch', gateway: 'Gateway', firewall: 'Firewall', unknown: 'Desconocido' };
const STATE_PILL = { online: 'ok', degraded: 'warn', offline: 'block', maintenance: 'off', unknown: 'off' };
const SOURCE_LABELS = { opnsense: 'OPNsense', unifi: 'UniFi', mock: 'Simulador' };

export function createInventory({ document, window, Option, state, api, textNode }) {
  const $ = (selector) => document.querySelector(selector);
  const MONITORING = '/api/v1/monitoring';
  const local = { timer: null, offset: 0, canManage: false, plan: null, planUrl: null, selected: null, planToken: 0 };
  const dateTime = (value) => (value ? new Date(value).toLocaleString('es-CL') : '–');

  const cell = (value, className) => textNode('td', value, className);
  const pill = (label, tone) => { const td = document.createElement('td'); td.append(textNode('span', label, `pill ${tone}`)); return td; };
  function row(...cells) { const tr = document.createElement('tr'); tr.append(...cells); return tr; }
  function emptyRow(colspan, message) { const td = textNode('td', message, 'empty-state'); td.colSpan = colspan; return row(td); }

  function reset() {
    stop();
    local.offset = 0; local.canManage = false; local.plan = null; local.selected = null; local.planToken += 1;
    releaseImage();
    $('#plan-stage').hidden = true;
    $('#plan-markers').replaceChildren();
    $('#plan-unplaced').replaceChildren();
    $('#plan-status').textContent = '';
  }

  function stop() { if (local.timer) window.clearInterval(local.timer); local.timer = null; }

  function configureUser(user) {
    const allowed = Boolean(user.permissions?.includes('monitoring:read'));
    document.querySelectorAll('.nav-item[href="#devices"], .nav-item[href="#alerts"], .nav-item[href="#coverage"]').forEach((element) => { element.hidden = !allowed; });
    local.canManage = Boolean(user.permissions?.includes('networks:manage'));
    $('#plan-form').hidden = !local.canManage;
    $('#plan-delete').hidden = true;
    if (!allowed) { stop(); return Promise.resolve(); }
    local.timer = window.setInterval(refresh, POLL_MS);
    return Promise.all([refresh(), loadPlans()]);
  }

  async function refresh() {
    const session = state.session;
    const stateFilter = $('#devices-state').value;
    const typeFilter = $('#devices-type').value;
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(local.offset) });
    if (stateFilter) params.set('state', stateFilter);
    if (typeFilter) params.set('type', typeFilter);
    try {
      const [summary, devices, alerts, ssids, vlans] = await Promise.all([
        api.authedRequest(`${MONITORING}/summary`),
        api.authedRequest(`${MONITORING}/devices?${params}`),
        api.authedRequest(`${MONITORING}/alerts?limit=50`),
        api.authedRequest(`${MONITORING}/ssids?limit=200`),
        api.authedRequest(`${MONITORING}/vlans?limit=200`),
      ]);
      if (session !== state.session) return;
      if (stateFilter !== $('#devices-state').value || typeFilter !== $('#devices-type').value) return;
      renderSummary(summary);
      renderDevices(devices);
      renderAlerts(alerts);
      renderWireless(ssids, vlans);
      if (local.plan) await openPlan(local.plan.id);
    } catch (error) {
      if (session !== state.session || error.status === 401) return;
      const banner = $('#inventory-stale');
      banner.hidden = false;
      banner.textContent = 'Sin conexión con la API de Netbot. Reintentando automáticamente…';
    }
  }

  function renderSummary(data) {
    const availability = data.availability_percent == null ? 'Sin datos' : `${data.availability_percent.toFixed(2)} %`;
    const items = [
      ['APs en línea', `${data.access_points_online} / ${data.access_points_total}`],
      ['APs fuera de línea', data.access_points_offline],
      ['VLAN activas', data.vlans_active],
      ['SSID activos', data.ssids_active],
      [`Disponibilidad ${data.availability_window_hours} h`, availability],
      ['Alertas activas', data.active_alerts],
    ];
    $('#inventory-kpis').replaceChildren(...items.map(([label, value]) => {
      const box = document.createElement('div');
      box.append(textNode('small', label), textNode('strong', String(value)));
      return box;
    }));
    $('#inventory-updated').textContent = dateTime(data.last_update_at);
    $('#nav-alerts').textContent = String(data.active_alerts);
    const affected = data.sources.filter((source) => source.stale).map((source) => SOURCE_LABELS[source.source] || source.source);
    const banner = $('#inventory-stale');
    banner.hidden = !affected.length;
    banner.textContent = affected.length ? `Datos desactualizados de ${affected.join(', ')}: se muestran los últimos conocidos.` : '';
    $('#inventory-sources').replaceChildren(...data.sources.map((source) => {
      const detail = source.status === 'ok' ? 'Operativa' : source.status === 'degraded' ? 'Parcial' : 'No disponible';
      const version = source.version ? ` ${source.version}` : '';
      const error = source.last_error_message ? ` · ${source.last_error_message}` : '';
      return textNode('span', `${SOURCE_LABELS[source.source] || source.source}${version}: ${detail}${error}`, 'source-chip');
    }));
  }

  function renderDevices(page) {
    const body = $('#devices-body');
    body.replaceChildren(...(page.items.length ? page.items.map((device) => row(
      cell(device.name), cell(TYPE_LABELS[device.device_type] || device.device_type),
      cell(device.ip_address || '–', 'mono'),
      pill(device.stale ? `${STATE_LABELS[device.state]} (desactualizado)` : STATE_LABELS[device.state], STATE_PILL[device.state]),
      cell(dateTime(device.last_online_at), 'mono'),
    )) : [emptyRow(5, 'Sin dispositivos para este filtro.')]));
    const last = Math.min(page.offset + page.items.length, page.total);
    $('#devices-page').textContent = page.total ? `${page.offset + 1}–${last} de ${page.total}` : '0 de 0';
    $('#devices-prev').disabled = page.offset === 0;
    $('#devices-next').disabled = last >= page.total;
  }

  function renderAlerts(page) {
    $('#alerts-body').replaceChildren(...(page.items.length ? page.items.map((alert) => row(
      pill(alert.severity === 'critical' ? 'Crítica' : 'Advertencia', alert.severity === 'critical' ? 'block' : 'warn'),
      cell(alert.device_name || SOURCE_LABELS[alert.source] || alert.source), cell(alert.message),
      cell(dateTime(alert.detected_at), 'mono'),
    )) : [emptyRow(4, 'Sin alertas activas.')]));
  }

  function renderWireless(ssids, vlans) {
    $('#ssids-body').replaceChildren(...(ssids.items.length ? ssids.items.map((ssid) => row(
      cell(ssid.name), pill(ssid.enabled ? 'Activo' : 'Inactivo', ssid.enabled ? 'ok' : 'off'),
      cell(ssid.security || '–', 'mono'), cell(ssid.vlan_tag ?? 'Sin resolver', 'mono'),
    )) : [emptyRow(4, 'Sin SSID registrados.')]));
    $('#vlans-body').replaceChildren(...(vlans.items.length ? vlans.items.map((vlan) => row(
      cell(vlan.tag, 'mono'), cell(vlan.name || '–'), cell(SOURCE_LABELS[vlan.source] || vlan.source),
    )) : [emptyRow(3, 'Sin VLAN registradas.')]));
  }

  // ------------------------------------------------------------------ //
  // Planos
  // ------------------------------------------------------------------ //

  function releaseImage() {
    if (local.planUrl) window.URL.revokeObjectURL(local.planUrl);
    local.planUrl = null;
    $('#plan-image').removeAttribute?.('src');
  }

  async function loadPlans(selectId) {
    const session = state.session;
    try {
      const plans = await api.authedRequest(`${MONITORING}/plans`);
      if (session !== state.session) return;
      const select = $('#plan-select');
      select.replaceChildren(new Option('Selecciona un plano', ''), ...plans.map((plan) => new Option(plan.name, String(plan.id))));
      if (selectId) { select.value = String(selectId); await openPlan(selectId, true); }
    } catch (error) {
      if (session === state.session) $('#plan-status').textContent = error.message;
    }
  }

  async function openPlan(id, reloadImage = false) {
    const session = state.session;
    const token = ++local.planToken;
    try {
      const plan = await api.authedRequest(`${MONITORING}/plans/${id}`);
      const blob = reloadImage ? await api.authedRequest(`${MONITORING}/plans/${id}/image`, { raw: true }) : null;
      if (session !== state.session || token !== local.planToken) return;
      local.plan = plan;
      if (blob) {
        releaseImage();
        local.planUrl = window.URL.createObjectURL(blob);
        $('#plan-image').src = local.planUrl;
      }
      $('#plan-stage').hidden = false;
      $('#plan-delete').hidden = !local.canManage;
      renderPlan();
    } catch (error) {
      if (session === state.session && token === local.planToken) $('#plan-status').textContent = error.message;
    }
  }

  function renderPlan() {
    const { placed, unplaced } = local.plan;
    $('#plan-markers').replaceChildren(...placed.map((ap) => {
      const marker = textNode('button', '', `plan-marker ${ap.state}${local.selected === ap.device_id ? ' selected' : ''}`);
      marker.type = 'button';
      marker.title = `${ap.name} · ${STATE_LABELS[ap.state]}`;
      marker.setAttribute('aria-label', marker.title);
      marker.style.left = `${ap.x * 100}%`;
      marker.style.top = `${ap.y * 100}%`;
      marker.addEventListener('click', (event) => { event.stopPropagation(); selectDevice(ap.device_id); });
      return marker;
    }));
    $('#plan-unplaced').replaceChildren(...(unplaced.length ? unplaced.map((ap) => {
      const button = textNode('button', `${ap.name} · sin ubicar`, local.selected === ap.device_id ? 'selected' : '');
      button.type = 'button';
      button.addEventListener('click', () => selectDevice(ap.device_id));
      return button;
    }) : [textNode('p', 'Todos los AP están ubicados.', 'empty-state')]));
  }

  async function selectDevice(id) {
    const session = state.session;
    local.selected = id;
    renderPlan();
    try {
      const device = await api.authedRequest(`${MONITORING}/devices/${id}`);
      if (session !== state.session || local.selected !== id) return;
      const lines = [textNode('p', device.name), textNode('p', `${TYPE_LABELS[device.device_type]} · ${STATE_LABELS[device.state]}`),
        textNode('p', `IP: ${device.ip_address || '–'}`), textNode('p', `Modelo: ${device.model || '–'}`),
        textNode('p', `Visto: ${dateTime(device.last_online_at)}`),
        ...(device.alerts.length ? device.alerts.map((alert) => textNode('p', alert.message)) : [textNode('p', 'Sin alertas activas.')])];
      if (local.canManage) {
        lines.push(textNode('p', 'Pulsa el plano para ubicar este AP.'));
        if (local.plan?.placed.some((ap) => ap.device_id === id)) {
          const remove = textNode('button', 'Quitar del plano');
          remove.type = 'button';
          remove.addEventListener('click', () => removePlacement(id));
          lines.push(remove);
        }
      }
      $('#plan-detail').replaceChildren(...lines);
    } catch (error) {
      if (session === state.session) $('#plan-status').textContent = error.message;
    }
  }

  async function place(x, y) {
    const id = local.selected;
    if (!local.canManage || !id || !local.plan) return;
    const clamp = (value) => Math.min(Math.max(value, 0), 1);
    try {
      await api.authedRequest(`${MONITORING}/plans/${local.plan.id}/placements/${id}`, { method: 'PUT', body: JSON.stringify({ x: clamp(x), y: clamp(y) }) });
      await openPlan(local.plan.id);
    } catch (error) { $('#plan-status').textContent = error.message; }
  }

  async function removePlacement(id) {
    try {
      await api.authedRequest(`${MONITORING}/plans/${local.plan.id}/placements/${id}`, { method: 'DELETE' });
      await openPlan(local.plan.id);
      await selectDevice(id);
    } catch (error) { $('#plan-status').textContent = error.message; }
  }

  $('#plan-stage').addEventListener('click', (event) => {
    const box = $('#plan-stage').getBoundingClientRect();
    if (box.width && box.height) place((event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
  });

  $('#plan-select').addEventListener('change', () => {
    const id = $('#plan-select').value;
    local.selected = null;
    if (id) { openPlan(Number(id), true); return; }
    local.plan = null; local.planToken += 1;
    releaseImage();
    $('#plan-stage').hidden = true; $('#plan-delete').hidden = true;
    $('#plan-unplaced').replaceChildren();
  });

  $('#plan-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = $('#plan-file').files?.[0];
    if (!file || !['image/png', 'image/jpeg'].includes(file.type)) { $('#plan-status').textContent = 'Selecciona una imagen PNG o JPEG.'; return; }
    const session = state.session;
    try {
      const body = new Uint8Array(await file.arrayBuffer());
      const name = encodeURIComponent($('#plan-name').value.trim());
      const plan = await api.authedRequest(`${MONITORING}/plans?name=${name}`, { method: 'POST', headers: { 'Content-Type': file.type }, body });
      if (session !== state.session) return;
      $('#plan-status').textContent = 'Plano cargado.';
      $('#plan-form').reset?.();
      await loadPlans(plan.id);
    } catch (error) {
      if (session === state.session) $('#plan-status').textContent = error.message;
    }
  });

  $('#plan-delete').addEventListener('click', async () => {
    if (!local.plan) return;
    try {
      await api.authedRequest(`${MONITORING}/plans/${local.plan.id}`, { method: 'DELETE' });
      local.plan = null; local.selected = null; local.planToken += 1;
      releaseImage();
      $('#plan-stage').hidden = true; $('#plan-delete').hidden = true;
      $('#plan-unplaced').replaceChildren();
      await loadPlans();
    } catch (error) { $('#plan-status').textContent = error.message; }
  });

  ['#devices-state', '#devices-type'].forEach((selector) => $(selector).addEventListener('change', () => { local.offset = 0; refresh(); }));
  $('#devices-prev').addEventListener('click', () => { local.offset = Math.max(0, local.offset - PAGE_SIZE); refresh(); });
  $('#devices-next').addEventListener('click', () => { local.offset += PAGE_SIZE; refresh(); });

  return { configureUser, reset, refresh };
}
