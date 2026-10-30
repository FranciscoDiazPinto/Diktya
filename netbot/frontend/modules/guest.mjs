// Estado privado en memoria. No usa localStorage, cookies ni el chat autenticado.
export function createGuest({document, window, api, Option, now = () => Date.now()}) {
  const $ = (s) => document.querySelector(s);
  const screen = $('#guest-screen'), messages = $('#guest-messages'), input = $('#guest-message');
  let generation = 0, token = null, creating = null, timer = null, deadline = 0;
  let visible = false, busy = false, stage = '', lastActivity = 0;
  let aborter = new AbortController();
  const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
  const current = (g) => visible && g === generation;
  const request = (path, options = {}) => api.apiRequest(`/api/v1/guest${path}`, {
    cache: 'no-store', ...options, headers: {'X-Guest-Session': token, ...options.headers}, signal: aborter.signal,
  });
  function say(value, role = 'assistant') {
    const node = document.createElement('div'); node.className = `chat-message chat-message-${role}`;
    node.append(text('p', value)); messages.append(node); messages.scrollTop = messages.scrollHeight;
  }
  function setBusy(value) {
    busy = value; $('#guest-send').disabled = value; $('#guest-show-qr').disabled = value; $('#guest-wifi-button').disabled = value;
    $('#guest-network').disabled = value;
    $('#guest-identify-submit').disabled = value; $('#guest-contact').disabled = value;
    $('#guest-portal-button').disabled = value;
  }
  function cancelTimer() { if (timer !== null) window.clearTimeout?.(timer); timer = null; deadline = 0; }
  function arm() {
    cancelTimer(); deadline = now() + 60000;
    timer = window.setTimeout(checkExpiry, 60000);
    $('#guest-status').textContent = 'La atención se limpiará tras un minuto sin respuesta.';
  }
  function checkExpiry() {
    if (deadline && now() >= deadline) reset('La atención anterior se limpió. Hola, ¿en qué puedo ayudarte?');
  }
  function reset(welcome = '¡Hola! Puedo ayudarte a recuperar el acceso Wi-Fi enviado a tu correo. ¿Qué necesitas?') {
    const old = token; generation += 1; token = null; creating = null;
    aborter.abort(); aborter = new AbortController(); cancelTimer(); stage = ''; lastActivity = 0;
    setBusy(false); input.value = ''; messages.replaceChildren(); $('#guest-qr').replaceChildren();
    $('#guest-wifi').hidden = true; $('#guest-network').replaceChildren(); $('#guest-resolution').hidden = true;
    $('#guest-contact').value = ''; $('#guest-identify-form').hidden = true; $('#guest-identify-error').textContent = '';
    $('#guest-status').textContent = ''; say(welcome);
    if (old) api.apiRequest('/api/v1/guest/session', {method: 'DELETE', cache: 'no-store', keepalive: true, headers: {'X-Guest-Session': old}}).catch(() => {});
  }
  async function ensureSession() {
    if (token) return token;
    if (creating) return creating;
    const g = generation;
    const pending = api.apiRequest('/api/v1/guest/sessions', {method: 'POST', cache: 'no-store', signal: aborter.signal}).then((result) => {
      if (!current(g)) {
        api.apiRequest('/api/v1/guest/session', {method: 'DELETE', headers: {'X-Guest-Session': result.token}}).catch(() => {});
        throw new Error('La atención cambió.');
      }
      token = result.token; return token;
    });
    creating = pending;
    try { return await pending; } finally { if (creating === pending) creating = null; }
  }
  function askResolved() {
    stage = 'resolved'; $('#guest-resolution').hidden = false;
    $('#guest-question').textContent = '¿Se resolvió tu duda?';
    $('#guest-yes').textContent = 'Sí, se resolvió'; $('#guest-no').textContent = 'Necesito más ayuda';
    say('¿Se resolvió tu duda? Puedes responder aquí o usar los botones.'); arm();
  }
  function askClear() {
    stage = 'clear'; $('#guest-resolution').hidden = false;
    $('#guest-question').textContent = '¿Confirmas que borremos el chat y el QR para atender a otra persona?';
    $('#guest-yes').textContent = 'Sí, limpiar atención'; $('#guest-no').textContent = 'Seguir consultando';
    say('¿Confirmas que borremos el chat y el QR? Si no respondes, se limpiarán automáticamente en un minuto.'); arm();
    touch();
  }
  function moreHelp() {
    stage = ''; $('#guest-resolution').hidden = true; say('Claro. Cuéntame qué falta por resolver.'); arm(); touch(); input.focus();
  }
  async function touch() {
    if (!token || !visible) return;
    const g = generation;
    try { await request('/session/activity', {method: 'POST'}); }
    catch (error) { if (current(g) && error.status === 404) reset(); }
  }
  function failure(error, g) {
    if (!current(g)) return;
    if (error.status === 404) { reset('La atención venció y se limpió. Puedes comenzar de nuevo.'); return; }
    say(error.message || 'No se pudo conectar. Inténtalo nuevamente.'); askResolved();
  }
  async function showNetworks() {
    checkExpiry(); if (busy) return;
    const g = generation; setBusy(true); arm();
    try {
      await ensureSession(); const networks = await request('/networks');
      if (!current(g)) return;
      $('#guest-identify-form').hidden = true; $('#guest-contact').value = '';
      $('#guest-qr').replaceChildren();
      $('#guest-network').replaceChildren(...networks.map(n => new Option(`${n.name} · ${n.ssid}`, n.id)));
      $('#guest-wifi').hidden = networks.length === 0;
      say(networks.length ? 'Selecciona la red de invitados y pulsa «Mostrar QR para conectarme».' : 'No hay una red habilitada para invitados. Pide ayuda al equipo del recinto.');
      if (networks.length) { stage = ''; $('#guest-resolution').hidden = true; arm(); } else askResolved();
    } catch (error) { failure(error, g); }
    finally { if (current(g)) setBusy(false); }
  }
  function askIdentity() {
    checkExpiry(); if (busy) return;
    $('#guest-wifi').hidden = true; $('#guest-qr').replaceChildren(); $('#guest-network').replaceChildren();
    $('#guest-contact').value = ''; $('#guest-identify-error').textContent = '';
    $('#guest-identify-form').hidden = false; stage = ''; $('#guest-resolution').hidden = true;
    say('Para recuperar tus credenciales, ingresa el correo o teléfono registrado en el formulario protegido. Solo mostraremos la red que corresponda a ese dato.');
    arm(); touch(); $('#guest-contact').focus();
  }
  $('#guest-identify-form').addEventListener('submit', async (event) => {
    event.preventDefault(); checkExpiry(); if (busy) return;
    const contact = $('#guest-contact').value.trim(); if (!contact) return;
    $('#guest-contact').value = ''; $('#guest-identify-error').textContent = '';
    $('#guest-qr').replaceChildren(); $('#guest-network').replaceChildren(); $('#guest-wifi').hidden = true;
    const g = generation; setBusy(true); arm();
    try {
      await ensureSession();
      const networks = await request('/identify', {method: 'POST', body: JSON.stringify({contact})});
      if (!current(g)) return;
      $('#guest-network').replaceChildren(...networks.map(n => new Option(`${n.name} · ${n.ssid}`, n.id)));
      $('#guest-wifi').hidden = networks.length === 0; $('#guest-identify-form').hidden = true;
      say('Encontramos tu acceso. Selecciona tu red y pulsa «Mostrar QR para conectarme».'); arm();
    } catch (error) {
      if (!current(g)) return;
      if (error.status === 404) { failure(error, g); return; }
      $('#guest-identify-error').textContent = error.message || 'No se pudo comprobar el acceso. Solicita ayuda al equipo.';
      arm();
    } finally { if (current(g)) setBusy(false); }
  });
  async function showQr() {
    checkExpiry(); if (busy || !$('#guest-network').value) return;
    const g = generation; setBusy(true); $('#guest-qr').replaceChildren(); arm();
    try {
      await ensureSession();
      const access = await request(`/networks/${Number($('#guest-network').value)}/access`, {method: 'POST'});
      if (!current(g)) return;
      const image = document.createElement('img'); image.src = access.qr_data_url;
      image.alt = `QR para conectarte a ${access.ssid}`; image.className = 'wifi-qr';
      $('#guest-qr').replaceChildren(text('strong', access.ssid), image, text('p', 'Escanea con la cámara de tu teléfono y acepta conectarte. El QR se elimina al finalizar la atención.'));
      say('Tu QR está disponible en el panel Wi-Fi.'); askResolved();
      $('#guest-qr').scrollIntoView?.({behavior: 'smooth', block: 'center'});
    } catch (error) { failure(error, g); }
    finally { if (current(g)) setBusy(false); }
  }
  $('#guest-form').addEventListener('submit', async (event) => {
    event.preventDefault(); checkExpiry(); if (busy) return;
    const message = input.value.trim(); if (!message) return; input.value = '';
    // El dato de recuperación va únicamente a /identify, nunca al log ni al LLM.
    if (/[^\s@]+@[^\s@]+|(?:\+|00)?[0-9][0-9 ()-]{7,}[0-9]/.test(message)) { askIdentity(); return; }
    say(message, 'user');
    const choice = message.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[.!¡¿?]/g, '').trim();
    if (stage && /^(si|si gracias|resuelto|listo|confirmo|confirmar|limpiar|borrar)$/.test(choice)) {
      if (stage === 'clear') reset('Atención finalizada. Hola, ¿en qué puedo ayudarte?'); else askClear(); return;
    }
    if (stage && /^(no|no gracias|seguir|continuar)$/.test(choice)) { moreHelp(); return; }
    stage = ''; $('#guest-resolution').hidden = true;
    if (/wi[ -]?fi|credencial|contrase[nñ]a|codigo qr|código qr|\bqr\b/i.test(message)) { askIdentity(); return; }
    const g = generation; setBusy(true); arm();
    try {
      await ensureSession(); const response = await request('/messages', {method: 'POST', body: JSON.stringify({message})});
      if (!current(g)) return;
      say(response.answer); askResolved();
    } catch (error) { failure(error, g); }
    finally { if (current(g)) setBusy(false); }
  });
  $('#guest-yes').addEventListener('click', () => {
    checkExpiry(); if (stage === 'clear') reset('Atención finalizada. Hola, ¿en qué puedo ayudarte?'); else if (stage === 'resolved') askClear();
  });
  $('#guest-no').addEventListener('click', () => { checkExpiry(); if (stage) moreHelp(); });
  $('#guest-finish').addEventListener('click', () => { checkExpiry(); askClear(); });
  $('#guest-wifi-button').addEventListener('click', askIdentity);
  $('#guest-portal-button').addEventListener('click', showNetworks);
  $('#guest-show-qr').addEventListener('click', showQr);
  $('#guest-network').addEventListener('change', () => { checkExpiry(); $('#guest-qr').replaceChildren(); arm(); touch(); });
  input.addEventListener('input', () => {
    checkExpiry(); arm();
    if (now() - lastActivity >= 15000) { lastActivity = now(); touch(); }
  });
  $('#guest-contact').addEventListener('input', () => {
    checkExpiry(); arm();
    if (now() - lastActivity >= 15000) { lastActivity = now(); touch(); }
  });
  function start() { visible = true; screen.hidden = false; $('#login-screen').style.display = 'none'; reset(); }
  function stop() { visible = false; reset(); screen.hidden = true; }
  $('#guest-login').addEventListener('click', () => { stop(); $('#login-screen').style.display = ''; $('#email').focus(); });
  $('#guest-back').addEventListener('click', start);
  window.addEventListener?.('pagehide', () => reset());
  window.addEventListener?.('pageshow', checkExpiry);
  document.addEventListener?.('visibilitychange', checkExpiry);
  return {start, stop, reset, checkExpiry};
}
