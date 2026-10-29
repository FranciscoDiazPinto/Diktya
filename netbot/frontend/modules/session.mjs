
export function createSession({ document, state, api, FormData, showToast, onAuthenticated, onSignedOut }) {
  const $ = (selector) => document.querySelector(selector);
  const { apiRequest, authedRequest, getStoredTokens } = api;
  const loginScreen = $('#login-screen'), appShell = $('#app-shell'), loginForm = $('#login-form');
  const loginSubmit = $('#login-submit'), loginError = $('#login-error');
  const togglePassword = $('#toggle-password'), logoutButton = $('#logout-button');
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
  }

  function signOut(message) {
    api.clearTokens();
    state.user = null;
    state.session += 1;
    appShell.classList.add('is-hidden');
    loginScreen.style.display = '';
    loginForm.reset();
    onSignedOut();
    if (message) showToast(message);
  }

  async function validateSession() {
    if (!getStoredTokens()?.access_token) return;
    try { setAuthenticated(await authedRequest('/auth/me')); } catch { api.clearTokens(); }
  }

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    loginError.textContent = '';
    loginSubmit.disabled = true;
    loginSubmit.firstChild.textContent = 'Conectando ';
    try {
      const formData = new FormData(loginForm);
      const tokens = await apiRequest('/auth/login', { method: 'POST', body: JSON.stringify({ email: formData.get('email'), password: formData.get('password') }) });
      api.setTokens(tokens);
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
    signOut('Sesion cerrada');
    try { if (tokens?.refresh_token) await apiRequest('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) }); } catch {}
  });


  return { setAuthenticated, signOut, validateSession };
}
