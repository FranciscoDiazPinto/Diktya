// Cambio de la contraseña propia. Tras cambiarla el backend cierra todas las sesiones.
import { describeError } from './users.mjs';

export function createAccount({document, state, api, onPasswordChanged = () => {}}) {
  const $ = id => document.querySelector('#' + id);
  const fields = ['account-current', 'account-new', 'account-repeat'];
  let generation = 0;
  const clear = () => { for (const id of fields) $(id).value = ''; };
  function reset() { generation += 1; clear(); $('account-status').textContent = ''; $('account-email').textContent = ''; }
  function configureUser(user) { $('account-email').textContent = user.email || ''; }
  $('account-form').addEventListener('submit', async event => {
    event?.preventDefault?.();
    const [current_password, new_password, repeat] = fields.map(id => $(id).value);
    if (new_password.length < 12) { $('account-status').textContent = 'La nueva contraseña debe tener al menos 12 caracteres.'; return; }
    if (new_password !== repeat) { $('account-status').textContent = 'La confirmación no coincide con la nueva contraseña.'; return; }
    const session = state.session, version = generation;
    $('account-save').disabled = true;
    try {
      await api.authedRequest('/auth/password', {method: 'POST', body: JSON.stringify({current_password, new_password})});
      if (session !== state.session || version !== generation) return;
      clear(); onPasswordChanged();
    } catch (error) {
      if (session === state.session && version === generation)
        $('account-status').textContent = error.status === 401 || error.status === 403 ? 'La contraseña actual no es correcta.' : describeError(error);
    } finally { clear(); $('account-save').disabled = false; }
  });
  return {reset, configureUser};
}
