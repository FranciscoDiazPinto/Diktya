// Registro administrable; no comparte datos con el chat ni persiste contactos en el navegador.
export function createWifiRecipients({document, Option, state, api}) {
  const $ = s => document.querySelector(s);
  const panel = $('#wifi-recipients-panel'), network = $('#wifi-recipients-network');
  const contacts = $('#wifi-recipients-contacts'), save = $('#wifi-recipients-save'), status = $('#wifi-recipients-status');
  let generation = 0, loaded = false;
  const capture = () => ({session: state.session, generation, id: network.value});
  const current = c => c.session === state.session && c.generation === generation && c.id === network.value;
  function reset() {
    generation += 1; loaded = false; panel.hidden = true; contacts.value = ''; status.textContent = '';
    network.replaceChildren(new Option('Selecciona una red', '')); network.disabled = false; save.disabled = true; contacts.disabled = true;
  }
  async function configureUser(user) {
    if (!user.permissions?.includes('networks:manage')) return;
    panel.hidden = false;
    const context = capture();
    try {
      const networks = await api.authedRequest('/api/v1/networks');
      if (!current(context)) return;
      network.replaceChildren(new Option('Selecciona una red', ''), ...networks.map(n => new Option(`${n.name} · ${n.ssid}`, n.id)));
    } catch (error) { if (current(context)) status.textContent = error.message; }
  }
  network.addEventListener('change', async () => {
    generation += 1; loaded = false; contacts.value = ''; status.textContent = ''; save.disabled = true; contacts.disabled = true;
    if (!network.value) return;
    const context = capture();
    try {
      const rows = await api.authedRequest(`/admin/networks/${Number(context.id)}/recipients`);
      if (!current(context)) return;
      contacts.value = rows.map(r => `${r.email || ''};${r.phone || ''}`).join('\n');
      loaded = true; save.disabled = false; contacts.disabled = false;
    } catch (error) { if (current(context)) status.textContent = error.message; }
  });
  $('#wifi-recipients-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!loaded || !network.value || save.disabled) return;
    const context = capture();
    const lines = contacts.value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    if (lines.length > 500 || lines.some(s => s.split(';').length !== 2)) {
      status.textContent = 'Usa correo;teléfono en cada línea, máximo 500 clientes.'; return;
    }
    const recipients = lines.map(line => { const [email, phone] = line.split(';').map(v => v.trim()); return {email: email || null, phone: phone || null}; });
    save.disabled = true; contacts.disabled = true; network.disabled = true;
    try {
      const rows = await api.authedRequest(`/admin/networks/${Number(context.id)}/recipients`, {method: 'PUT', body: JSON.stringify({recipients})});
      if (!current(context)) return;
      contacts.value = rows.map(r => `${r.email || ''};${r.phone || ''}`).join('\n');
      status.textContent = `${rows.length} destinatario(s) guardados para esta red.`;
    } catch (error) { if (current(context)) status.textContent = error.status === 422 ? 'Revisa los correos y teléfonos. Cada cliente necesita al menos uno; incluye código de país.' : error.message; }
    finally { if (current(context)) { save.disabled = false; contacts.disabled = false; network.disabled = false; } }
  });
  return {reset, configureUser};
}
