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

const getStoredTokens = () => {
  try { return JSON.parse(localStorage.getItem('netbot_tokens') || 'null'); } catch { return null; }
};

function setAuthenticated(user) {
  loginScreen.style.display = 'none';
  appShell.classList.remove('is-hidden');
  const name = user.full_name || user.email.split('@')[0];
  document.querySelector('#user-name').textContent = name;
  document.querySelector('#user-role').textContent = user.roles?.join(', ') || 'Usuario';
  document.querySelector('#user-avatar').textContent = name.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase();
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
  showToast('Sesion cerrada');
});

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