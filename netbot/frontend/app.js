import { canReserveVlans, reservationPayload } from './chat-reservations.mjs';

const API_BASE = localStorage.getItem('netbot_api_url') || 'http://localhost:8000';
const loginScreen = document.querySelector('#login-screen');
const appShell = document.querySelector('#app-shell');
const loginForm = document.querySelector('#login-form');
const loginSubmit = document.querySelector('#login-submit');
const loginError = document.querySelector('#login-error');
const togglePassword = document.querySelector('#toggle-password');
const logoutButton = document.querySelector('#logout-button');
const refreshButton = document.querySelector('#refresh-button');
const syncLabel = document.querySelector('#last-sync');
const toast = document.querySelector('#toast');
const mobileMenu = document.querySelector('.mobile-menu');
const sidebar = document.querySelector('.sidebar');
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

function setAuthenticated(user) {
  currentRoles = user.roles || [];
  loginScreen.style.display = 'none';
  appShell.classList.remove('is-hidden');
  const name = user.full_name || user.email.split('@')[0];
  document.querySelector('#user-name').textContent = name;
  document.querySelector('#user-role').textContent = user.roles?.join(', ') || 'Usuario';
  document.querySelector('#user-avatar').textContent = name.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase();
  reservationList.hidden = !canReserveVlans(currentRoles);
  if (!reservationList.hidden) refreshReservations();
}

async function apiRequest(path, options = {}, accessToken = '') {
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...(options.headers || {}) } });
  if (!response.ok) { let detail = 'No fue posible conectar con Netbot.'; try { detail = (await response.json()).detail || detail; } catch {} throw new Error(detail); }
  return response.status === 204 ? null : response.json();
}

async function validateSession() {
  const tokens = getStoredTokens();
  if (!tokens?.access_token) return;
  try { setAuthenticated(await apiRequest('/auth/me', {}, tokens.access_token)); } catch { localStorage.removeItem('netbot_tokens'); }
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
    loginError.textContent = error.message === 'Invalid credentials' ? 'El correo o la contraseña no son correctos.' : 'No se pudo conectar con la API. Revisa que el backend este activo.';
  } finally {
    loginSubmit.disabled = false;
    loginSubmit.firstChild.textContent = 'Ingresar ';
  }
});

togglePassword.addEventListener('click', () => {
  const password = document.querySelector('#password');
  password.type = password.type === 'password' ? 'text' : 'password';
  togglePassword.textContent = password.type === 'password' ? 'Mostrar' : 'Ocultar';
});

logoutButton.addEventListener('click', async () => {
  const tokens = getStoredTokens();
  try { if (tokens?.refresh_token) await apiRequest('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) }); } catch {}
  localStorage.removeItem('netbot_tokens');
  appShell.classList.add('is-hidden');
  loginScreen.style.display = '';
  loginForm.reset();
  chatHistory = [];
  currentRoles = [];
  reservationList.replaceChildren();
  reservationList.hidden = true;
  chatMessages.replaceChildren(chatEmpty);
  chatEmpty.hidden = false;
  chatStatus.textContent = '';
  chatStatus.classList.remove('is-error');
  showToast('Sesion cerrada');
});

function appendChatMessage(role, content) {
  chatEmpty.hidden = true;
  const message = document.createElement('article');
  message.className = `chat-message chat-message-${role}`;
  const text = document.createElement('p');
  text.textContent = content;
  message.append(text);
  chatMessages.append(message);
  return message;
  chatMessages.scrollTop = chatMessages.scrollHeight;
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

refreshButton.addEventListener('click', () => {
  refreshButton.disabled = true;
  refreshButton.querySelector('span').style.display = 'inline-block';
  refreshButton.querySelector('span').animate(
    [{ transform: 'rotate(0)' }, { transform: 'rotate(360deg)' }],
    { duration: 650, easing: 'ease-in-out' },
  );
  window.setTimeout(() => {
    syncLabel.textContent = 'ahora mismo';
    refreshButton.disabled = false;
    showToast('Datos actualizados');
  }, 650);
});

document.querySelectorAll('.period').forEach((period) => {
  period.addEventListener('click', () => {
    document.querySelector('.period.active').classList.remove('active');
    period.classList.add('active');
    showToast(`Periodo seleccionado: ${period.textContent}`);
  });
});

mobileMenu.addEventListener('click', () => sidebar.classList.toggle('open'));
document.querySelectorAll('.nav-item').forEach((item) => item.addEventListener('click', () => sidebar.classList.remove('open')));

validateSession();
