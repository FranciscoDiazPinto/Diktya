
export function createMonitoring({ document, window, sessionState, api, format, showToast, signOut }) {
  const $ = (selector) => document.querySelector(selector);
  const { monitoringRequest } = api;
  const { formatBytes, formatRate, formatCount, formatDuration, relativeTime, escapeHtml, clockTime, endpoint } = format;
  const refreshButton = $('#refresh-button');
  const syncLabel = $('#last-sync');
  const POLL_MS = 5000;
  const metrics = { timer: null, lastSync: null, chartWindow: 300, fwAction: '', data: {}, rates: {},
                    history: { interfaces: [], traffic: [], clients: [], blocked: [] } };
  function reset() {
    stopPolling();
    metrics.data = {}; metrics.lastSync = null; metrics.rates = {};
    metrics.history = { interfaces: [], traffic: [], clients: [], blocked: [] };
  }
  function configureUser(user) {
    const globalMonitoring = user.permissions?.includes('monitoring:read');
    document.querySelectorAll('.stats-grid, .dashboard-grid, .page-heading .period-picker, .last-sync, #refresh-button, #issues-banner, .nav-item[href="#interfaces"], .nav-item[href="#clients"], .nav-item[href="#firewall"]').forEach((element) => { element.hidden = !globalMonitoring; });
    renderGreeting();
    if (globalMonitoring) startPolling();
    else {
      stopPolling();
      $('#source-name').textContent = 'Acceso personal';
      $('#source-detail').textContent = 'Solo redes autorizadas';
      $('#footer-status').textContent = 'Consulta tus redes desde el asistente';
    }
  }
  function startPolling() {
    stopPolling();
    poll();
    metrics.timer = window.setInterval(poll, POLL_MS);
  }

  function stopPolling() {
    if (metrics.timer) window.clearInterval(metrics.timer);
    metrics.timer = null;
  }

  async function poll() {
    const session = sessionState.session;
    try {
      const [system, interfaces, traffic, clients, stats, events] = await Promise.all([
        monitoringRequest('/system'),
        monitoringRequest('/interfaces'),
        monitoringRequest(`/interfaces/traffic?window=${metrics.chartWindow}`),
        monitoringRequest('/clients'),
        monitoringRequest('/firewall/stats'),
        monitoringRequest('/firewall/events?limit=200'),
      ]);
      if (session !== sessionState.session) return;
      metrics.data = { system, interfaces, traffic, clients, stats, events };
      metrics.lastSync = new Date();
      recordSamples();
      render();
    } catch (error) {
      if (session !== sessionState.session) return;
      if (error.status === 401) { signOut('Tu sesion expiro, ingresa nuevamente'); return; }
      if (error.status === 403) { renderFatal('Tu usuario no tiene permiso para ver el monitoreo (monitoring:read).'); return; }
      renderFatal('No se pudo conectar con la API de Netbot.');
    }
  }

  function pushHistory(key, value) {
    if (value == null) return;
    const list = metrics.history[key];
    list.push(value);
    if (list.length > 8) list.shift();
  }

  // La API calcula la velocidad (bytes/s) a partir de muestras periodicas de los contadores.
  function recordSamples() {
    const { interfaces, traffic, clients, stats } = metrics.data;
    metrics.rates = {};
    for (const series of traffic.data || []) {
      const last = series.points[series.points.length - 1];
      if (last) metrics.rates[series.interface_id] = { in: last.bytes_in_per_second, out: last.bytes_out_per_second };
    }
    const wanRate = metrics.rates.wan;
    if (wanRate) pushHistory('traffic', wanRate.in + wanRate.out);
    if (interfaces.data) pushHistory('interfaces', interfaces.data.filter((i) => i.status === 'up').length);
    if (clients.data) pushHistory('clients', clients.data.filter((c) => c.active).length);
    if (stats.data) pushHistory('blocked', stats.data.packets_blocked);
  }

  // --------------------------------------------------------------------------- //
  // Render
  // --------------------------------------------------------------------------- //

  function render() {
    renderStatus();
    renderStats();
    renderChart();
    renderSystem();
    renderActivity();
    renderInterfaces();
    renderClients();
    renderFirewall();
    syncLabel.textContent = relativeTime(metrics.lastSync);
  }

  function renderGreeting() {
    const now = new Date();
    const hour = now.getHours();
    const salute = hour < 12 ? 'Buenos dias' : hour < 20 ? 'Buenas tardes' : 'Buenas noches';
    const name = (sessionState.user?.full_name || sessionState.user?.email.split('@')[0] || '').split(/[\s.]/)[0];
    const capitalized = name ? name[0].toUpperCase() + name.slice(1) : '';
    $('#greeting').innerHTML = `${salute}${capitalized ? `, ${escapeHtml(capitalized)}` : ''} <span>↗</span>`;
    $('#today-label').textContent = now.toLocaleDateString('es-CL', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
  }

  const RESOURCE_LABELS = { system: 'Sistema', interfaces: 'Interfaces', traffic: 'Historial de trafico', clients: 'Clientes DHCP', stats: 'Estadisticas del firewall', events: 'Registro del firewall' };

  function renderStatus() {
    const entries = Object.entries(metrics.data);
    const statuses = entries.map(([, r]) => r.status);
    const worst = statuses.includes('unavailable') ? 'unavailable' : statuses.includes('degraded') ? 'degraded' : 'ok';
    const source = metrics.data.system?.source || entries[0]?.[1].source;
    const sourceName = source === 'mock' ? 'Simulador' : source === 'opnsense' ? 'OPNsense' : 'Sin fuente';

    $('#source-name').textContent = sourceName;
    $('#source-detail').textContent = worst === 'ok' ? `Operativo · ${clockTime(metrics.lastSync)}` : worst === 'degraded' ? 'Datos parciales' : 'Fuente con fallas';
    $('#source-dot').className = `status-dot ${worst}`;
    $('#live-badge').className = `live-badge ${worst}`;
    $('#live-badge').innerHTML = `<i></i> ${worst === 'ok' ? 'En vivo' : worst === 'degraded' ? 'Parcial' : 'Sin datos'}`;
    $('#footer-status').innerHTML = `${worst === 'ok' ? 'Todos los sistemas operativos' : worst === 'degraded' ? 'Algunos componentes con fallas' : 'Fuente de monitoreo no disponible'} <i class="status-dot ${worst}"></i>${source === 'mock' ? ' · datos simulados' : ''}`;

    const problems = entries.flatMap(([key, r]) => r.issues.filter((issue) => !issue.optional).map((issue) => ({ key, ...issue })));
    const banner = $('#issues-banner');
    banner.classList.toggle('is-hidden', !problems.length);
    banner.className = `issues-banner ${problems.length ? '' : 'is-hidden'} ${statuses.includes('unavailable') ? 'critical' : ''}`;
    banner.innerHTML = problems.length ? `<strong>Problemas al recolectar datos</strong><ul>${problems.map((p) => `<li><b>${escapeHtml(RESOURCE_LABELS[p.key] || p.key)}</b> · ${escapeHtml(p.component)}: ${escapeHtml(p.message)}</li>`).join('')}</ul>` : '';
  }

  function renderFatal(message) {
    const banner = $('#issues-banner');
    banner.className = 'issues-banner critical';
    banner.innerHTML = `<strong>${escapeHtml(message)}</strong>`;
    $('#source-dot').className = 'status-dot unavailable';
    $('#source-name').textContent = 'Sin conexion';
    $('#source-detail').textContent = 'Reintentando…';
  }

  function renderSparkline(id, values) {
    const element = $(`#${id}`);
    if (!values.length) { element.innerHTML = ''; return; }
    const max = Math.max(...values);
    const min = Math.min(...values);
    element.innerHTML = values.map((v) => `<i style="height:${max === min ? 18 : 6 + ((v - min) / (max - min)) * 23}px"></i>`).join('');
  }

  function setMeta(id, html, tone = '') {
    const element = $(`#${id}`);
    element.className = `stat-meta ${tone}`;
    element.innerHTML = html;
  }

  function renderStats() {
    const { interfaces, clients, stats, events } = metrics.data;

    if (interfaces.data) {
      const up = interfaces.data.filter((i) => i.status === 'up');
      const down = interfaces.data.filter((i) => i.status !== 'up');
      $('#stat-interfaces').innerHTML = `${up.length}<span> / ${interfaces.data.length}</span>`;
      setMeta('stat-interfaces-meta', down.length ? `<span>${down.length} caida${down.length > 1 ? 's' : ''}</span> ${escapeHtml(down.map((i) => i.description || i.name).join(', '))}` : '<span>Todas operativas</span>', down.length ? 'negative' : 'positive');
      $('#nav-interfaces').textContent = interfaces.data.length;
    } else {
      $('#stat-interfaces').textContent = '–';
      setMeta('stat-interfaces-meta', 'Sin datos', 'negative');
    }

    const wan = interfaces.data?.find((i) => i.interface_id === 'wan');
    const wanRate = wan && metrics.rates[wan.interface_id];
    if (wanRate) {
      const [value, unit] = formatRate(wanRate.in + wanRate.out).split(' ');
      $('#stat-traffic').innerHTML = `${value}<span> ${unit}</span>`;
      setMeta('stat-traffic-meta', `<span>↓ ${formatRate(wanRate.in)}</span> ↑ ${formatRate(wanRate.out)}`, 'positive');
    } else if (wan?.traffic) {
      const [value, unit] = formatBytes(wan.traffic.bytes_in + wan.traffic.bytes_out).split(' ');
      $('#stat-traffic').innerHTML = `${value}<span> ${unit}</span>`;
      setMeta('stat-traffic-meta', 'Acumulado · calculando velocidad…', 'neutral');
    } else {
      $('#stat-traffic').textContent = '–';
      setMeta('stat-traffic-meta', 'Sin datos de la WAN', 'negative');
    }

    if (clients.data) {
      const active = clients.data.filter((c) => c.active).length;
      const expired = clients.data.length - active;
      $('#stat-clients').textContent = active;
      setMeta('stat-clients-meta', `<span>${clients.data.length}</span> concesiones · ${expired} vencidas`, 'neutral');
      $('#nav-clients').textContent = active;
    } else {
      $('#stat-clients').textContent = '–';
      setMeta('stat-clients-meta', 'Sin datos DHCP', 'negative');
    }

    const blockedEvents = events.data?.filter((e) => e.action === 'block').length;
    $('#nav-blocked').textContent = blockedEvents ?? '–';
    if (stats.data?.packets_blocked != null) {
      const [value, unit = ''] = formatCount(stats.data.packets_blocked).split(' ');
      $('#stat-blocked').innerHTML = `${value}<span> ${unit}</span>`;
      const total = (stats.data.packets_blocked || 0) + (stats.data.packets_passed || 0);
      const share = total ? ((stats.data.packets_blocked / total) * 100).toFixed(2) : '0';
      setMeta('stat-blocked-meta', `<span>${share}%</span> del trafico · ${blockedEvents ?? 0} en el registro`, 'negative');
    } else {
      $('#stat-blocked').textContent = blockedEvents ?? '–';
      setMeta('stat-blocked-meta', blockedEvents != null ? 'Del registro · estadisticas no disponibles' : 'Sin datos', 'negative');
    }

    renderSparkline('spark-interfaces', metrics.history.interfaces);
    renderSparkline('spark-traffic', metrics.history.traffic);
    renderSparkline('spark-clients', metrics.history.clients);
    renderSparkline('spark-blocked', metrics.history.blocked);
  }

  function renderChart() {
    const series = metrics.data.traffic?.data?.find((h) => h.interface_id === 'wan');
    const samples = (series?.points || []).map((p) => ({ t: new Date(p.timestamp).getTime(), in: p.bytes_in_per_second, out: p.bytes_out_per_second }));
    const empty = $('#chart-empty');
    if (samples.length < 2) {
      empty.style.display = '';
      ['#chart-area', '#chart-in', '#chart-out'].forEach((id) => $(id).setAttribute('d', ''));
      $('#chart-x').innerHTML = '';
      return;
    }
    empty.style.display = 'none';
    const max = Math.max(...samples.flatMap((s) => [s.in, s.out])) * 1.15 || 1;
    const start = samples[0].t;
    const span = samples[samples.length - 1].t - start || 1;
    const point = (s, key) => `${((s.t - start) / span) * 760},${190 - (s[key] / max) * 180}`;
    const line = (key) => `M${samples.map((s) => point(s, key)).join(' L')}`;
    $('#chart-in').setAttribute('d', line('in'));
    $('#chart-out').setAttribute('d', line('out'));
    $('#chart-area').setAttribute('d', `${line('in')} L760,190 L0,190 Z`);
    $('#chart-y').innerHTML = [1, 0.75, 0.5, 0.25, 0].map((f) => `<span>${f ? formatRate(max * f) : '0'}</span>`).join('');
    const ticks = 5;
    $('#chart-x').innerHTML = Array.from({ length: ticks }, (_, i) => {
      const t = start + (span * i) / (ticks - 1);
      const format = span < 600000 ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { hour: '2-digit', minute: '2-digit' };
      return `<span>${i === ticks - 1 ? 'Ahora' : new Date(t).toLocaleTimeString('es-CL', format)}</span>`;
    }).join('');
  }

  function setBar(id, percent) {
    $(`#${id}`).style.width = `${Math.min(Math.max(percent || 0, 0), 100)}%`;
  }

  function renderSystem() {
    const system = metrics.data.system.data;
    if (!system) {
      ['#sys-cpu', '#sys-mem', '#sys-temp', '#sys-uptime'].forEach((id) => { $(id).textContent = '–'; });
      $('#sys-host').textContent = 'Sin datos del sistema';
      return;
    }
    $('#sys-host').textContent = system.hostname || 'Equipo sin nombre';
    $('#sys-cpu').innerHTML = system.cpu_percent != null ? `${Math.round(system.cpu_percent)}<span>%</span>` : '–';
    setBar('sys-cpu-bar', system.cpu_percent);
    if (system.memory) {
      $('#sys-mem').innerHTML = `${Math.round(system.memory.used_percent)}<span>%</span>`;
      $('#sys-mem-detail').textContent = `${formatBytes(system.memory.used_bytes)} de ${formatBytes(system.memory.total_bytes)}`;
      setBar('sys-mem-bar', system.memory.used_percent);
    }
    if (system.temperature?.available && system.temperature.value_celsius != null) {
      $('#sys-temp').innerHTML = `${system.temperature.value_celsius.toFixed(1)}<span>°C</span>`;
      $('#sys-temp-detail').textContent = system.temperature.value_celsius > 70 ? 'Temperatura elevada' : 'Dentro de lo normal';
      setBar('sys-temp-bar', system.temperature.value_celsius);
    } else {
      $('#sys-temp').textContent = 'N/D';
      $('#sys-temp-detail').textContent = 'Sensor no disponible';
      setBar('sys-temp-bar', 0);
    }
    $('#sys-uptime').textContent = formatDuration(system.uptime_seconds);
    $('#sys-version').textContent = system.version || 'Version desconocida';
  }

  function eventRow(event) {
    const blocked = event.action === 'block';
    return `<div class="activity-row"><span class="activity-icon ${blocked ? 'blocked' : 'connected'}">${blocked ? '×' : '↗'}</span><div><strong>${blocked ? 'Conexion bloqueada' : 'Conexion permitida'}</strong><small>${escapeHtml(endpoint(event.source_ip, event.source_port))} → ${escapeHtml(endpoint(event.destination_ip, event.destination_port))} · ${escapeHtml((event.protocol || '').toUpperCase())} · ${escapeHtml(event.interface || '–')}</small></div><time>${relativeTime(event.timestamp)}</time></div>`;
  }

  function renderActivity() {
    const events = metrics.data.events.data;
    $('#activity-list').innerHTML = events?.length ? events.slice(0, 6).map(eventRow).join('') : `<p class="empty-state">${events ? 'Sin eventos recientes.' : 'Registro del firewall no disponible.'}</p>`;
  }

  function renderInterfaces() {
    const interfaces = metrics.data.interfaces.data;
    if (!interfaces) { $('#interfaces-list').innerHTML = '<p class="empty-state">Interfaces no disponibles.</p>'; return; }
    $('#interfaces-list').innerHTML = interfaces.map((i) => {
      const rate = metrics.rates[i.interface_id];
      const statusClass = i.status === 'up' ? '' : i.status === 'down' ? 'down' : 'warning';
      const traffic = i.status !== 'up' ? 'Sin enlace' : rate ? `↓ ${formatRate(rate.in)} ↑ ${formatRate(rate.out)}` : `Σ ${formatBytes((i.traffic?.bytes_in || 0) + (i.traffic?.bytes_out || 0))}`;
      const errors = (i.traffic?.errors_in || 0) + (i.traffic?.errors_out || 0);
      return `<div class="interface-row"><span class="interface-status ${statusClass}"></span><div><strong>${escapeHtml(i.description || i.interface_id.toUpperCase())}</strong><small>${escapeHtml(i.name)} · ${escapeHtml(i.ip_addresses.join(', ') || 'sin IP')}</small></div><span class="interface-speed">${errors ? `${errors} errores` : escapeHtml(i.interface_id)}</span><span class="interface-traffic ${statusClass}">${traffic}</span></div>`;
    }).join('');
  }

  function renderClients() {
    const clients = metrics.data.clients?.data;
    const body = $('#clients-body');
    if (!clients) { body.innerHTML = '<tr><td colspan="6" class="empty-state">Clientes DHCP no disponibles.</td></tr>'; return; }
    const query = $('#clients-search').value.trim().toLowerCase();
    const activeOnly = $('#clients-active-only').checked;
    const rows = clients
      .filter((c) => !activeOnly || c.active)
      .filter((c) => !query || [c.hostname, c.ip_address, c.mac_address, c.interface].some((v) => String(v || '').toLowerCase().includes(query)));
    body.innerHTML = rows.length ? rows.map((c) => `<tr><td>${escapeHtml(c.hostname || 'Sin nombre')}</td><td class="mono">${escapeHtml(c.ip_address)}</td><td class="mono">${escapeHtml(c.mac_address)}</td><td class="mono">${escapeHtml(c.interface || '–')}</td><td class="mono">${c.expires_at ? escapeHtml(new Date(c.expires_at).toLocaleString('es-CL')) : 'Estatica'}</td><td><span class="pill ${c.active ? 'ok' : 'off'}">${c.active ? 'Activo' : 'Vencido'}</span></td></tr>`).join('') : '<tr><td colspan="6" class="empty-state">Sin clientes que coincidan.</td></tr>';
  }

  function renderFirewall() {
    const { stats, events } = metrics.data;
    const summary = $('#fw-summary');
    if (stats.data) {
      const s = stats.data;
      summary.innerHTML = [
        ['Filtro pf', s.pf_enabled == null ? '–' : s.pf_enabled ? 'Activo' : 'Inactivo'],
        ['Estados actuales', formatCount(s.states?.current_entries)],
        ['Paquetes permitidos', formatCount(s.packets_passed)],
        ['Paquetes bloqueados', formatCount(s.packets_blocked)],
      ].map(([label, value]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join('');
    } else {
      summary.innerHTML = '<div><small>Estadisticas</small><strong>No disponibles</strong></div>';
    }
    const body = $('#fw-body');
    if (!events.data) { body.innerHTML = '<tr><td colspan="6" class="empty-state">Registro del firewall no disponible.</td></tr>'; return; }
    const rows = events.data.filter((e) => !metrics.fwAction || e.action === metrics.fwAction).slice(0, 50);
    body.innerHTML = rows.length ? rows.map((e) => `<tr><td class="mono">${clockTime(e.timestamp)}</td><td><span class="pill ${e.action === 'block' ? 'block' : 'ok'}">${e.action === 'block' ? 'Bloqueado' : 'Permitido'}</span></td><td class="mono">${escapeHtml(e.interface || '–')}</td><td class="mono">${escapeHtml(endpoint(e.source_ip, e.source_port))}</td><td class="mono">${escapeHtml(endpoint(e.destination_ip, e.destination_port))}</td><td class="mono">${escapeHtml((e.protocol || '–').toUpperCase())}</td></tr>`).join('') : '<tr><td colspan="6" class="empty-state">Sin eventos para este filtro.</td></tr>';
  }

  // --------------------------------------------------------------------------- //
  // Interacciones
  // --------------------------------------------------------------------------- //

  refreshButton.addEventListener('click', async () => {
    refreshButton.disabled = true;
    refreshButton.querySelector('span').animate([{ transform: 'rotate(0)' }, { transform: 'rotate(360deg)' }], { duration: 650, easing: 'ease-in-out' });
    await poll();
    refreshButton.disabled = false;
    showToast('Datos actualizados');
  });

  document.querySelectorAll('.period[data-window]').forEach((period) => {
    period.addEventListener('click', () => {
      period.parentElement.querySelector('.active').classList.remove('active');
      period.classList.add('active');
      metrics.chartWindow = Number(period.dataset.window);
      poll();
    });
  });

  document.querySelectorAll('#fw-filter .period').forEach((button) => {
    button.addEventListener('click', () => {
      button.parentElement.querySelector('.active').classList.remove('active');
      button.classList.add('active');
      metrics.fwAction = button.dataset.action;
      if (metrics.data.events) renderFirewall();
    });
  });

  $('#clients-search').addEventListener('input', () => metrics.data.clients && renderClients());
  $('#clients-active-only').addEventListener('change', () => metrics.data.clients && renderClients());

  window.setInterval(() => { if (metrics.lastSync) syncLabel.textContent = relativeTime(metrics.lastSync); }, 1000);


  return { configureUser, reset, poll };
}
