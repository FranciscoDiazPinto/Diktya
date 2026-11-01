import test from 'node:test';
import assert from 'node:assert/strict';
import { createInventory } from '../modules/inventory.mjs';

class Element {
  constructor(text = '', value = '') { this.textContent = text; this.value = value; this.children = []; this.events = {}; this.style = {}; this.attributes = {}; this.hidden = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(event, handler) { this.events[event] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getBoundingClientRect() { return { left: 100, top: 50, width: 200, height: 100 }; }
}
const text = (node) => [node.textContent, ...node.children.map(text)].join(' ');
const summary = (extra = {}) => ({ access_points_total: 2, access_points_online: 1, access_points_offline: 1, vlans_active: 3, ssids_active: 2,
  availability_percent: 99.5, availability_window_hours: 24, active_alerts: 1, last_update_at: '2026-11-01T12:00:00Z', stale: false,
  sources: [{ source: 'unifi', status: 'ok', version: '10.6.106', stale: false, last_error_message: null }], ...extra });
const device = { id: 7, name: '<img src=x onerror=alert(1)>', device_type: 'ap', ip_address: '10.0.0.2', model: 'U7', state: 'offline', stale: false, last_online_at: null, alerts: [{ message: 'AP caído' }] };
const responses = (path) => {
  if (path.includes('/summary')) return summary();
  if (path.includes('/devices/')) return device;
  if (path.includes('/devices')) return { items: [device], total: 30, limit: 25, offset: 0 };
  if (path.includes('/alerts')) return { items: [{ severity: 'critical', source: 'unifi', device_name: 'AP Hall', message: 'Fuera de línea', detected_at: '2026-11-01T12:00:00Z' }], total: 1 };
  if (path.includes('/ssids')) return { items: [{ name: 'Feria', enabled: true, security: 'OPEN', vlan_tag: null }], total: 1 };
  if (path.includes('/vlans')) return { items: [{ tag: 20, name: 'Invitados', source: 'unifi' }], total: 1 };
  if (path.endsWith('/image')) return new Blob(['x']);
  if (/\/plans\/\d+$/.test(path)) return { id: 1, placed: [{ device_id: 7, name: 'AP Hall', state: 'offline', x: 0.5, y: 0.25 }], unplaced: [{ device_id: 8, name: 'AP Sur', state: 'online' }] };
  if (path.endsWith('/plans')) return [{ id: 1, name: 'Hall' }];
  return null;
};
function setup(request = async (path) => responses(path)) {
  const nodes = new Map(); const state = { session: 1 }; const calls = [];
  const document = { querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); }, querySelectorAll: () => [], createElement: () => new Element() };
  const window = { setInterval: () => 1, clearInterval() {}, URL: { createObjectURL: () => 'blob:plan', revokeObjectURL() {} } };
  const api = { authedRequest: (path, options) => { calls.push({ path, options }); return request(path, options); } };
  const controller = createInventory({ document, window, Option: Element, state, api, textNode: (tag, value, className) => { const element = new Element(value == null ? '' : String(value)); element.className = className; return element; } });
  return { nodes, state, calls, controller, $: (selector) => document.querySelector(selector) };
}
const admin = { permissions: ['monitoring:read', 'networks:manage'] };

test('muestra indicadores, filtros y paginación del inventario', async () => {
  const ui = setup();
  await ui.controller.configureUser({ permissions: ['monitoring:read'] });
  const kpis = text(ui.$('#inventory-kpis'));
  for (const expected of ['1 / 2', '99.50 %', 'SSID activos', 'VLAN activas']) assert.ok(kpis.includes(expected), expected);
  assert.equal(ui.$('#devices-page').textContent, '1–1 de 30');
  assert.equal(ui.$('#devices-next').disabled, false);
  assert.equal(ui.$('#inventory-stale').hidden, true);
  ui.$('#devices-state').value = 'offline'; ui.$('#devices-type').value = 'ap';
  await ui.$('#devices-state').events.change();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ui.calls.some(({ path }) => path.includes('state=offline') && path.includes('type=ap')));
});

test('el texto externo no se interpreta como HTML y un SSID sin VLAN no inventa una', async () => {
  const ui = setup();
  await ui.controller.configureUser({ permissions: ['monitoring:read'] });
  assert.equal(ui.$('#devices-body').children[0].children[0].textContent, device.name);
  assert.equal(ui.$('#devices-body').innerHTML, undefined);
  assert.ok(text(ui.$('#ssids-body')).includes('Sin resolver'));
});

test('avisa cuando los datos están desactualizados y cuando se pierde la API', async () => {
  const ui = setup(async (path) => (path.includes('/summary') ? summary({ stale: true, sources: [{ source: 'opnsense', status: 'unavailable', stale: true, last_error_message: 'Sin respuesta' }] }) : responses(path)));
  await ui.controller.configureUser({ permissions: ['monitoring:read'] });
  assert.equal(ui.$('#inventory-stale').hidden, false);
  assert.ok(ui.$('#inventory-stale').textContent.includes('OPNsense'));
  assert.ok(text(ui.$('#inventory-sources')).includes('Sin respuesta'));

  const down = setup(async () => { throw Object.assign(new Error('x'), { status: 0 }); });
  await down.controller.configureUser({ permissions: ['monitoring:read'] });
  assert.ok(down.$('#inventory-stale').textContent.includes('Reintentando'));
});

test('usuarios sin monitoreo no consultan; sin gestión no ven la carga de planos', async () => {
  const none = setup();
  await none.controller.configureUser({ permissions: [] });
  assert.equal(none.calls.length, 0);
  const viewer = setup();
  await viewer.controller.configureUser({ permissions: ['monitoring:read'] });
  assert.equal(viewer.$('#plan-form').hidden, true);
  const manager = setup();
  await manager.controller.configureUser(admin);
  assert.equal(manager.$('#plan-form').hidden, false);
});

test('el plano colorea por estado, lista los AP sin ubicar y permite ubicar uno', async () => {
  const ui = setup();
  await ui.controller.configureUser(admin);
  ui.$('#plan-select').value = '1';
  ui.$('#plan-select').events.change();
  await new Promise((resolve) => setImmediate(resolve));
  const marker = ui.$('#plan-markers').children[0];
  assert.ok(marker.className.includes('offline'));
  assert.equal(marker.style.left, '50%');
  assert.ok(text(ui.$('#plan-unplaced')).includes('sin ubicar'));

  await marker.events.click({ stopPropagation() {} });
  assert.ok(text(ui.$('#plan-detail')).includes('AP caído'));

  await ui.$('#plan-unplaced').children[0].events.click();
  await ui.$('#plan-stage').events.click({ clientX: 200, clientY: 75 });
  await new Promise((resolve) => setImmediate(resolve));
  const put = ui.calls.find(({ options }) => options?.method === 'PUT');
  assert.ok(put.path.endsWith('/plans/1/placements/8'));
  assert.deepEqual(JSON.parse(put.options.body), { x: 0.5, y: 0.25 });
});

test('una respuesta tardía de otra sesión se descarta', async () => {
  let release; const gate = new Promise((resolve) => { release = resolve; });
  const ui = setup(async (path) => { await gate; return responses(path); });
  const pending = ui.controller.configureUser({ permissions: ['monitoring:read'] });
  ui.state.session += 1;
  release();
  await pending;
  assert.equal(ui.$('#inventory-kpis').children.length, 0);
});
