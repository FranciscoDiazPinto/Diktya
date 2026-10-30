import { canReserveVlans, reservationPayload } from '../chat-reservations.mjs';

export function createReservations({ document, state, api, chatMessages, textNode, showToast }) {
  const { authedRequest } = api;
  const reservationList = document.querySelector('#vlan-reservations');
  function configureUser(user) {
    reservationList.hidden = !canReserveVlans(user.roles || []);
    if (!reservationList.hidden) refreshReservations();
  }
  function reset() { reservationList.replaceChildren(); reservationList.hidden = true; }
  function renderReservationProposal(proposal) {
    const session = state.session;
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
      if (session !== state.session) return;
      confirm.disabled = cancel.disabled = true;
      try {
        await authedRequest('/api/v1/changes/vlan-reservations', {
          method: 'POST', body: JSON.stringify(reservationPayload(proposal)),
        });
        if (session !== state.session) return;
        card.replaceChildren(textNode('p', 'Reserva confirmada.'));
        await refreshReservations();
      } catch (error) {
        if (session !== state.session) return;
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
    const session = state.session;
    if (!canReserveVlans(state.user?.roles || [])) return;
    try {
      const rows = await authedRequest('/api/v1/changes/vlan-reservations', {});
      if (session !== state.session) return;
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
          if (session !== state.session) return;
          release.disabled = true;
          try {
            await authedRequest(`/api/v1/changes/vlan-reservations/${row.id}/release`, { method: 'POST' });
            if (session !== state.session) return;
            await refreshReservations();
          } catch (error) {
            if (session !== state.session) return;
            release.disabled = false;
            showToast(error.message);
          }
        });
        item.append(release);
        reservationList.append(item);
      }
    } catch (error) {
      if (session !== state.session) return;
      reservationList.replaceChildren(textNode('p', `No se pudieron cargar las reservas: ${error.message}`));
    }
  }


  return { configureUser, reset, renderReservationProposal, refresh: refreshReservations };
}
