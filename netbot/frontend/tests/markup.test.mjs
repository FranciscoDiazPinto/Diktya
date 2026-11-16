import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Las pruebas de cada módulo usan un DOM simulado que crea nodos a pedido. Esta prueba
// cierra esa brecha: todo elemento que un módulo busca por id debe existir en la página real.
const html = readFileSync(new URL('../src/components/FeatureMarkup.jsx', import.meta.url), 'utf8');
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
const source = name => readFileSync(new URL(`../modules/${name}.mjs`, import.meta.url), 'utf8');
const literal = text => [...text.matchAll(/\$\('([a-z0-9-]+)'\)/g)].map(match => match[1]);

for (const [name, prefix] of [['change-plans', ''], ['users', ''], ['account', ''], ['system-status', ''], ['audit', 'audit-']]) {
  test(`${name}: every element it looks up exists in React markup`, () => {
    const wanted = literal(source(name)).map(id => prefix + id);
    assert.ok(wanted.length > 3, 'el módulo debe consultar elementos por id');
    assert.deepEqual(wanted.filter(id => !ids.has(id)), []);
  });
}

test('forms that carry secrets never autofill into the wrong field and nothing loads remote scripts', () => {
  assert.match(html, /id="user-password"\s+type="password"[^>]*autoComplete="new-password"/);
  assert.match(html, /id="account-current"\s+type="password"[^>]*autoComplete="current-password"/);
  assert.equal([...html.matchAll(/<script[^>]*src="(https?:)?\/\//g)].length, 0);
});
