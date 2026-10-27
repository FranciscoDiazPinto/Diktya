
export function createTickets({ document, Option, crypto, state, api, chatMessages, textNode, selectedNetworkId, captureChat, isChatCurrent }) {
  const $ = (selector) => document.querySelector(selector);
  const { authedRequest } = api;
  const ticketForm = $('#ticket-form'), ticketFeedback = $('#ticket-feedback');
  const ticketsPanel = $('#tickets-panel'), ticketsList = $('#tickets-list');
  let ticketsGeneration = 0, ticketRequest = null;
  function reset() {
    ticketsGeneration += 1; ticketFeedback.textContent = ''; $('#ticket-submit').disabled = false;
    ticketsList.replaceChildren(); ticketForm.reset(); ticketRequest = null;
  }
  function configureUser(user) {
    ticketForm.hidden = !user.permissions?.includes('tickets:create:own');
    const canRead = user.permissions?.some((p) => ['tickets:read:own', 'tickets:read:assigned', 'tickets:read'].includes(p));
    ticketsPanel.hidden = $('#tickets-nav').hidden = !canRead;
    if (canRead) refreshTickets();
  }
  function renderTicketProposal(proposal) {
    const session = state.session;
    const context = captureChat();
    const requestKey = crypto.randomUUID();
    const card = document.createElement('article');
    card.className = 'reservation-card';
    card.append(textNode('h3', 'Propuesta de ticket'), textNode('p', proposal.summary), textNode('p', proposal.description));
    const feedback = textNode('p', 'Confirma para guardar y enviar esta solicitud al soporte técnico.');
    const confirm = textNode('button', 'Crear ticket');
    const cancel = textNode('button', 'Cancelar');
    confirm.type = cancel.type = 'button';
    cancel.addEventListener('click', () => card.remove());
    confirm.addEventListener('click', async () => {
      if (!isChatCurrent(context)) return;
      confirm.disabled = cancel.disabled = true;
      try {
        const ticket = await authedRequest('/api/v1/tickets', {
          method: 'POST', body: JSON.stringify({ ...proposal, request_key: requestKey }),
        });
        if (!isChatCurrent(context)) return;
        card.replaceChildren(textNode('p', `Ticket #${ticket.id} creado. Estado: ${ticket.status}.`));
        refreshTickets();
      } catch (error) {
        if (!isChatCurrent(context)) return;
        feedback.textContent = error.message;
        confirm.disabled = cancel.disabled = false;
      }
    });
    card.append(feedback, confirm, cancel);
    chatMessages.append(card);
  }

  ticketForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const networkId = selectedNetworkId();
    if (!networkId) { ticketFeedback.textContent = 'Selecciona la red que necesita ayuda.'; return; }
    const proposal = { network_id: networkId, summary: $('#ticket-summary').value.trim(), description: $('#ticket-description').value.trim() };
    const signature = JSON.stringify(proposal);
    if (ticketRequest?.signature !== signature) ticketRequest = { signature, key: crypto.randomUUID() };
    const session = state.session;
    const button = $('#ticket-submit');
    if (button.disabled) return;
    button.disabled = true;
    ticketFeedback.textContent = 'Guardando solicitud…';
    try {
      const ticket = await authedRequest('/api/v1/tickets', {
        method: 'POST', body: JSON.stringify({ ...proposal, request_key: ticketRequest.key }),
      });
      if (session !== state.session) return;
      ticketFeedback.textContent = `Ticket #${ticket.id} creado. Puedes seguirlo en Tickets.`;
      if ($('#ticket-summary').value.trim() === proposal.summary && $('#ticket-description').value.trim() === proposal.description) ticketForm.reset();
      ticketRequest = null;
      refreshTickets();
    } catch (error) {
      if (session === state.session) ticketFeedback.textContent = error.message;
    } finally {
      if (session === state.session) button.disabled = false;
    }
  });

  async function refreshTickets() {
    const session = state.session;
    const generation = ++ticketsGeneration;
    try {
      const rows = await authedRequest('/api/v1/tickets');
      if (session !== state.session || generation !== ticketsGeneration) return;
      ticketsList.replaceChildren();
      if (!rows.length) ticketsList.append(textNode('p', 'No hay tickets disponibles.'));
      for (const ticket of rows) {
        const card = document.createElement('article');
        card.className = 'reservation-card';
        card.append(textNode('h3', `#${ticket.id} · ${ticket.summary}`), textNode('p', `Red #${ticket.network_id} · ${ticket.status}`), textNode('p', ticket.description));
        card.append(textNode('p', `Comprobación al crear el ticket (${new Date(ticket.network_snapshot.checked_at).toLocaleString('es-CL')}): ${ticket.network_snapshot.simulated ? 'DEMOSTRACIÓN · ' : ''}${ticket.network_snapshot.summary}`));
        const detail = textNode('button', 'Ver seguimiento');
        detail.type = 'button';
        const history = document.createElement('div');
        detail.addEventListener('click', async () => {
          if (session !== state.session || generation !== ticketsGeneration) return;
          try {
            const data = await authedRequest(`/api/v1/tickets/${ticket.id}`);
            if (session !== state.session || generation !== ticketsGeneration) return;
            history.replaceChildren(...data.events.map((e) => textNode('p', `${new Date(e.created_at).toLocaleString('es-CL')} · ${e.status} · ${e.note}`)));
          } catch (error) { if (session === state.session && generation === ticketsGeneration) history.textContent = error.message; }
        });
        card.append(detail, history);
        if (state.user.permissions.some((p) => ['tickets:manage', 'tickets:manage:assigned'].includes(p))) {
          const form = document.createElement('form');
          form.className = 'ticket-update';
          const select = document.createElement('select');
          select.setAttribute('aria-label', 'Nuevo estado del ticket');
          const transitions = { open: ['in_progress', 'resolved'], in_progress: ['open', 'resolved'], resolved: ['in_progress', 'closed'], closed: ['open'] };
          select.append(...transitions[ticket.status].map((value) => new Option(value, value)));
          const note = document.createElement('input');
          note.placeholder = 'Nota visible para el cliente, sin contraseñas';
          note.setAttribute('aria-label', 'Nota de seguimiento');
          note.required = true;
          note.maxLength = 1000;
          const submit = textNode('button', 'Actualizar estado');
          submit.type = 'submit';
          const feedback = textNode('p', '');
          form.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (session !== state.session || generation !== ticketsGeneration) return;
            submit.disabled = true;
            try {
              await authedRequest(`/api/v1/tickets/${ticket.id}`, { method: 'PATCH', body: JSON.stringify({ status: select.value, version: ticket.version, note: note.value }) });
              if (session === state.session) refreshTickets();
            } catch (error) { if (session === state.session) { feedback.textContent = error.message; submit.disabled = false; } }
          });
          form.append(select, note, submit, feedback);
          card.append(form);
        }
        ticketsList.append(card);
      }
    } catch (error) {
      if (session === state.session && generation === ticketsGeneration) ticketsList.replaceChildren(textNode('p', error.message));
    }
  }

  $('#tickets-refresh').addEventListener('click', refreshTickets);


  return { configureUser, reset, renderTicketProposal, refreshTickets };
}
