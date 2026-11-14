// Administración de usuarios y roles (HU002). El backend autoriza cada operación.
const ROLES = [
  ['admin', 'Administrador de Red'], ['tecnico', 'Técnico de Red'], ['operador', 'Operador (alias de técnico)'],
  ['visor', 'Supervisor de Evento (solo lectura)'], ['cliente', 'Cliente'],
];

// Errores de validación por campo: FastAPI entrega una lista; el resto, un texto.
export function describeError(error) {
  const detail = error?.body?.detail;
  if (Array.isArray(detail)) return detail.map(item => `${(item.loc || []).slice(1).join('.') || 'campo'}: ${item.msg}`).join(' · ');
  return error?.message || 'No se pudo completar la operación.';
}

export function createUsers({document, state, api, textNode}) {
  const $ = id => document.querySelector('#' + id);
  const fields = ['user-email', 'user-full-name', 'user-password'];
  let allowed = false, generation = 0, editing = null, roleChecks = [];
  const capture = () => ({session: state.session, generation});
  const current = c => allowed && c.session === state.session && c.generation === generation;
  const request = (path, extra = {}) => api.authedRequest(`/admin/users${path}`, extra);

  function buildRoles() {
    roleChecks = ROLES.map(([value, label]) => {
      const wrapper = document.createElement('label'), check = document.createElement('input');
      check.type = 'checkbox'; check.value = value; wrapper.append(check, textNode('span', ' ' + label));
      return {value, check, wrapper};
    });
    $('user-roles').replaceChildren(...roleChecks.map(item => item.wrapper));
  }
  function edit(user) {
    editing = user;
    $('user-form-title').textContent = user ? `Editar ${user.email}` : 'Nuevo usuario';
    $('user-email').value = user?.email || ''; $('user-email').disabled = !!user;
    $('user-full-name').value = user?.full_name || ''; $('user-password').value = '';
    $('user-active').checked = user ? user.is_active : true; $('user-active').disabled = !user;
    for (const item of roleChecks) item.check.checked = user ? user.roles.includes(item.value) : item.value === 'visor';
    $('user-password-hint').textContent = user
      ? 'Déjala vacía para conservar la actual. Cambiarla cierra las sesiones del usuario.'
      : 'Contraseña temporal de al menos 12 caracteres; el usuario debe cambiarla en Mi cuenta.';
    $('user-cancel').hidden = !user;
  }
  function reset() {
    generation += 1; allowed = false; editing = null;
    for (const id of fields) $(id).value = '';
    $('users-body').replaceChildren(); $('users-status').textContent = ''; $('user-roles').replaceChildren(); roleChecks = [];
  }

  function row(user) {
    const line = document.createElement('tr'), context = capture();
    const cell = value => textNode('td', value);
    const actions = document.createElement('td');
    const button = (label, run) => {
      const node = textNode('button', label); node.type = 'button';
      node.addEventListener('click', () => current(context) && run()); actions.append(node); return node;
    };
    button('Editar', () => edit(user));
    button('Desbloquear', async () => {
      try { await request(`/${user.id}/unlock`, {method: 'POST'}); if (current(context)) $('users-status').textContent = `Se levantó el bloqueo de ${user.email}.`; }
      catch (error) { if (current(context)) $('users-status').textContent = describeError(error); }
    });
    line.append(cell(user.email), cell(user.full_name || '—'), cell(user.roles.join(', ')),
      cell(user.is_active ? 'Activo' : 'Desactivado'), actions);
    return line;
  }
  async function refresh() {
    if (!allowed) return;
    const context = capture();
    try {
      const users = await request(''); if (!current(context)) return;
      $('users-body').replaceChildren(...users.map(row));
    } catch (error) { if (current(context)) $('users-status').textContent = describeError(error); }
  }
  async function save(event) {
    event?.preventDefault?.();
    if (!allowed) return;
    const context = capture(), roles = roleChecks.filter(item => item.check.checked).map(item => item.value);
    const password = $('user-password').value, full_name = $('user-full-name').value.trim() || null;
    if (!roles.length) { $('users-status').textContent = 'Selecciona al menos un rol.'; return; }
    if (!editing && !password) { $('users-status').textContent = 'Define una contraseña temporal.'; return; }
    $('user-save').disabled = true;
    try {
      if (editing) {
        const body = {full_name, roles, is_active: $('user-active').checked, ...(password ? {password} : {})};
        await request(`/${editing.id}`, {method: 'PATCH', body: JSON.stringify(body)});
      } else {
        await request('', {method: 'POST', body: JSON.stringify({email: $('user-email').value.trim(), password, full_name, roles})});
      }
      if (!current(context)) return;
      $('users-status').textContent = editing ? 'Usuario actualizado. Sus sesiones anteriores quedaron cerradas si cambió rol, estado o contraseña.' : 'Usuario creado.';
      edit(null); await refresh();
    } catch (error) { if (current(context)) $('users-status').textContent = describeError(error); }
    finally { if (current(context)) $('user-save').disabled = false; $('user-password').value = ''; }
  }
  async function configureUser(user) {
    if (!user.permissions?.includes('users:manage')) return;
    allowed = true; buildRoles(); edit(null); await refresh();
  }
  $('user-form').addEventListener('submit', save);
  $('user-cancel').addEventListener('click', () => allowed && edit(null));
  $('users-refresh').addEventListener('click', refresh);
  return {reset, configureUser, refresh};
}
