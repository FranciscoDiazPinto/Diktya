import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Las pruebas de cada módulo usan un DOM simulado que crea nodos a pedido. Esta prueba
// cierra esa brecha: todo elemento que un módulo busca por id debe existir en la página real.
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
const source = name => readFileSync(new URL(`../modules/${name}.mjs`, import.meta.url), 'utf8');
const literal = text => [...text.matchAll(/\$\('([a-z0-9-]+)'\)/g)].map(match => match[1]);

for (const [name, prefix] of [['change-plans', ''], ['users', ''], ['account', ''], ['system-status', ''], ['audit', 'audit-']]) {
  test(`${name}: every element it looks up exists in index.html`, () => {
    const wanted = literal(source(name)).map(id => prefix + id);
    assert.ok(wanted.length > 3, 'el módulo debe consultar elementos por id');
    assert.deepEqual(wanted.filter(id => !ids.has(id)), []);
  });
}

test('every navigable view has its link and its section', () => {
  const views = [...source('navigation').matchAll(/key:'([a-z-]+)',nav:'([a-z-]+)'/g)];
  const inventory = ['devices', 'alerts', 'wireless', 'coverage'].map(key => [key, key + '-nav']);
  for (const [key, nav] of [...views.map(match => [match[1], match[2]]), ...inventory]) {
    assert.ok(ids.has('view-' + key), 'falta la sección view-' + key);
    assert.ok(ids.has(nav), 'falta el enlace ' + nav);
    assert.match(html, new RegExp(`id="${nav}"[^>]*href="#${key}"|href="#${key}"[^>]*id="${nav}"`));
  }
});

test('forms that carry secrets never autofill into the wrong field and nothing loads remote scripts', () => {
  assert.match(html, /id="user-password" type="password"[^>]*autocomplete="new-password"/);
  assert.match(html, /id="account-current" type="password"[^>]*autocomplete="current-password"/);
  assert.equal([...html.matchAll(/<script[^>]*src="(https?:)?\/\//g)].length, 0);
});
