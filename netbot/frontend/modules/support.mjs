
export function createSupport({ document, window, Option, state, api, chatMessages, textNode, clockTime, captureChat, isChatCurrent }) {
  const $ = (selector) => document.querySelector(selector);
  const { authedRequest } = api;
  const supportPanel = $('#support-panel'), supportNetworkSelect = $('#support-network');
  const supportResult = $('#support-result'), wifiAccessPanel = $('#wifi-access-panel');
  let supportGeneration = 0;
  function reset() {
    clearWifiAccess(); supportNetworkSelect.replaceChildren(new Option('Selecciona una red', ''));
    supportResult.textContent = '';
  }
  function configureUser(user) {
    supportPanel.hidden = !user.permissions?.includes('networks:read:own');
    $('#support-access').hidden = !user.permissions?.includes('wifi:access:read:own');
  }
  function setNetworks(networks) {
    supportNetworkSelect.replaceChildren(new Option('Selecciona una red', ''), ...networks.map((n) => new Option(`${n.name} · ${n.ssid}`, n.id)));
  }
  function clearWifiAccess() {
    supportGeneration += 1;
    wifiAccessPanel.replaceChildren();
    wifiAccessPanel.hidden = true;
  }

  supportNetworkSelect.addEventListener('change', () => {
    clearWifiAccess();
    supportResult.textContent = '';
  });

  async function showWifiAccess(networkId) {
    if (!networkId) { supportResult.textContent = 'Selecciona una red autorizada.'; return; }
    clearWifiAccess();
    const session = state.session;
    const generation = supportGeneration;
    supportResult.textContent = 'Consultando el acceso…';
    try {
      const access = await authedRequest(`/api/v1/networks/${networkId}/access`, { method: 'POST', cache: 'no-store' });
      if (session !== state.session || generation !== supportGeneration) return;
      supportNetworkSelect.value = String(networkId);
      wifiAccessPanel.replaceChildren(textNode('strong', `SSID: ${access.ssid}`), textNode('p', `Seguridad: ${access.security}`));
      wifiAccessPanel.append(textNode('p', access.passphrase === null ? 'Red abierta, sin contraseña.' : access.passphrase, 'wifi-passphrase'));
      wifiAccessPanel.append(textNode('p', 'Este acceso se oculta en un minuto y no se guarda en el historial.'));
      const hide = textNode('button', 'Ocultar acceso');
      hide.type = 'button';
      hide.addEventListener('click', clearWifiAccess);
      wifiAccessPanel.append(hide);
      wifiAccessPanel.hidden = false;
      supportResult.textContent = 'Acceso disponible en el panel protegido.';
      window.setTimeout(() => {
        if (session === state.session && generation === supportGeneration) clearWifiAccess();
      }, 60000);
    } catch (error) {
      if (session === state.session && generation === supportGeneration) supportResult.textContent = error.message;
    }
  }

  $('#support-access').addEventListener('click', () => showWifiAccess(Number(supportNetworkSelect.value)));
  $('#support-status').addEventListener('click', async () => {
    const networkId = Number(supportNetworkSelect.value);
    if (!networkId) { supportResult.textContent = 'Selecciona una red autorizada.'; return; }
    const session = state.session;
    clearWifiAccess();
    const generation = supportGeneration;
    supportResult.textContent = 'Comprobando tu red…';
    try {
      const status = await authedRequest(`/api/v1/networks/${networkId}/status`);
      if (session !== state.session || generation !== supportGeneration) return;
      supportResult.textContent = `${status.simulated ? 'DEMOSTRACIÓN · ' : ''}${status.summary}\nFuente: ${status.source}. Comprobado: ${clockTime(status.checked_at)}.`;
    } catch (error) {
      if (session === state.session && generation === supportGeneration) supportResult.textContent = error.message;
    }
  });

  function renderAccessAction(action) {
    const session = state.session;
    const context = captureChat();
    const card = document.createElement('article');
    card.className = 'reservation-card';
    card.append(textNode('p', `Acceso Wi-Fi para ${action.ssid}`));
    const button = textNode('button', 'Ver acceso protegido');
    button.type = 'button';
    button.addEventListener('click', () => {
      if (!isChatCurrent(context)) return;
      showWifiAccess(action.network_id);
      supportPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    card.append(button);
    chatMessages.append(card);
  }


  return { configureUser, reset, clearWifiAccess, showWifiAccess, renderAccessAction, setNetworks, selectedNetworkId: () => Number(supportNetworkSelect.value) };
}
