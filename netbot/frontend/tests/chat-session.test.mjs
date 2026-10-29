import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';
import { createDashboard } from '../modules/dashboard.mjs';

// Ejecuta el controlador real sin dependencias de navegador. Los nodos se crean
// a partir de los IDs del HTML para detectar también selectores que no existen.
class Element {
  constructor(text = '', value = '') {
    this.textContent = text;
    this.value = String(value);
    this.children = [];
    this.events = {};
    this.className = '';
    this.style = {};
    this.firstChild = { textContent: '' };
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  addEventListener(name, handler) { this.events[name] = handler; }
  append(...nodes) { for (const node of nodes) node.parent = this; this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((node) => node !== this); }
  querySelector(selector) { return this.children.find((c) => c.className?.split(' ').includes(selector.slice(1))) || null; }
  focus() {}
  reset() {}
  setAttribute() {}
  scrollIntoView() {}
}

const user = (id) => ({ id, email: `${id}@example.com`, roles: ['cliente'], permissions: ['chat:use', 'networks:read:own'] });
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
};
const tick = () => new Promise((r) => setImmediate(r));

function dashboard(fetch) {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map((m) => [`#${m[1]}`, new Element()]));
  for (const selector of ['.mobile-menu', '.sidebar']) nodes.set(selector, new Element());
  const storage = new Map();
  const timers = [];
  const monitoringNodes = [new Element(), new Element()];
  const environment = {
    document: {
      querySelector(selector) { assert.ok(nodes.has(selector), `Missing HTML selector ${selector}`); return nodes.get(selector); },
      querySelectorAll(selector) { return selector.startsWith('.stats-grid,') ? monitoringNodes : []; },
      createElement() { return new Element(); },
    },
    Option: Element,
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    window: { setInterval() {}, clearInterval() {}, setTimeout(callback, delay) { timers.push({ callback, delay }); } },
    crypto: { randomUUID }, FormData: class {}, fetch,
  };
  const controller = createDashboard(environment);
  const exposed = {
    setAuthenticated: controller.session.setAuthenticated, signOut: controller.session.signOut,
    loadConversation: controller.chat.loadConversation, startNewChat: controller.chat.startNewChat,
    refreshTokens: controller.api.refreshTokens, authedRequest: controller.api.authedRequest,
    showWifiAccess: controller.support.showWifiAccess, renderTicketProposal: controller.tickets.renderTicketProposal,
  };
  Object.defineProperties(exposed, {
    conversationId: {get: () => controller.chat.conversationId},
    conversationVersion: {get: () => controller.chat.conversationVersion},
  });
  const context = vm.createContext(exposed);
  return { nodes, storage, monitoringNodes, timers, controller, run: (code) => vm.runInContext(code, context),
    login(id, permissions) { const person = user(id); if (permissions) person.permissions = permissions; controller.session.setAuthenticated(person); } };

}

test('customer login restores saved chat and sends only conversation identity and version', async () => {
  const calls = [];
  const ui = dashboard(async (url, options) => {
    const path = new URL(url).pathname;
    calls.push({ path, options });
    if (path === '/api/v1/networks') return response([{ id: 1, name: 'Red A', ssid: 'SSID-A' }]);
    if (path === '/api/v1/chat/conversations') return response([{ id: 'saved-chat', title: 'Soporte' }]);
    if (path.endsWith('/saved-chat')) return response({ id: 'saved-chat', version: 3, network_id: 1, messages: [{ id: 1, role: 'user', content: 'Consulta guardada' }] });
    if (path.endsWith('/messages')) return response({ answer: 'Respuesta nueva', version: 4 });
    throw new Error(`Unexpected endpoint ${path}`);
  });
  ui.login('a');
  await tick();
  assert.equal(ui.run('conversationId'), 'saved-chat');
  assert.equal(ui.nodes.get('#chat-messages').querySelector('.chat-message').children[0].textContent, 'Consulta guardada');
  assert.ok(ui.monitoringNodes.every((n) => n.hidden));
  assert.ok(!calls.some((c) => c.path.includes('/monitoring/')));
  ui.nodes.get('#chat-message').value = 'Nueva consulta';
  await ui.nodes.get('#chat-form').events.submit({ preventDefault() {} });
  const payload = JSON.parse(calls.find((c) => c.path.endsWith('/messages')).options.body);
  assert.deepEqual(payload, { message: 'Nueva consulta', conversation_id: 'saved-chat', version: 3 });
  assert.equal(ui.run('conversationVersion'), 4);
});

test('late response from account A never appears after account B logs in', async () => {
  const pending = deferred();
  let requested = false;
  const ui = dashboard(async (url, options) => {
    const path = new URL(url).pathname;
    if (path.endsWith('/messages')) { requested = true; return pending.promise; }
    if (path.endsWith('/conversations') && options.method === 'POST') return response({ id: 'chat-a', version: 0 });
    return response([]);
  });
  ui.login('a');
  await tick();
  ui.nodes.get('#chat-message').value = 'Privado de A';
  const submission = ui.nodes.get('#chat-form').events.submit({ preventDefault() {} });
  await tick();
  assert.ok(requested);
  ui.run('signOut()');
  ui.login('b');
  await tick();
  pending.resolve(response({ answer: 'Secreto de A', version: 1 }));
  await submission;
  assert.equal(ui.nodes.get('#chat-messages').querySelector('.chat-message'), null);
  assert.equal(ui.run('conversationId'), null);
  assert.equal(ui.nodes.get('#chat-send').disabled, false);
});

test('switching chat ignores a previous pending history response', async () => {
  const pending = deferred();
  const ui = dashboard(async (url) => {
    if (url.endsWith('/slow-chat')) return pending.promise;
    return response([]);
  });
  ui.login('a');
  await tick();
  const loading = ui.run("loadConversation('slow-chat')");
  ui.run('startNewChat()');
  pending.resolve(response({ id: 'slow-chat', version: 1, messages: [{ id: 1, role: 'assistant', content: 'Anterior' }] }));
  await loading;
  assert.equal(ui.run('conversationId'), null);
  assert.equal(ui.nodes.get('#chat-messages').querySelector('.chat-message'), null);
});

test('late token renewal cannot replace the credentials of another session', async () => {
  const pending = deferred();
  let refreshCount = 0;
  const ui = dashboard(async (url) => {
    if (url.endsWith('/auth/refresh')) { refreshCount += 1; return pending.promise; }
    return response([]);
  });
  ui.storage.set('netbot_tokens', JSON.stringify({ access_token: 'old-a', refresh_token: 'refresh-a' }));
  const refresh = ui.run('refreshTokens()');
  const rejected = assert.rejects(refresh, /sesión cambió/);
  ui.run('signOut()');
  ui.storage.set('netbot_tokens', JSON.stringify({ access_token: 'token-b', refresh_token: 'refresh-b' }));
  pending.resolve(response({ access_token: 'fresh-a', refresh_token: 'rotated-a' }));
  await rejected;
  assert.equal(refreshCount, 1);
  assert.equal(JSON.parse(ui.storage.get('netbot_tokens')).access_token, 'token-b');
});

test('simultaneous expired requests share one refresh and keep POST payload', async () => {
  let refreshCount = 0;
  const ui = dashboard(async (url, options) => {
    if (url.endsWith('/auth/refresh')) { refreshCount += 1; await tick(); return response({ access_token: 'fresh', refresh_token: 'rotated' }); }
    if (options.headers.Authorization === 'Bearer old') return response({ detail: 'expired' }, 401);
    return response({ method: options.method, body: options.body });
  });
  ui.storage.set('netbot_tokens', JSON.stringify({ access_token: 'old', refresh_token: 'refresh' }));
  const result = await ui.run("Promise.all([authedRequest('/one', {method: 'POST', body: 'payload'}), authedRequest('/two')])");
  assert.equal(refreshCount, 1);
  assert.equal(result[0].method, 'POST');
  assert.equal(result[0].body, 'payload');
});

test('conflict clears rejected context and restores controls for a new authorized chat', async () => {
  const ui = dashboard(async (url, options) => {
    if (url.endsWith('/messages')) return response({ detail: 'La conversación cambió.' }, 409);
    if (url.endsWith('/conversations') && options.method === 'POST') return response({ id: 'stale-chat', version: 0 });
    return response([]);
  });
  ui.login('a');
  await tick();
  ui.nodes.get('#chat-message').value = 'Consulta rechazada';
  await ui.nodes.get('#chat-form').events.submit({ preventDefault() {} });
  assert.equal(ui.run('conversationId'), null);
  assert.equal(ui.nodes.get('#chat-messages').querySelector('.chat-message'), null);
  for (const selector of ['#chat-send', '#chat-message', '#chat-conversation', '#chat-new']) {
    assert.equal(ui.nodes.get(selector).disabled, false, selector);
  }
});

test('Wi-Fi password is shown outside chat, never stored locally, and hidden after a minute', async () => {
  const ui = dashboard(async (url) => {
    if (url.endsWith('/access')) return response({ ssid: 'My Wi-Fi', security: 'wpa2-personal', passphrase: 'test-only-secret' });
    return response([]);
  });
  ui.login('a');
  await tick();
  await ui.run('showWifiAccess(1)');
  const panel = ui.nodes.get('#wifi-access-panel');
  assert.equal(panel.hidden, false);
  assert.ok(panel.children.some((n) => n.textContent === 'test-only-secret'));
  assert.equal(ui.nodes.get('#chat-messages').querySelector('.chat-message'), null);
  assert.ok(![...ui.storage.values()].some((value) => value.includes('test-only-secret')));
  ui.timers.find((timer) => timer.delay === 60000).callback();
  assert.equal(panel.hidden, true);
  assert.equal(panel.children.length, 0);
});

test('late Wi-Fi access response is discarded when the user changes accounts', async () => {
  const pending = deferred();
  const ui = dashboard(async (url) => url.endsWith('/access') ? pending.promise : response([]));
  ui.login('a');
  await tick();
  const revealing = ui.run('showWifiAccess(1)');
  ui.run('signOut()');
  ui.login('b');
  await tick();
  pending.resolve(response({ ssid: 'Private-A', security: 'wpa2-personal', passphrase: 'secret-of-a' }));
  await revealing;
  assert.equal(ui.nodes.get('#wifi-access-panel').hidden, true);
  assert.equal(ui.nodes.get('#wifi-access-panel').children.length, 0);
});

test('changing networks invalidates a pending credential reveal', async () => {
  const pending = deferred();
  const ui = dashboard(async (url) => url.endsWith('/access') ? pending.promise : response([]));
  ui.login('a');
  await tick();
  const revealing = ui.run('showWifiAccess(1)');
  ui.nodes.get('#support-network').events.change();
  pending.resolve(response({ ssid: 'Previous', security: 'wpa2-personal', passphrase: 'previous-secret' }));
  await revealing;
  assert.equal(ui.nodes.get('#wifi-access-panel').children.length, 0);
});

test('ticket proposals wait for confirmation and retries reuse the request key', async () => {
  const bodies = [];
  const ui = dashboard(async (url, options) => {
    if (url.endsWith('/tickets') && options.method === 'POST') {
      bodies.push(JSON.parse(options.body));
      return bodies.length === 1 ? response({ detail: 'Reintenta' }, 503) : response({ id: 42, status: 'open' });
    }
    return response([]);
  });
  ui.login('a');
  await tick();
  ui.run("renderTicketProposal({network_id: 1, summary: 'No veo mi red', description: 'Solicito ayuda'})");
  assert.equal(bodies.length, 0);
  const card = ui.nodes.get('#chat-messages').children.at(-1);
  const confirm = card.children.find((n) => n.textContent === 'Crear ticket');
  await confirm.events.click();
  assert.equal(confirm.disabled, false);
  await confirm.events.click();
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0].request_key, bodies[1].request_key);
  assert.match(card.children[0].textContent, /Ticket #42 creado/);
});

test('monitoring module still renders authorized telemetry after composition', async () => {
  const calls = [];
  const ui = dashboard(async (url) => {
    const path = new URL(url).pathname;
    calls.push(path);
    if (!path.includes('/monitoring/')) return response([]);
    const data = path.endsWith('/system') ? { hostname: 'test-firewall', uptime_seconds: 60, temperature: { available: false } }
      : path.endsWith('/stats') ? { packets_blocked: 0 } : [];
    return response({ data, source: 'mock', status: 'ok', issues: [], collected_at: new Date().toISOString() });
  });
  ui.login('internal', ['chat:use', 'monitoring:read']);
  await tick();
  assert.ok(calls.includes('/api/v1/monitoring/system'));
  assert.ok(ui.monitoringNodes.every((node) => !node.hidden));
  assert.equal(ui.nodes.get('#sys-host').textContent, 'test-firewall');
  assert.equal(ui.nodes.get('#stat-clients').textContent, 0);
  ui.controller.session.signOut();
  ui.login('customer');
  await tick();
  assert.ok(ui.monitoringNodes.every((node) => node.hidden));
});

test('two composed dashboards keep session and conversation state independent', async () => {
  const first = dashboard(async () => response([]));
  const second = dashboard(async () => response([]));
  first.login('a');
  second.login('b');
  await tick();
  first.controller.session.signOut();
  assert.equal(second.nodes.get('#chat-send').disabled, false);
  assert.equal(second.nodes.get('#user-name').textContent, 'b');
  assert.notEqual(first.controller.api, second.controller.api);
});

test('administrator maintains Wi-Fi recipients per network and logout clears contact fields', async () => {
  const calls = [];
  const ui = dashboard(async (url, options) => {
    const path = new URL(url).pathname; calls.push({path, options});
    if (path === '/api/v1/networks') return response([{id:1, name:'Cliente', ssid:'Client'}]);
    if (path.endsWith('/recipients')) return response(options.method === 'PUT' ? JSON.parse(options.body).recipients : [{email:'client@example.com', phone:'+56912345678'}]);
    return response([]);
  });
  ui.login('admin', ['networks:manage']); await tick();
  assert.equal(ui.nodes.get('#wifi-recipients-panel').hidden, false);
  const select = ui.nodes.get('#wifi-recipients-network'); select.value = '1';
  await select.events.change();
  const contacts = ui.nodes.get('#wifi-recipients-contacts');
  assert.equal(contacts.value, 'client@example.com;+56912345678');
  contacts.value = 'updated@example.com;\n;+56987654321';
  await ui.nodes.get('#wifi-recipients-form').events.submit({preventDefault() {}});
  const saved = calls.find(c => c.options.method === 'PUT');
  assert.equal(saved.path, '/admin/networks/1/recipients');
  assert.deepEqual(JSON.parse(saved.options.body), {recipients:[{email:'updated@example.com', phone:null}, {email:null, phone:'+56987654321'}]});
  ui.controller.session.signOut();
  assert.equal(contacts.value, '');
  assert.equal(ui.nodes.get('#wifi-recipients-panel').hidden, true);
  assert.ok(![...ui.storage.values()].some(value => value.includes('updated@example.com')));
});

test('late recipient list from another network never replaces the selected network contacts', async () => {
  const pending = deferred();
  const ui = dashboard(async url => {
    if (url.endsWith('/networks')) return response([{id:1}, {id:2}]);
    if (url.endsWith('/1/recipients')) return pending.promise;
    if (url.endsWith('/2/recipients')) return response([{email:'second@example.com', phone:null}]);
    return response([]);
  });
  ui.login('admin', ['networks:manage']); await tick();
  const select = ui.nodes.get('#wifi-recipients-network'); select.value = '1';
  const first = select.events.change(); select.value = '2'; await select.events.change();
  pending.resolve(response([{email:'first@example.com', phone:null}])); await first;
  assert.equal(ui.nodes.get('#wifi-recipients-contacts').value, 'second@example.com;');
});
