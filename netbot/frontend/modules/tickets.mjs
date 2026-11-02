
export function createTickets({ document, Option, crypto, state, api, chatMessages, textNode, selectedNetworkId, captureChat, isChatCurrent }) {
  const $ = (selector) => document.querySelector(selector);
  const { authedRequest } = api;
  const ticketForm = $('#ticket-form'), ticketFeedback = $('#ticket-feedback');
  const ticketsPanel = $('#tickets-panel'), ticketsList = $('#tickets-list');
  let ticketsGeneration = 0, ticketRequest = null, manualRequest = null;
  const STATUS_LABELS = { open: 'Abierto', in_progress: 'En progreso', resolved: 'Resuelto', closed: 'Cerrado' };
  const CRITICALITY_LABELS = { baja: 'Baja', media: 'Media', alta: 'Alta', critica: 'Crítica' };
  const CRITICALITY_TONE = { baja: 'off', media: 'warn', alta: 'block', critica: 'block' };
  const canManage = () => state.user.permissions.some((p) => ['tickets:manage', 'tickets:manage:assigned'].includes(p));
  function reset() {
    ticketsGeneration += 1; ticketFeedback.textContent = ''; $('#ticket-submit').disabled = false;
    ticketsList.replaceChildren(); ticketForm.reset(); ticketRequest = null; manualRequest = null;
    $('#manual-feedback').textContent = '';
  }
  function configureUser(user) {
    ticketForm.hidden = !user.permissions?.includes('tickets:create:own');
    const canRead = user.permissions?.some((p) => ['tickets:read:own', 'tickets:read:assigned', 'tickets:read', 'monitoring:read'].includes(p));
    ticketsPanel.hidden = $('#tickets-nav').hidden = !canRead;
    $('#ticket-manual-form').hidden = !user.permissions?.some((p) => ['tickets:manage', 'tickets:manage:assigned'].includes(p));
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

  $('#ticket-manual-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const proposal = { summary: $('#manual-summary').value.trim(), description: $('#manual-description').value.trim(), criticality: $('#manual-criticality').value };
    const signature = JSON.stringify(proposal);
    if (manualRequest?.signature !== signature) manualRequest = { signature, key: crypto.randomUUID() };
    const session = state.session;
    const button = $('#manual-submit');
    if (button.disabled) return;
    button.disabled = true;
    try {
      const ticket = await authedRequest('/api/v1/tickets/manual', { method: 'POST', body: JSON.stringify({ ...proposal, request_key: manualRequest.key }) });
      if (session !== state.session) return;
      $('#manual-feedback').textContent = `Ticket #${ticket.id} creado.`;
      $('#ticket-manual-form').reset();
      manualRequest = null;
      refreshTickets();
    } catch (error) {
      if (session === state.session) $('#manual-feedback').textContent = error.message;
    } finally {
      if (session === state.session) button.disabled = false;
    }
  });

  function managementControls(ticket, session, generation) {
    const box = document.createElement('div');
    box.className = 'ticket-meta';
    const feedback = textNode('p', '');
    const guarded = async (call) => {
      if (session !== state.session || generation !== ticketsGeneration) return;
      try { await call(); if (session === state.session) refreshTickets(); }
      catch (error) { if (session === state.session) feedback.textContent = error.message; }
    };
    if (ticket.status !== 'closed' && ticket.assignee_id !== state.user.id) {
      const take = textNode('button', 'Asignármelo');
      take.type = 'button';
      take.addEventListener('click', () => guarded(() => authedRequest(`/api/v1/tickets/${ticket.id}/assign`, { method: 'POST', body: JSON.stringify({ version: ticket.version }) })));
      box.append(take);
    }
    const level = document.createElement('select');
    level.setAttribute('aria-label', 'Ajustar criticidad');
    level.append(...Object.entries(CRITICALITY_LABELS).map(([value, label]) => new Option(label, value)));
    level.value = ticket.criticality;
    const reason = document.createElement('input');
    reason.placeholder = 'Motivo o comentario';
    reason.setAttribute('aria-label', 'Motivo o comentario');
    reason.maxLength = 1000;
    const adjust = textNode('button', 'Ajustar criticidad');
    adjust.type = 'button';
    adjust.addEventListener('click', () => { if (!reason.value.trim()) { feedback.textContent = 'Indica el motivo del ajuste.'; return; } guarded(() => authedRequest(`/api/v1/tickets/${ticket.id}/criticality`, { method: 'PATCH', body: JSON.stringify({ criticality: level.value, version: ticket.version, note: reason.value }) })); });
    const comment = textNode('button', 'Comentar');
    comment.type = 'button';
    comment.addEventListener('click', () => { if (!reason.value.trim()) { feedback.textContent = 'Escribe un comentario.'; return; } guarded(() => authedRequest(`/api/v1/tickets/${ticket.id}/comments`, { method: 'POST', body: JSON.stringify({ note: reason.value }) })); });
    box.append(level, reason, adjust, comment, feedback);
    return box;
  }

  function ticketOrigin(ticket) {
    if (ticket.source === 'incident') return `Incidente automático${ticket.evidence?.simulated ? ' · DEMOSTRACIÓN' : ''}`;
    if (ticket.network_id == null) return 'Infraestructura';
    return `Red #${ticket.network_id}`;
  }

  async function refreshTickets() {
    const session = state.session;
    const generation = ++ticketsGeneration;
    const params = new URLSearchParams();
    if ($('#tickets-status').value) params.set('status', $('#tickets-status').value);
    if ($('#tickets-criticality').value) params.set('criticality', $('#tickets-criticality').value);
    if ($('#tickets-mine').checked) params.set('assignee_id', String(state.user.id));
    try {
      const query = params.toString();
      const rows = await authedRequest(`/api/v1/tickets${query ? `?${query}` : ''}`);
      if (session !== state.session || generation !== ticketsGeneration) return;
      ticketsList.replaceChildren();
      if (!rows.length) ticketsList.append(textNode('p', 'No hay tickets disponibles.'));
      for (const ticket of rows) {
        const card = document.createElement('article');
        card.className = `reservation-card${['alta', 'critica'].includes(ticket.criticality) ? ' is-urgent' : ''}`;
        card.id = `ticket-${ticket.id}`;
        const meta = document.createElement('div');
        meta.className = 'ticket-meta';
        meta.append(textNode('span', CRITICALITY_LABELS[ticket.criticality], `pill ${CRITICALITY_TONE[ticket.criticality]}`), textNode('span', STATUS_LABELS[ticket.status], 'pill off'));
        if (ticket.needs_review) meta.append(textNode('span', 'Requiere revisión', 'pill warn'));
        card.append(textNode('h3', `#${ticket.id} · ${ticket.summary}`), meta, textNode('p', ticketOrigin(ticket)), textNode('p', ticket.description));
        if (ticket.device_name) card.append(textNode('p', `Dispositivo: ${ticket.device_name}`));
        if (ticket.evidence) card.append(textNode('p', `Evidencia: alerta #${ticket.evidence.alert_id ?? '–'} de ${ticket.evidence.source}, detectada ${new Date(ticket.evidence.detected_at).toLocaleString('es-CL')}`));
        if (ticket.resolution) card.append(textNode('p', `Resolución: ${ticket.resolution}`));
        if (ticket.escalations) card.append(textNode('p', `Escalado ${ticket.escalations} vez/veces por falta de atención`));
        if (ticket.network_snapshot) card.append(textNode('p', `Comprobación al crear el ticket (${new Date(ticket.network_snapshot.checked_at).toLocaleString('es-CL')}): ${ticket.network_snapshot.simulated ? 'DEMOSTRACIÓN · ' : ''}${ticket.network_snapshot.summary}`));
        const detail = textNode('button', 'Ver seguimiento');
        detail.type = 'button';
        const history = document.createElement('div');
        detail.addEventListener('click', async () => {
          if (session !== state.session || generation !== ticketsGeneration) return;
          try {
            const data = await authedRequest(`/api/v1/tickets/${ticket.id}`);
            if (session !== state.session || generation !== ticketsGeneration) return;
            history.replaceChildren(...data.events.map((e) => textNode('p', `${new Date(e.created_at).toLocaleString('es-CL')} · ${STATUS_LABELS[e.status]} · ${e.note}`)));
          } catch (error) { if (session === state.session && generation === ticketsGeneration) history.textContent = error.message; }
        });
        card.append(detail, history);
        if (canManage()) {
          card.append(managementControls(ticket, session, generation));
          const form = document.createElement('form');
          form.className = 'ticket-update';
          const select = document.createElement('select');
          select.setAttribute('aria-label', 'Nuevo estado del ticket');
          const transitions = { open: ['in_progress', 'resolved'], in_progress: ['open', 'resolved'], resolved: ['in_progress', 'closed'], closed: ['open'] };
          select.append(...transitions[ticket.status].map((value) => new Option(STATUS_LABELS[value], value)));
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
  ['#tickets-status', '#tickets-criticality', '#tickets-mine'].forEach((selector) => $(selector).addEventListener('change', refreshTickets));


  return { configureUser, reset, renderTicketProposal, refreshTickets };
}
