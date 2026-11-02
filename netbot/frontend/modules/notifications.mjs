// Bandeja del equipo técnico. Solo muestra las notificaciones propias del usuario.
const POLL_MS = 20000;

export function createNotifications({ document, window, state, api, textNode, onOpenTicket = null }) {
  const $ = (selector) => document.querySelector(selector);
  const button = $('#notifications-button'), panel = $('#notifications-panel');
  const count = $('#notifications-count'), list = $('#notifications-list');
  let timer = null, generation = 0;

  function reset() {
    if (timer) window.clearInterval(timer);
    timer = null; generation += 1;
    button.hidden = true; panel.hidden = true; list.replaceChildren(); count.textContent = '0';
  }

  function configureUser(user) {
    const staff = user.permissions?.some((p) => ['tickets:manage', 'tickets:manage:assigned'].includes(p));
    button.hidden = !staff;
    if (!staff) return Promise.resolve();
    timer = window.setInterval(refresh, POLL_MS);
    return refresh();
  }

  function item(notification) {
    const unread = !notification.read_at;
    const card = document.createElement('article');
    card.className = `reservation-card notification-item${notification.highlighted ? ' is-urgent' : ''}${unread ? ' is-unread' : ''}`;
    const link = textNode('a', notification.title);
    link.href = `#ticket-${notification.ticket_id}`; // ancla interna: no se usa una URL recibida
    link.addEventListener('click', (event) => {
      if (onOpenTicket) { event.preventDefault(); onOpenTicket(notification.ticket_id); }
    });
    card.append(link, textNode('p', new Date(notification.created_at).toLocaleString('es-CL')));
    if (unread) {
      const mark = textNode('button', 'Marcar como leída');
      mark.type = 'button';
      mark.addEventListener('click', async () => {
        const session = state.session;
        try {
          await api.authedRequest(`/api/v1/notifications/${notification.id}/read`, { method: 'POST' });
          if (session === state.session) await refresh();
        } catch (error) { if (session === state.session) card.append(textNode('p', error.message)); }
      });
      card.append(mark);
    }
    return card;
  }

  async function refresh() {
    const session = state.session;
    const current = ++generation;
    try {
      const page = await api.authedRequest('/api/v1/notifications');
      if (session !== state.session || current !== generation) return;
      count.textContent = String(page.unread);
      list.replaceChildren(...(page.items.length ? page.items.map(item) : [textNode('p', 'Sin notificaciones.', 'empty-state')]));
    } catch (error) {
      if (session === state.session && current === generation && error.status !== 401) list.replaceChildren(textNode('p', 'No se pudieron cargar las notificaciones. Reintentando…'));
    }
  }

  button.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    button.setAttribute('aria-expanded', String(!panel.hidden));
  });

  return { configureUser, reset, refresh };
}
