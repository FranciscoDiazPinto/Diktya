import test from 'node:test';
import assert from 'node:assert/strict';
import { canReserveVlans, reservationPayload } from '../chat-reservations.mjs';

test('only operator and admin can see reservation controls', () => {
  assert.equal(canReserveVlans(['visor']), false);
  assert.equal(canReserveVlans(['operador']), true);
  assert.equal(canReserveVlans(['admin']), true);
});

test('reservation payload contains only approved fields', () => {
  assert.deepEqual(reservationPayload({ parent_interface: 'igc1', tag: '20', event_name: ' Feria ', purpose: ' Invitados ', ssid: ' Evento ', actor_id: 3 }), {
    parent_interface: 'igc1', tag: 20, event_name: 'Feria', purpose: 'Invitados', ssid: 'Evento',
  });
});
