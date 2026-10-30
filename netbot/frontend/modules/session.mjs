
export function createSession({ document, window = globalThis, now = () => Date.now(), state, api, FormData, showToast, onAuthenticated, onSignedOut }) {
  const $ = (selector) => document.querySelector(selector);
  const { apiRequest, authedRequest, getStoredTokens } = api;
  const loginScreen = $('#login-screen'), appShell = $('#app-shell'), loginForm = $('#login-form');
  const loginSubmit = $('#login-submit'), loginError = $('#login-error');
  const togglePassword = $('#toggle-password'), logoutButton = $('#logout-button');
  let expiryTimer = null, expiresAt = 0, loginAttempt = 0;
  function clearExpiry() { if (expiryTimer !== null) window.clearTimeout?.(expiryTimer); expiryTimer = null; expiresAt = 0; }
  function checkExpiry() {
    if (!state.user || !expiresAt) return;
    if (now() >= expiresAt) { expire(); return; }
    expiryTimer = window.setTimeout(checkExpiry, Math.min(expiresAt - now(), 2147483647));
  }
  function watchExpiry() {
    clearExpiry();
    try {
      const encoded = getStoredTokens()?.access_token?.split('.')[1];
      if (!encoded) return;
      const payload = JSON.parse(atob(encoded.replace(/-/g, '+').replace(/_/g, '/')));
      if (!Number.isFinite(payload.exp)) return;
      expiresAt = payload.exp * 1000;
      checkExpiry();
    } catch { /* El servidor valida firma, formato y sesión; no confiar en este temporizador. */ }
  }
  function expire() {
    if (!getStoredTokens() && !state.user) return;
    const tokens = getStoredTokens();
    signOut('Tu sesión expiró. Inicia sesión nuevamente.', {expired:true});
    if (tokens?.refresh_token) apiRequest('/auth/logout', {method:'POST', body:JSON.stringify({refresh_token:tokens.refresh_token})}).catch(() => {});
    loginError.textContent = 'Tu sesión expiró. Inicia sesión nuevamente.';
    $('#email').focus();
  }
  document.addEventListener?.('visibilitychange', () => { if (expiryTimer !== null) window.clearTimeout?.(expiryTimer); checkExpiry(); });
  window.addEventListener?.('pageshow', () => { if (expiryTimer !== null) window.clearTimeout?.(expiryTimer); checkExpiry(); });
  function setAuthenticated(user) {
    state.session += 1;
    state.user = user;
    loginScreen.style.display = 'none';
    appShell.classList.remove('is-hidden');
    const name = user.full_name || user.email.split('@')[0];
    $('#user-name').textContent = name;
    $('#user-role').textContent = user.roles?.join(', ') || 'Usuario';
    $('#user-avatar').textContent = name.split(/[\s._-]+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();
    onAuthenticated(user);
    watchExpiry();
  }

  function signOut(message, {expired = false} = {}) {
    clearExpiry();
    loginAttempt += 1;
    loginSubmit.disabled = false; loginSubmit.firstChild.textContent = 'Ingresar ';
    api.clearTokens();
    state.user = null;
    state.session += 1;
    appShell.classList.add('is-hidden');
    loginScreen.style.display = '';
    loginForm.reset();
    $('#password').type = 'password'; togglePassword.textContent = 'Mostrar';
    togglePassword.setAttribute?.('aria-label', 'Mostrar contraseña');
    onSignedOut({expired});
    if (message) showToast(message);
  }

  async function validateSession() {
    if (!getStoredTokens()?.access_token) return;
    const epoch = state.session;
    try { const user = await authedRequest('/auth/me'); if (epoch === state.session) setAuthenticated(user); } catch { if (epoch === state.session) api.clearTokens(); }
  }

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const attempt = ++loginAttempt, epoch = state.session;
    const current = () => attempt === loginAttempt && epoch === state.session;
    loginError.textContent = '';
    loginSubmit.disabled = true;
    loginSubmit.firstChild.textContent = 'Conectando ';
    try {
      const formData = new FormData(loginForm);
      const tokens = await apiRequest('/auth/login', { method: 'POST', body: JSON.stringify({ email: formData.get('email'), password: formData.get('password') }) });
      if (!current()) return;
      const user = await apiRequest('/auth/me', {}, tokens.access_token);
      if (!current()) return;
      api.setTokens(tokens);
      $('#password').value = '';
      setAuthenticated(user);
    } catch (error) {
      if (!current()) return;
      api.clearTokens();
      loginError.textContent = error.status === 401 ? 'El correo o la contraseña no son correctos.' : 'No se pudo conectar con la API. Revisa que el backend este activo.';
    } finally {
      if (attempt === loginAttempt) {
        loginSubmit.disabled = false;
        loginSubmit.firstChild.textContent = 'Ingresar ';
      }
    }
  });

  $('#guest-back')?.addEventListener('click', () => {
    loginAttempt += 1;
    loginSubmit.disabled = false; loginSubmit.firstChild.textContent = 'Ingresar ';
    loginError.textContent = ''; $('#password').value = '';
  });

  togglePassword.addEventListener('click', () => {
    const password = $('#password');
    password.type = password.type === 'password' ? 'text' : 'password';
    togglePassword.textContent = password.type === 'password' ? 'Mostrar' : 'Ocultar';
    togglePassword.setAttribute?.('aria-label', password.type === 'password' ? 'Mostrar contraseña' : 'Ocultar contraseña');
  });

  logoutButton.addEventListener('click', async () => {
    const tokens = getStoredTokens();
    signOut('Sesion cerrada');
    try { if (tokens?.refresh_token) await apiRequest('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) }); } catch {}
  });


  return { setAuthenticated, signOut, expire, validateSession, checkExpiry };
}
