import { canReserveVlans, reservationPayload } from './chat-reservations.mjs';

const API_BASE = localStorage.getItem('netbot_api_url') || 'http://localhost:8000';
const MONITORING = '/api/v1/monitoring';
const POLL_MS = 5000;

const $ = (selector) => document.querySelector(selector);
const loginScreen = $('#login-screen');
const appShell = $('#app-shell');
const loginForm = $('#login-form');
const loginSubmit = $('#login-submit');
const loginError = $('#login-error');
const togglePassword = $('#toggle-password');
const logoutButton = $('#logout-button');
const refreshButton = $('#refresh-button');
const syncLabel = $('#last-sync');
const toast = $('#toast');
const mobileMenu = $('.mobile-menu');
const sidebar = $('.sidebar');

const state = {
  user: null,
  timer: null,
  lastSync: null,
  chartWindow: 300,
  fwAction: '',
  data: {},
  rates: {}, // interface_id -> { in, out } en bytes/s (ultimo punto del historial)
  history: { interfaces: [], traffic: [], clients: [], blocked: [] },
};

// --------------------------------------------------------------------------- //
// Utilidades de formato
// --------------------------------------------------------------------------- //

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function formatBytes(bytes) {
  if (bytes == null) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatRate(bytesPerSecond) {
  if (bytesPerSecond == null) return '–';
  const bits = bytesPerSecond * 8;
  if (bits >= 1e9) return `${(bits / 1e9).toFixed(2)} Gb/s`;
  if (bits >= 1e6) return `${(bits / 1e6).toFixed(1)} Mb/s`;
  if (bits >= 1e3) return `${(bits / 1e3).toFixed(0)} kb/s`;
  return `${bits.toFixed(0)} b/s`;
}

function formatCount(value) {
  if (value == null) return '–';
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} G`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)} k`;
  return String(value);
}

function formatDuration(seconds) {
  if (seconds == null) return '–';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function relativeTime(date) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(date).getTime()) / 1000));
  if (seconds < 5) return 'ahora mismo';
  if (seconds < 60) return `hace ${seconds} s`;
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)} h`;
  return `hace ${Math.floor(seconds / 86400)} d`;
}

const clockTime = (date) => new Date(date).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const endpoint = (ip, port) => (port != null ? `${ip}:${port}` : ip);

// --------------------------------------------------------------------------- //
// API y sesión
// --------------------------------------------------------------------------- //

const chatForm = document.querySelector('#chat-form');
const chatInput = document.querySelector('#chat-message');
const chatMessages = document.querySelector('#chat-messages');
const chatEmpty = document.querySelector('#chat-empty');
const chatStatus = document.querySelector('#chat-status');
const chatSend = document.querySelector('#chat-send');
let chatHistory = [];
let currentRoles = [];
const reservationList = document.querySelector('#vlan-reservations');

const getStoredTokens = () => {
  try { return JSON.parse(localStorage.getItem('netbot_tokens') || 'null'); } catch { return null; }
};

class ApiError extends Error {
  constructor(message, status, body) { super(message); this.status = status; this.body = body; }
}

async function apiRequest(path, options = {}, accessToken = '') {
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...(options.headers || {}) } });
  if (response.status === 204) return null;
  let body = null;
  try { body = await response.json(); } catch {}
  if (!response.ok) throw new ApiError(body?.detail || 'No fue posible conectar con Netbot.', response.status, body);
  return body;
}

async function refreshTokens() {
  const tokens = getStoredTokens();
  if (!tokens?.refresh_token) throw new ApiError('Sesion expirada', 401);
  const fresh = await apiRequest('/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) });
  localStorage.setItem('netbot_tokens', JSON.stringify(fresh));
  return fresh;
}

// Peticion autenticada: si el token de acceso vencio, lo renueva una vez y reintenta.
async function authedRequest(path) {
  const tokens = getStoredTokens();
  try {
    return await apiRequest(path, {}, tokens?.access_token);
  } catch (error) {
    if (error.status !== 401) throw error;
    const fresh = await refreshTokens();
    return apiRequest(path, {}, fresh.access_token);
  }
}

// Los endpoints de monitoreo responden 503 con el mismo envoltorio cuando la fuente no tiene datos.
async function monitoringRequest(path) {
  try {
    return await authedRequest(`${MONITORING}${path}`);
  } catch (error) {
    if (error.status === 503 && error.body?.status) return error.body;
    throw error;
  }
}

function setAuthenticated(user) {
  state.user = user;
  currentRoles = user.roles || [];
  reservationList.hidden = !canReserveVlans(currentRoles);
  if (!reservationList.hidden) refreshReservations();
  loginScreen.style.display = 'none';
  appShell.classList.remove('is-hidden');
  const name = user.full_name || user.email.split('@')[0];
  $('#user-name').textContent = name;
  $('#user-role').textContent = user.roles?.join(', ') || 'Usuario';
  $('#user-avatar').textContent = name.split(/[\s._-]+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();
  renderGreeting();
  startPolling();
}

function signOut(message) {
  stopPolling();
  localStorage.removeItem('netbot_tokens');
  state.user = null;
  chatHistory = [];
  currentRoles = [];
  reservationList.replaceChildren();
  reservationList.hidden = true;
  chatMessages.replaceChildren(chatEmpty);
  chatEmpty.hidden = false;
  chatStatus.textContent = "";
  chatStatus.classList.remove("is-error");
  state.rates = {};
  state.history = { interfaces: [], traffic: [], clients: [], blocked: [] };
  appShell.classList.add('is-hidden');
  loginScreen.style.display = '';
  loginForm.reset();
  if (message) showToast(message);
}

async function validateSession() {
  if (!getStoredTokens()?.access_token) return;
  try { setAuthenticated(await authedRequest('/auth/me')); } catch { localStorage.removeItem('netbot_tokens'); }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  loginSubmit.disabled = true;
  loginSubmit.firstChild.textContent = 'Conectando ';
  try {
    const formData = new FormData(loginForm);
    const tokens = await apiRequest('/auth/login', { method: 'POST', body: JSON.stringify({ email: formData.get('email'), password: formData.get('password') }) });
    localStorage.setItem('netbot_tokens', JSON.stringify(tokens));
    setAuthenticated(await apiRequest('/auth/me', {}, tokens.access_token));
  } catch (error) {
    loginError.textContent = error.status === 401 ? 'El correo o la contraseña no son correctos.' : 'No se pudo conectar con la API. Revisa que el backend este activo.';
  } finally {
    loginSubmit.disabled = false;
    loginSubmit.firstChild.textContent = 'Ingresar ';
  }
});

togglePassword.addEventListener('click', () => {
  const password = $('#password');
  password.type = password.type === 'password' ? 'text' : 'password';
  togglePassword.textContent = password.type === 'password' ? 'Mostrar' : 'Ocultar';
});

logoutButton.addEventListener('click', async () => {
  const tokens = getStoredTokens();
  try { if (tokens?.refresh_token) await apiRequest('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) }); } catch {}
  signOut('Sesion cerrada');
});

function appendChatMessage(role, content) {
  chatEmpty.hidden = true;
  const message = document.createElement('article');
  message.className = `chat-message chat-message-${role}`;
  const text = document.createElement('p');
  text.textContent = content;
  message.append(text);
  chatMessages.append(message);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return message;
}

function setChatStatus(message, isError = false) {
  chatStatus.textContent = message;
  chatStatus.classList.toggle('is-error', isError);
}

chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message || chatSend.disabled) return;

  const tokens = getStoredTokens();
  if (!tokens?.access_token) {
    setChatStatus('Inicia sesión para conversar con Netbot.', true);
    return;
  }

  appendChatMessage('user', message);
  chatInput.value = '';
  chatSend.disabled = true;
  chatInput.disabled = true;
  setChatStatus('Consultando el monitoreo…');
  try {
    const response = await apiRequest(
      '/api/v1/chat/messages',
      {
        method: 'POST',
        body: JSON.stringify({ message, history: chatHistory.slice(-8) }),
      },
      tokens.access_token,
    );
    appendChatMessage('assistant', response.answer);
    if (response.reservation_proposal && canReserveVlans(currentRoles)) {
      renderReservationProposal(response.reservation_proposal);
    }
    chatHistory = [
      ...chatHistory,
      { role: 'user', content: message },
      { role: 'assistant', content: response.answer },
    ].slice(-8);
    setChatStatus('Consulta completada.');
  } catch (error) {
    setChatStatus(error.message || 'No se pudo completar la consulta.', true);
  } finally {
    chatSend.disabled = false;
    chatInput.disabled = false;
    chatInput.focus();
  }
});

function textNode(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value ?? '';
  if (className) element.className = className;
  return element;
}

function renderReservationProposal(proposal) {
  const card = document.createElement('article');
  card.className = 'reservation-card';
  card.append(textNode('h3', 'Propuesta de reserva VLAN'));
  card.append(textNode('p', `VLAN ${proposal.tag} · ${proposal.parent_interface} · ${proposal.description || proposal.interface_name}`));
  card.append(textNode('p', `Evento: ${proposal.event_name} · Propósito: ${proposal.purpose} · SSID: ${proposal.ssid}`));
  card.append(textNode('p', 'La VLAN solo quedará reservada después de confirmar.'));
  const actions = document.createElement('div');
  actions.className = 'reservation-actions';
  const confirm = textNode('button', 'Confirmar');
  confirm.type = 'button';
  const cancel = textNode('button', 'Cancelar');
  cancel.type = 'button';
  cancel.className = 'button-secondary';
  cancel.addEventListener('click', () => card.remove());
  confirm.addEventListener('click', async () => {
    const tokens = getStoredTokens();
    confirm.disabled = cancel.disabled = true;
    try {
      await apiRequest('/api/v1/changes/vlan-reservations', {
        method: 'POST', body: JSON.stringify(reservationPayload(proposal)),
      }, tokens?.access_token);
      card.replaceChildren(textNode('p', 'Reserva confirmada.'));
      await refreshReservations();
    } catch (error) {
      confirm.disabled = cancel.disabled = false;
      card.append(textNode('p', error.message, 'reservation-error'));
    }
  });
  actions.append(confirm, cancel);
  card.append(actions);
  chatMessages.append(card);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function refreshReservations() {
  if (!canReserveVlans(currentRoles)) return;
  const tokens = getStoredTokens();
  try {
    const rows = await apiRequest('/api/v1/changes/vlan-reservations', {}, tokens?.access_token);
    reservationList.replaceChildren(textNode('h3', 'Reservas VLAN activas'));
    if (!rows.length) reservationList.append(textNode('p', 'No hay reservas activas.'));
    for (const row of rows) {
      const item = document.createElement('article');
      item.className = 'reservation-card';
      item.append(textNode('strong', `VLAN ${row.tag} · ${row.parent_interface}`));
      item.append(textNode('p', `${row.event_name} · ${row.purpose} · SSID ${row.ssid}`));
      const release = textNode('button', 'Liberar');
      release.type = 'button';
      release.addEventListener('click', async () => {
        release.disabled = true;
        try {
          await apiRequest(`/api/v1/changes/vlan-reservations/${row.id}/release`, { method: 'POST' }, tokens?.access_token);
          await refreshReservations();
        } catch (error) {
          release.disabled = false;
          showToast(error.message);
        }
      });
      item.append(release);
      reservationList.append(item);
    }
  } catch (error) {
    reservationList.replaceChildren(textNode('p', `No se pudieron cargar las reservas: ${error.message}`));
  }
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 2200);
}

// --------------------------------------------------------------------------- //
// Recolección
// --------------------------------------------------------------------------- //

function startPolling() {
  stopPolling();
  poll();
  state.timer = window.setInterval(poll, POLL_MS);
}

function stopPolling() {
  if (state.timer) window.clearInterval(state.timer);
  state.timer = null;
}

async function poll() {
  try {
    const [system, interfaces, traffic, clients, stats, events] = await Promise.all([
      monitoringRequest('/system'),
      monitoringRequest('/interfaces'),
      monitoringRequest(`/interfaces/traffic?window=${state.chartWindow}`),
      monitoringRequest('/clients'),
      monitoringRequest('/firewall/stats'),
      monitoringRequest('/firewall/events?limit=200'),
    ]);
    state.data = { system, interfaces, traffic, clients, stats, events };
    state.lastSync = new Date();
    recordSamples();
    render();
  } catch (error) {
    if (error.status === 401) { signOut('Tu sesion expiro, ingresa nuevamente'); return; }
    if (error.status === 403) { renderFatal('Tu usuario no tiene permiso para ver el monitoreo (monitoring:read).'); return; }
    renderFatal('No se pudo conectar con la API de Netbot.');
  }
}

function pushHistory(key, value) {
  if (value == null) return;
  const list = state.history[key];
  list.push(value);
  if (list.length > 8) list.shift();
}

// La API calcula la velocidad (bytes/s) a partir de muestras periodicas de los contadores.
function recordSamples() {
  const { interfaces, traffic, clients, stats } = state.data;
  state.rates = {};
  for (const series of traffic.data || []) {
    const last = series.points[series.points.length - 1];
    if (last) state.rates[series.interface_id] = { in: last.bytes_in_per_second, out: last.bytes_out_per_second };
  }
  const wanRate = state.rates.wan;
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
  syncLabel.textContent = relativeTime(state.lastSync);
}

function renderGreeting() {
  const now = new Date();
  const hour = now.getHours();
  const salute = hour < 12 ? 'Buenos dias' : hour < 20 ? 'Buenas tardes' : 'Buenas noches';
  const name = (state.user?.full_name || state.user?.email.split('@')[0] || '').split(/[\s.]/)[0];
  const capitalized = name ? name[0].toUpperCase() + name.slice(1) : '';
  $('#greeting').innerHTML = `${salute}${capitalized ? `, ${escapeHtml(capitalized)}` : ''} <span>↗</span>`;
  $('#today-label').textContent = now.toLocaleDateString('es-CL', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
}

const RESOURCE_LABELS = { system: 'Sistema', interfaces: 'Interfaces', traffic: 'Historial de trafico', clients: 'Clientes DHCP', stats: 'Estadisticas del firewall', events: 'Registro del firewall' };

function renderStatus() {
  const entries = Object.entries(state.data);
  const statuses = entries.map(([, r]) => r.status);
  const worst = statuses.includes('unavailable') ? 'unavailable' : statuses.includes('degraded') ? 'degraded' : 'ok';
  const source = state.data.system?.source || entries[0]?.[1].source;
  const sourceName = source === 'mock' ? 'Simulador' : source === 'opnsense' ? 'OPNsense' : 'Sin fuente';

  $('#source-name').textContent = sourceName;
  $('#source-detail').textContent = worst === 'ok' ? `Operativo · ${clockTime(state.lastSync)}` : worst === 'degraded' ? 'Datos parciales' : 'Fuente con fallas';
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
  const { interfaces, clients, stats, events } = state.data;

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
  const wanRate = wan && state.rates[wan.interface_id];
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

  renderSparkline('spark-interfaces', state.history.interfaces);
  renderSparkline('spark-traffic', state.history.traffic);
  renderSparkline('spark-clients', state.history.clients);
  renderSparkline('spark-blocked', state.history.blocked);
}

function renderChart() {
  const series = state.data.traffic?.data?.find((h) => h.interface_id === 'wan');
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
  const system = state.data.system.data;
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
  const events = state.data.events.data;
  $('#activity-list').innerHTML = events?.length ? events.slice(0, 6).map(eventRow).join('') : `<p class="empty-state">${events ? 'Sin eventos recientes.' : 'Registro del firewall no disponible.'}</p>`;
}

function renderInterfaces() {
  const interfaces = state.data.interfaces.data;
  if (!interfaces) { $('#interfaces-list').innerHTML = '<p class="empty-state">Interfaces no disponibles.</p>'; return; }
  $('#interfaces-list').innerHTML = interfaces.map((i) => {
    const rate = state.rates[i.interface_id];
    const statusClass = i.status === 'up' ? '' : i.status === 'down' ? 'down' : 'warning';
    const traffic = i.status !== 'up' ? 'Sin enlace' : rate ? `↓ ${formatRate(rate.in)} ↑ ${formatRate(rate.out)}` : `Σ ${formatBytes((i.traffic?.bytes_in || 0) + (i.traffic?.bytes_out || 0))}`;
    const errors = (i.traffic?.errors_in || 0) + (i.traffic?.errors_out || 0);
    return `<div class="interface-row"><span class="interface-status ${statusClass}"></span><div><strong>${escapeHtml(i.description || i.interface_id.toUpperCase())}</strong><small>${escapeHtml(i.name)} · ${escapeHtml(i.ip_addresses.join(', ') || 'sin IP')}</small></div><span class="interface-speed">${errors ? `${errors} errores` : escapeHtml(i.interface_id)}</span><span class="interface-traffic ${statusClass}">${traffic}</span></div>`;
  }).join('');
}

function renderClients() {
  const clients = state.data.clients?.data;
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
  const { stats, events } = state.data;
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
  const rows = events.data.filter((e) => !state.fwAction || e.action === state.fwAction).slice(0, 50);
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
    state.chartWindow = Number(period.dataset.window);
    poll();
  });
});

document.querySelectorAll('#fw-filter .period').forEach((button) => {
  button.addEventListener('click', () => {
    button.parentElement.querySelector('.active').classList.remove('active');
    button.classList.add('active');
    state.fwAction = button.dataset.action;
    if (state.data.events) renderFirewall();
  });
});

$('#clients-search').addEventListener('input', () => state.data.clients && renderClients());
$('#clients-active-only').addEventListener('change', () => state.data.clients && renderClients());

document.querySelectorAll('.nav-item[href]').forEach((item) => item.addEventListener('click', () => {
  document.querySelector('.nav-item.active')?.classList.remove('active');
  item.classList.add('active');
  sidebar.classList.remove('open');
}));

mobileMenu.addEventListener('click', () => sidebar.classList.toggle('open'));
window.setInterval(() => { if (state.lastSync) syncLabel.textContent = relativeTime(state.lastSync); }, 1000);

validateSession();
