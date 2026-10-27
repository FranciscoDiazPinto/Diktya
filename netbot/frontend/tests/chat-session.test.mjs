import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { canReserveVlans, reservationPayload } from '../chat-reservations.mjs';

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
  const monitoringNodes = [new Element(), new Element()];
  const context = vm.createContext({
    document: {
      querySelector(selector) { assert.ok(nodes.has(selector), `Missing HTML selector ${selector}`); return nodes.get(selector); },
      querySelectorAll(selector) { return selector.startsWith('.stats-grid,') ? monitoringNodes : []; },
      createElement() { return new Element(); },
    },
    Option: Element,
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    window: { setInterval() {}, clearInterval() {}, setTimeout() {} },
    fetch, canReserveVlans, reservationPayload,
  });
  const source = readFileSync(new URL('../app.js', import.meta.url), 'utf8').replace(/^import .*;\n/, '');
  vm.runInContext(source, context);
  return { nodes, storage, monitoringNodes, run: (code) => vm.runInContext(code, context),
    login(id) { context.testUser = user(id); vm.runInContext('setAuthenticated(testUser)', context); } };
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
