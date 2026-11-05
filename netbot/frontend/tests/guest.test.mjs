import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createGuest} from '../modules/guest.mjs';

class Element {
  constructor(text = '', value = '') { this.textContent = text; this.value = String(value); this.children = []; this.events = {}; this.style = {}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  focus() {}
}
function setup(handler = async () => ({answer: 'Prueba reiniciar la conexión.', state: 'answered'})) {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [`#${m[1]}`, new Element()]));
  let time = 100000, timerId = 0;
  const timers = new Map(), calls = [], events = {};
  const document = {querySelector: s => nodes.get(s), createElement: () => new Element(), addEventListener: (n, f) => events[n] = f};
  const window = {setTimeout(f, ms) { const id = ++timerId; timers.set(id, {f, at: time + ms}); return id; }, clearTimeout: id => timers.delete(id), addEventListener: (n, f) => events[n] = f};
  const api = {async apiRequest(path, options = {}) {
    calls.push({path, options});
    if (path.endsWith('/sessions')) return {token: `guest-${calls.length}`};
    if (path.endsWith('/session') || path.endsWith('/activity')) return;
    return handler(path, options);
  }};
  const guest = createGuest({document, window, api, Option: Element, now: () => time}); guest.start();
  const $ = s => nodes.get(s);
  return {guest, $, calls, events, timers,
    content: () => $('#guest-messages').children.map(n => n.children[0].textContent).join('\n'),
    async identify(contact) { $('#guest-contact').value = contact; await $('#guest-identify-form').events.submit({preventDefault() {}}); },
    async submit(message) { $('#guest-message').value = message; await $('#guest-form').events.submit({preventDefault() {}}); },
    advance(ms) { time += ms; for (const [id, t] of [...timers]) if (t.at <= time) { timers.delete(id); t.f(); } },
    elapse(ms) { time += ms; },
  };
}

test('entry is anonymous; closing requires confirmation and clears within exactly one minute', async () => {
  const ui = setup();
  assert.equal(ui.$('#login-screen').style.display, 'none');
  assert.equal(ui.calls.length, 0);
  await ui.submit('No puedo conectar');
  assert.match(ui.content(), /¿Se resolvió tu duda/);
  ui.$('#guest-yes').events.click();
  assert.match(ui.content(), /¿Confirmas que borremos/);
  ui.advance(59999);
  assert.match(ui.content(), /No puedo conectar/);
  ui.advance(1);
  assert.doesNotMatch(ui.content(), /No puedo conectar/);
  assert.ok(ui.calls.some(c => c.path.endsWith('/session') && c.options.method === 'DELETE'));
});

test('QR stays outside history and is removed together with all guest state on confirmation', async () => {
  const ui = setup(async path => (path.endsWith('/networks') || path.endsWith('/identify')) ? [{id: 1, name: 'Invitados', ssid: 'Public'}] : {ssid:'Public', qr_data_url:'data:image/svg+xml;base64,TEST'});
  await ui.submit('Dame el Wi-Fi');
  await ui.$('#guest-portal-button').events.click();
  ui.$('#guest-network').value = '1';
  await ui.$('#guest-show-qr').events.click();
  assert.equal(ui.$('#guest-qr').children[1].src, 'data:image/svg+xml;base64,TEST');
  assert.doesNotMatch(ui.content(), /base64|TEST/);
  await ui.submit('sí');
  assert.match(ui.content(), /¿Confirmas/);
  await ui.submit('confirmo');
  assert.equal(ui.$('#guest-qr').children.length, 0);
  assert.equal(ui.$('#guest-network').children.length, 0);
  assert.equal(ui.$('#guest-message').value, '');
  assert.equal(ui.timers.size, 0);
  assert.doesNotMatch(ui.content(), /Dame el Wi-Fi/);
});

test('unanswered resolution question also expires; choosing more help keeps attention active', async () => {
  const ui = setup();
  await ui.submit('Mi teléfono no conecta');
  ui.advance(30000);
  ui.$('#guest-no').events.click();
  ui.advance(30000);
  assert.match(ui.content(), /Mi teléfono/);
  ui.advance(30000);
  assert.doesNotMatch(ui.content(), /Mi teléfono/);
});

test('late answer after timeout cannot appear for the next customer', async () => {
  let resolve;
  const ui = setup(() => new Promise(r => resolve = r));
  const pending = ui.submit('Consulta del cliente anterior');
  await new Promise(r => setImmediate(r));
  ui.advance(60000);
  resolve({answer:'Respuesta del cliente anterior'});
  await pending;
  assert.doesNotMatch(ui.content(), /cliente anterior/);
  assert.equal(ui.$('#guest-send').disabled, false);
});

test('login erases guest chat and QR; returning starts a new attention', async () => {
  const ui = setup();
  await ui.submit('Ayuda privada');
  ui.$('#guest-login').events.click();
  assert.equal(ui.$('#guest-screen').hidden, true);
  assert.equal(ui.$('#login-screen').style.display, '');
  assert.doesNotMatch(ui.content(), /Ayuda privada/);
  ui.$('#guest-back').events.click();
  assert.equal(ui.$('#guest-screen').hidden, false);
  assert.equal(ui.$('#login-screen').style.display, 'none');
  assert.equal(ui.$('#guest-resolution').hidden, true);
});

test('suspended browser clears expired attention immediately when visible again', async () => {
  const ui = setup();
  await ui.submit('Consulta sensible');
  ui.elapse(60001);
  ui.events.visibilitychange();
  assert.doesNotMatch(ui.content(), /Consulta sensible/);
});

test('a QR arriving after cleanup cannot appear in the next attention', async () => {
  let resolve;
  const ui = setup(path => (path.endsWith('/networks') || path.endsWith('/identify')) ? [{id: 1, name: 'Invitados', ssid: 'Public'}] : new Promise(r => resolve = r));
  await ui.$('#guest-portal-button').events.click();
  ui.$('#guest-network').value = '1';
  const pending = ui.$('#guest-show-qr').events.click();
  await new Promise(r => setImmediate(r));
  ui.guest.reset();
  resolve({ssid: 'Old', qr_data_url: 'data:image/svg+xml;base64,OLD'});
  await pending;
  assert.equal(ui.$('#guest-qr').children.length, 0);
  assert.equal(ui.$('#guest-wifi').hidden, true);
});

test('password questions reach the server clarification instead of generic private recovery', async () => {
  const ui = setup(async () => ({answer:'¿Te refieres a las credenciales del Wi-Fi o a tu cuenta de Netbot?',needs_clarification:true}));
  await ui.submit('no tengo mi clave de usuario');
  assert.match(ui.content(), /Wi-Fi o a tu cuenta de Netbot/);
  assert.equal(ui.$('#guest-resolution').hidden, true);
  assert.doesNotMatch(ui.content(), /¿Se resolvió/);
  assert.ok(ui.calls.some(c => c.path.endsWith('/messages')));
  assert.ok(!ui.calls.some(c => /identify|access/.test(c.path)));
  assert.equal(ui.$('#guest-identify-form').hidden, true);
});

test('contact accidentally entered in chat is neither echoed nor sent to the model', async () => {
  const ui = setup();
  await ui.submit('Mi correo es private@example.com');
  assert.doesNotMatch(ui.content(), /private@example.com/);
  assert.equal(ui.$('#guest-identify-form').hidden, false);
  assert.equal(ui.calls.length, 0);
  ui.$('#guest-contact').value = '+56912345678';
  ui.advance(60000);
  assert.equal(ui.$('#guest-contact').value, '');
  assert.equal(ui.$('#guest-identify-form').hidden, true);
});

test('failed identification never displays a network selector or QR', async () => {
  const ui = setup(async () => { const error = new Error('No se pudo habilitar el acceso.'); error.status = 403; throw error; });
  ui.$('#guest-wifi-button').events.click();
  await ui.identify('no-match@example.com');
  assert.equal(ui.$('#guest-wifi').hidden, true);
  assert.equal(ui.$('#guest-qr').children.length, 0);
  assert.match(ui.$('#guest-identify-error').textContent, /No se pudo/);
  assert.ok(!ui.calls.some(c => c.path.endsWith('/identify')));
  assert.doesNotMatch(ui.content(), /no-match@example.com/);
});

test('email recovery sends only the form email and keeps contacts outside chat history', async () => {
  const ui = setup(async () => ({message:'Si corresponde, recibirás un enlace de confirmación.'}));
  ui.$('#guest-wifi-button').events.click();
  assert.equal(ui.$('#guest-identify-form').hidden,false);
  await ui.identify('expositor@example.com');
  const call=ui.calls.find(c=>c.path.endsWith('/recovery/email'));
  assert.deepEqual(JSON.parse(call.options.body),{email:'expositor@example.com'});
  assert.equal(ui.$('#guest-contact').value,'');
  assert.equal(ui.$('#guest-identify-form').hidden,true);
  assert.doesNotMatch(ui.content(),/expositor@example.com/);
  assert.ok(!ui.calls.some(c=>c.path.endsWith('/messages')));
});

 test('diagnostic questions and unknown states keep the conversation open', async () => {
  for (const response of [{answer:'¿Ves la red?',state:'needs_information'}, {answer:'Continúa',state:'unexpected'}, {answer:'Texto sin clasificación'}]) {
    const ui=setup(async()=>response);await ui.submit('No conecta');
    assert.equal(ui.$('#guest-resolution').hidden,true);assert.doesNotMatch(ui.content(),/¿Se resolvió/);
  }
});
 test('a final answer offers resolution only once until more help is requested',async()=>{
  const ui=setup();await ui.submit('Qué es DHCP');await ui.submit('Y DNS');
  assert.equal((ui.content().match(/¿Se resolvió/g)||[]).length,1);
  assert.equal(ui.$('#guest-resolution').hidden,true);
  ui.$('#guest-finish').events.click();ui.$('#guest-no').events.click();
  await ui.submit('Sigo con una duda');assert.equal((ui.content().match(/¿Se resolvió/g)||[]).length,2);
});
 test('user-confirmed closure asks before erasing the conversation',async()=>{
  const ui=setup(async()=>({answer:'Gracias por confirmar.',state:'closed'}));await ui.submit('Ya funciona');
  assert.match(ui.content(),/¿Confirmas que borremos/);assert.match(ui.content(),/Ya funciona/);
  ui.$('#guest-yes').events.click();assert.doesNotMatch(ui.content(),/Ya funciona/);
});
 test('provider failures never ask whether an answer solved the issue',async()=>{
  const ui=setup(async()=>{throw new Error('No se pudo responder');});await ui.submit('Hola');
  assert.match(ui.content(),/No se pudo responder/);assert.doesNotMatch(ui.content(),/¿Se resolvió/);assert.equal(ui.$('#guest-resolution').hidden,true);
});
