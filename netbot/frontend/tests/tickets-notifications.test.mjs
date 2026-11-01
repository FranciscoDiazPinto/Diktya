import test from 'node:test';
import assert from 'node:assert/strict';
import { createTickets } from '../modules/tickets.mjs';
import { createNotifications } from '../modules/notifications.mjs';

class Element {
  constructor(text = '', value = '') { this.textContent = text; this.value = value; this.children = []; this.events = {}; this.hidden = false; this.checked = false; this.attributes = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(event, handler) { this.events[event] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  reset() {}
}
const text = (node) => [node.textContent, ...node.children.map(text)].join(' ');
const find = (node, label) => (node.textContent === label ? node : node.children.map((child) => find(child, label)).find(Boolean));
const ticket = { id: 5, network_id: null, summary: '<b>AP Hall</b> caído', description: 'Fuera de línea', status: 'open', version: 2, criticality: 'critica', needs_review: true, source: 'incident', device_name: 'AP Hall', evidence: { alert_id: 9, source: 'unifi', detected_at: '2026-11-01T12:00:00Z', simulated: false }, network_snapshot: null, assignee_id: null, escalations: 1, resolution: null };
function setup(permissions, responder = async () => [ticket]) {
  const nodes = new Map(); const calls = [];
  const document = { querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); }, createElement: () => new Element() };
  const state = { session: 1, user: { id: 3, permissions } };
  const api = { authedRequest: async (path, options) => { calls.push({ path, options }); return responder(path, options); } };
  const textNode = (tag, value, className) => { const element = new Element(value == null ? '' : String(value)); element.className = className; return element; };
  const controller = createTickets({ document, Option: Element, crypto: { randomUUID: () => 'uuid-1' }, state, api, chatMessages: new Element(), textNode, selectedNetworkId: () => 1, captureChat: () => ({}), isChatCurrent: () => true });
  return { nodes, calls, state, controller, $: (selector) => document.querySelector(selector), textNode, document, api };
}

test('un ticket de incidente sin red muestra criticidad, equipo y evidencia', async () => {
  const ui = setup(['tickets:manage:assigned', 'tickets:read:assigned']);
  await ui.controller.refreshTickets();
  const card = ui.$('#tickets-list').children[0];
  const body = text(card);
  for (const expected of ['Crítica', 'Requiere revisión', 'Incidente automático', 'AP Hall', 'alerta #9']) assert.ok(body.includes(expected), expected);
  assert.equal(card.id, 'ticket-5');
  assert.ok(card.className.includes('is-urgent'));
  assert.equal(card.children.find((node) => node.textContent?.startsWith('#5')).textContent, `#5 · ${ticket.summary}`);
});

test('quien gestiona puede asignarse, comentar y ajustar con la versión vigente', async () => {
  const ui = setup(['tickets:manage:assigned']);
  await ui.controller.refreshTickets();
  const card = ui.$('#tickets-list').children[0];
  await find(card, 'Asignármelo').events.click();
  const assign = ui.calls.find(({ path }) => path.endsWith('/assign'));
  assert.deepEqual(JSON.parse(assign.options.body), { version: 2 });
  find(card, 'Comentar').events.click();
  assert.ok(text(card).includes('Escribe un comentario.'));
  assert.equal(ui.calls.some(({ path }) => path.endsWith('/comments')), false);
});

test('el supervisor ve el ticket sin controles de gestión', async () => {
  const ui = setup(['monitoring:read']);
  ui.controller.configureUser({ permissions: ['monitoring:read'] });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ui.$('#tickets-panel').hidden, false);
  assert.equal(ui.$('#ticket-manual-form').hidden, true);
  const card = ui.$('#tickets-list').children[0];
  assert.equal(find(card, 'Asignármelo'), undefined);
  assert.equal(find(card, 'Actualizar estado'), undefined);
});

test('los filtros viajan a la API', async () => {
  const ui = setup(['tickets:read:assigned']);
  ui.$('#tickets-status').value = 'open'; ui.$('#tickets-criticality').value = 'alta'; ui.$('#tickets-mine').checked = true;
  await ui.controller.refreshTickets();
  const path = ui.calls.at(-1).path;
  for (const expected of ['status=open', 'criticality=alta', 'assignee_id=3']) assert.ok(path.includes(expected), expected);
});

test('un ticket de cliente conserva su comprobación de red', async () => {
  const ui = setup(['tickets:read:own'], async () => [{ ...ticket, network_id: 1, source: 'customer', criticality: 'media', needs_review: false, device_name: null, evidence: null, escalations: 0, network_snapshot: { checked_at: '2026-11-01T12:00:00Z', simulated: true, summary: 'Interfaz activa' } }]);
  await ui.controller.refreshTickets();
  const body = text(ui.$('#tickets-list').children[0]);
  assert.ok(body.includes('Red #1') && body.includes('DEMOSTRACIÓN'));
});

function inbox(permissions, responder) {
  const nodes = new Map(); const state = { session: 1 }; const calls = [];
  const document = { querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); }, createElement: () => new Element() };
  const window = { setInterval: () => 1, clearInterval() {} };
  const api = { authedRequest: async (path, options) => { calls.push({ path, options }); return responder(path); } };
  const controller = createNotifications({ document, window, state, api, textNode: (tag, value, className) => { const element = new Element(value ?? ''); element.className = className; return element; } });
  return { controller, $: (selector) => document.querySelector(selector), state, calls, permissions };
}
const page = { unread: 1, items: [{ id: 8, ticket_id: 5, title: '[Crítica] Nuevo ticket', highlighted: true, created_at: '2026-11-01T12:00:00Z', read_at: null, link: 'https://evil.test' }] };

test('la bandeja destaca lo urgente, enlaza internamente y marca como leída', async () => {
  const ui = inbox([], async () => page);
  await ui.controller.configureUser({ permissions: ['tickets:manage:assigned'] });
  assert.equal(ui.$('#notifications-count').textContent, '1');
  const card = ui.$('#notifications-list').children[0];
  assert.ok(card.className.includes('is-urgent') && card.className.includes('is-unread'));
  assert.equal(card.children[0].href, '#ticket-5');
  await find(card, 'Marcar como leída').events.click();
  assert.ok(ui.calls.some(({ path, options }) => path.endsWith('/8/read') && options.method === 'POST'));
});

test('sin gestión de tickets no consulta la bandeja', async () => {
  const ui = inbox([], async () => page);
  await ui.controller.configureUser({ permissions: ['tickets:read:own'] });
  assert.equal(ui.calls.length, 0);
  assert.equal(ui.$('#notifications-button').hidden, true);
});

test('una bandeja tardía de otra sesión se descarta', async () => {
  let release; const gate = new Promise((resolve) => { release = resolve; });
  const ui = inbox([], async () => { await gate; return page; });
  const pending = ui.controller.configureUser({ permissions: ['tickets:manage'] });
  ui.state.session += 1;
  release(); await pending;
  assert.equal(ui.$('#notifications-count').children.length, 0);
  assert.notEqual(ui.$('#notifications-count').textContent, '1');
});
