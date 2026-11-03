/** Independent pure-client checks. No browser/rendering behavior is claimed. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {confirmPayload, evidenceText, isOrderLocked, operationKey,
  validateCheckout} from '../ui/core.mjs';

const source = {source_id: 'synthetic:independent', revision: 1,
  sha256: 'a'.repeat(64), text: '🛒 UK QWERTY'};
const product = {sku_id: 'KB-INDEPENDENT', price_minor: 7900, currency: 'USD', source};
function checkout() {
  return {review_id: 'independent-review', state: 'REVIEW_REQUIRED',
    snapshot_hash: 'b'.repeat(64), sku_id: product.sku_id, source,
    amount: {minor: 7900, currency: 'USD'}, model: {is_fixture: true},
    conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'},
      {condition_id: 'c2', kind: 'included_cable', value: 'any cable'}],
    results: [{condition_id: 'c1', status: 'conflict', explanation: 'Synthetic conflict.',
      evidence: [{source_id: source.source_id, start: 2, end: 11, quote: 'UK QWERTY'}]},
    {condition_id: 'c2', status: 'unknown', explanation: 'Synthetic missing fact.', evidence: []}],
    order: null};
}

test('astral prefix uses codepoint spans rather than JavaScript UTF-16 offsets', () => {
  assert.equal(evidenceText(source, {source_id: source.source_id, start: 2,
    end: 11, quote: 'UK QWERTY'}), 'UK QWERTY');
  assert.throws(() => evidenceText(source, {source_id: source.source_id,
    start: 3, end: 12, quote: 'UK QWERTY'}));
  assert.throws(() => evidenceText(source, {source_id: 'different-sku',
    start: 2, end: 11, quote: 'UK QWERTY'}));
});

test('UNKNOWN and conflict require distinct explicit acknowledgements and stay unchanged', () => {
  const current = checkout();
  assert.throws(() => confirmPayload(current, 1, false, new Set(['c1', 'c2'])));
  assert.throws(() => confirmPayload(current, 1, true, new Set(['c1'])));
  assert.throws(() => confirmPayload(current, 1, true, new Set(['c2'])));
  const payload = confirmPayload(current, 1, true, new Set(['c1', 'c2']));
  assert.deepEqual(payload.acknowledged_unknown_ids, ['c2']);
  assert.deepEqual(payload.acknowledged_conflict_ids, ['c1']);
  assert.deepEqual(current.results.map(result => result.status), ['conflict', 'unknown']);
});

test('blocked analysis with null hash is recoverable but cannot be confirmed', () => {
  const current = {...checkout(), state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: []};
  assert.equal(validateCheckout(current, [product]), current);
  assert.throws(() => confirmPayload(current, 1, true, new Set()));
  assert.equal(isOrderLocked(current), false);
});

test('changed source, changed price and non-fixture provider fail closed', () => {
  const current = checkout();
  assert.throws(() => validateCheckout(current, [{...product, source: {...source, revision: 2}}]));
  assert.throws(() => validateCheckout(current, [{...product, price_minor: 1}]));
  assert.throws(() => validateCheckout({...current, model: {is_fixture: false}}, [product]));
  assert.throws(() => validateCheckout({...current, order: {provider_mode: 'sandbox'}}, [product]));
});

test('stale existing order can display history for reconciliation but never reconfirm', () => {
  const current = {...checkout(), stale: true, state: 'PAYMENT_UNKNOWN',
    confirmation_id: null, order: {order_id: 'existing', provider_mode: 'fixture'}};
  const changedCatalog = [{...product, price_minor: 8100,
    source: {...source, revision: 2, sha256: 'd'.repeat(64), text: 'New description.'}}];
  assert.equal(validateCheckout(current, changedCatalog), current);
  assert.equal(isOrderLocked(current), true);
  assert.throws(() => confirmPayload(current, 3, true, new Set(['c1', 'c2'])));
});

test('all existing, unknown and pending orders lock selection', () => {
  for (const state of ['ORDER_CREATE_PENDING', 'ORDER_CREATED', 'PAYPAL_APPROVED',
    'SERVER_RECHECKED', 'CAPTURE_PENDING', 'PAYMENT_UNKNOWN', 'COMPLETED']) {
    assert.equal(isOrderLocked({...checkout(), state}), true, state);
  }
  assert.equal(isOrderLocked({...checkout(), order: {order_id: 'existing'}}), true);
  assert.equal(isOrderLocked(checkout()), false);
});

test('operation key survives module callers via storage and call types stay separate', () => {
  const stored = new Map();
  const storage = {getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value)};
  let generated = 0;
  const uuid = () => `12345678-1234-4234-8234-${String(++generated).padStart(12, '0')}`;
  const hash = 'c'.repeat(64);
  const first = operationKey(storage, hash, 'create', uuid);
  assert.equal(operationKey(storage, hash, 'create', uuid), first);
  assert.notEqual(operationKey(storage, hash, 'capture', uuid), first);
  assert.equal(generated, 2);
  assert.throws(() => operationKey(storage, hash, 'refund', uuid));
  assert.throws(() => operationKey({getItem: () => { throw new Error('blocked storage'); }}, hash, 'create', uuid));
  for (const [name, value] of stored) {
    assert.match(name, /^cart-readback:fixture:v1:[a-f0-9]{64}:(create|capture)$/);
    assert.match(value, /^[a-f0-9-]{36}$/);
  }
});
