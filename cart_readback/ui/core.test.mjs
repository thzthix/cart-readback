import assert from 'node:assert/strict';
import test from 'node:test';
import {conditionLabel, confirmPayload, evidenceText, FEATURE_FLAGS, formatMoney,
  isOrderLocked, mergedEvidenceRanges, operationKey, validateBootstrap, validateCheckout} from './core.mjs';

const source = {source_id: 'synthetic:KB-UK', revision: 1, sha256: 'a'.repeat(64), text: '🙂 UK QWERTY. Cable unstated.'};
const product = {sku_id: 'KB-UK', name: 'Synthetic', price_minor: 7900, currency: 'USD', source,
  baseline: {layout: 'UK_QWERTY', included_cable: 'unknown'}};
const catalog = [product, ...Array.from({length: 5}, (_, i) => ({...structuredClone(product), sku_id: `KB-${i}`}))];
const checkout = {review_id: 'r1', snapshot_hash: 'b'.repeat(64), state: 'REVIEW_REQUIRED', sku_id: 'KB-UK',
  source, amount: {minor: 7900, currency: 'USD'}, model: {is_fixture: true}, confirmation_id: null, order: null,
  conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'}, {condition_id: 'c2', kind: 'included_cable', value: 'any cable'}],
  results: [{condition_id: 'c1', status: 'match', explanation: 'Explicit key layout.',
    evidence: [{source_id: source.source_id, start: 2, end: 11, quote: 'UK QWERTY'}]},
  {condition_id: 'c2', status: 'unknown', explanation: 'Not stated.', evidence: []}]};
const clone = value => structuredClone(value);

test('money accepts safe integer USD only', () => {
  assert.equal(formatMoney(7900, 'USD'), 'USD 79.00');
  for (const value of [true, 79.1, -1, Infinity, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => formatMoney(value, 'USD'));
  assert.throws(() => formatMoney(7900, 'EUR'));
});
test('key layout is not inferred from physical ISO geometry', () => {
  assert.equal(conditionLabel({kind: 'layout', value: 'DE_QWERTZ'}), 'Keyboard layout: German QWERTZ');
  assert.throws(() => conditionLabel({kind: 'layout', value: 'ISO'}));
});
test('fixture-only flags block unsupported actual integrations', () => {
  assert.equal(FEATURE_FLAGS.live, false);
  const bootstrap = {api_version: '1', mode: 'fixture', revision: 0, csrf_token: 'token', catalog};
  assert.equal(validateBootstrap(bootstrap), bootstrap);
  for (const mode of ['sandbox', 'live', 'offline']) assert.throws(() => validateBootstrap({...bootstrap, mode}));
});
test('catalog requires exactly six unique SKUs', () => {
  const bootstrap = {api_version: '1', mode: 'fixture', revision: 0, csrf_token: 'token', catalog};
  assert.throws(() => validateBootstrap({...bootstrap, catalog: catalog.slice(1)}));
  assert.throws(() => validateBootstrap({...bootstrap, catalog: [product, product, ...catalog.slice(2)]}));
});
test('source evidence uses Unicode code points, not UTF-16 units', () => {
  assert.equal(evidenceText(source, checkout.results[0].evidence[0]), 'UK QWERTY');
  assert.throws(() => evidenceText(source, {...checkout.results[0].evidence[0], start: 3}));
});
test('foreign, negative, reversed, float and out-of-bounds spans fail closed', () => {
  const span = checkout.results[0].evidence[0];
  for (const patch of [{source_id: 'foreign'}, {start: -1}, {start: true}, {start: .5}, {end: 999}, {end: 2}, {quote: 'invented'}]) {
    assert.throws(() => evidenceText(source, {...span, ...patch}));
  }
});
test('valid same-source fixture checkout accepted', () => assert.equal(validateCheckout(checkout, catalog), checkout));
test('stale source, amount or adapter cannot be displayed as confirmable', () => {
  for (const patch of [{source: {...source, text: 'changed'}}, {source: {...source, revision: 2}},
    {amount: {minor: 1, currency: 'USD'}}, {model: {is_fixture: false}}, {order: {provider_mode: 'sandbox'}}]) {
    assert.throws(() => validateCheckout({...checkout, ...patch}, catalog));
  }
});
test('missing, duplicate or foreign result IDs are rejected', () => {
  for (const results of [checkout.results.slice(1), [checkout.results[0], checkout.results[0]],
    [...checkout.results, {...checkout.results[0], condition_id: 'foreign'}]]) {
    assert.throws(() => validateCheckout({...checkout, results}, catalog));
  }
});
test('unsupported outcome and unsupported desired value are blocked', () => {
  const bad = clone(checkout); bad.results[0].status = 'verified'; assert.throws(() => validateCheckout(bad, catalog));
  bad.results[0].status = 'match'; bad.conditions[0].value = 'ANSI'; assert.throws(() => validateCheckout(bad, catalog));
});
test('match and conflict require evidence; unknown is allowed without it', () => {
  for (const status of ['match', 'conflict']) {
    const bad = clone(checkout); bad.results[0].status = status; bad.results[0].evidence = [];
    assert.throws(() => validateCheckout(bad, catalog));
  }
  assert.equal(validateCheckout(checkout, catalog).results[1].status, 'unknown');
});
test('unknown needs its own acknowledgement and remains unknown', () => {
  assert.throws(() => confirmPayload(checkout, 1, true, new Set()));
  assert.throws(() => confirmPayload(checkout, 1, false, new Set(['c2'])));
  const payload = confirmPayload(checkout, 1, true, new Set(['c2']));
  assert.deepEqual(payload.acknowledged_unknown_ids, ['c2']);
  assert.deepEqual(payload.acknowledged_conflict_ids, []);
  assert.deepEqual(payload.confirmed_condition_ids, ['c1', 'c2']);
  assert.equal(checkout.results[1].status, 'unknown');
});
test('conflict acknowledgement is distinct from unknown', () => {
  const conflict = clone(checkout); conflict.results[0].status = 'conflict';
  assert.throws(() => confirmPayload(conflict, 1, true, new Set(['c2'])));
  assert.deepEqual(confirmPayload(conflict, 1, true, new Set(['c1', 'c2'])).acknowledged_conflict_ids, ['c1']);
});
test('confirmation cannot be re-used on a non-review state', () => {
  assert.throws(() => confirmPayload({...checkout, state: 'SNAPSHOT_CONFIRMED'}, 1, true, new Set(['c2'])));
});
test('every order/pending/unknown/completed state freezes edits', () => {
  assert.equal(isOrderLocked(checkout), false);
  for (const state of ['ORDER_CREATE_PENDING', 'ORDER_CREATED', 'PAYPAL_APPROVED', 'SERVER_RECHECKED', 'CAPTURE_PENDING', 'PAYMENT_UNKNOWN', 'COMPLETED', 'NEW_UNKNOWN_STATE']) {
    assert.equal(isOrderLocked({...checkout, state}), true);
  }
  assert.equal(isOrderLocked({...checkout, order: {order_id: 'o1'}}), true);
});
test('overlapping evidence ranges merge without dropping exact original text', () => {
  const other = clone(checkout); other.results[1].evidence = [{start: 5, end: 15}, {start: 19, end: 21}];
  assert.deepEqual(mergedEvidenceRanges(other), [{start: 2, end: 15}, {start: 19, end: 21}]);
});

test('operation keys survive reload in tab storage and separate create/capture', () => {
  const values = new Map();
  const storage = {getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value)};
  const first = '11111111-1111-4111-8111-111111111111';
  const second = '22222222-2222-4222-8222-222222222222';
  assert.equal(operationKey(storage, checkout.snapshot_hash, 'create', () => first), first);
  assert.equal(operationKey(storage, checkout.snapshot_hash, 'create', () => second), first);
  assert.equal(operationKey(storage, checkout.snapshot_hash, 'capture', () => second), second);
  assert.equal(values.size, 2);
  assert.throws(() => operationKey(storage, 'invalid', 'create', () => first));
  assert.throws(() => operationKey(storage, checkout.snapshot_hash, 'approve', () => first));
});
test('unavailable operation-key storage prevents request preparation', () => {
  const storage = {getItem: () => null, setItem: () => { throw new Error('storage blocked'); }};
  assert.throws(() => operationKey(storage, checkout.snapshot_hash, 'capture', () => '11111111-1111-4111-8111-111111111111'));
});

test('blocked analysis may have a null fingerprint and no results, never confirmable', () => {
  const blocked = {...checkout, state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: []};
  assert.equal(validateCheckout(blocked, catalog), blocked);
  assert.throws(() => confirmPayload(blocked, 1, true, new Set()));
  assert.equal(isOrderLocked(blocked), false);
});

test('stale existing order remains readable but cannot be re-confirmed', () => {
  const historical = {...checkout, stale: true, confirmation_id: null, order: {order_id: 'o1', provider_mode: 'fixture'},
    amount: {minor: 7800, currency: 'USD'}, source: {...source, revision: 2}};
  assert.equal(validateCheckout(historical, catalog), historical);
  assert.equal(isOrderLocked(historical), true);
  assert.throws(() => confirmPayload(historical, 1, true, new Set(['c2'])));
});

import {validateEnvelope, validateProviders, parseBuyerReturn, buyerReturnPayload} from './core.mjs';
const offline = {analysis: {mode: 'injected-offline', is_fixture: false}, payment: {mode: 'paypal-sandbox-offline', is_fixture: false}, network_enabled: false};
const localId = '11111111-1111-4111-8111-111111111111';
const query = `?order_id=${localId}&state=${'a'.repeat(43)}&outcome=approved&token=REMOTE1`;
const returnOrder = {...checkout, state: 'ORDER_CREATED', model: {is_fixture: false}, order: {order_id: localId,
  provider_mode: 'paypal-sandbox-offline', provider_order_id: 'REMOTE1', approval_url: 'https://www.sandbox.paypal.com/checkoutnow?token=REMOTE1',
  buyer_return: {available: true, consumed: false, cancelled: false, expires_at: '2099-01-01T00:00:00Z'}}};
test('offline providers are independently validated and never imply genuine calls', () => {
  for (const analysis of [offline.analysis, {mode: 'fixture', is_fixture: true}]) {
    assert.equal(validateEnvelope({api_version: '1', mode: 'offline', providers: {...offline, analysis}}).payment.mode, 'paypal-sandbox-offline');
  }
  assert.equal(validateCheckout(returnOrder, catalog, offline), returnOrder);
  for (const providers of [{...offline, network_enabled: true}, {...offline, analysis: {mode: 'live', is_fixture: false}},
    {...offline, payment: {mode: 'sandbox', is_fixture: false}}, {...offline, payment: {mode: 'fixture', is_fixture: false}}]) {
    assert.throws(() => validateProviders(providers));
  }
  assert.throws(() => validateEnvelope({api_version: '1', mode: 'fixture', providers: offline}));
  assert.throws(() => validateCheckout({...returnOrder, model: {is_fixture: true}}, catalog, offline));
  assert.throws(() => validateCheckout({...returnOrder, order: {...returnOrder.order, provider_mode: 'fixture'}}, catalog, offline));
});
test('approval URL stays exact, sandbox-only, token-bound and text-only', () => {
  for (const url of ['https://www.paypal.com/checkoutnow?token=REMOTE1', 'javascript:alert(1)',
    'https://www.sandbox.paypal.com.evil/checkoutnow?token=REMOTE1',
    'https://www.sandbox.paypal.com/checkoutnow?token=OTHER',
    `${returnOrder.order.approval_url}&extra=1`, `${returnOrder.order.approval_url}#fragment`]) {
    assert.throws(() => validateCheckout({...returnOrder, order: {...returnOrder.order, approval_url: url}}, catalog, offline));
  }
});
test('return parsing rejects duplicate, unknown, missing, encoded attacks and malformed fields', () => {
  assert.equal(parseBuyerReturn('/payment-return', query).provider_order_id, 'REMOTE1');
  assert.deepEqual(parseBuyerReturn('/payment-return', `${query}&PayerID=PAYER1`), parseBuyerReturn('/payment-return', query));
  assert.equal(parseBuyerReturn('/', query), null);
  assert.equal(parseBuyerReturn('/payment-return', '', ''), null);
  assert.throws(() => parseBuyerReturn('/payment-return', '', '#state')); 
  for (const bad of ['?', query + '&token=REMOTE1', query + '&%74oken=REMOTE1', query + '&next=https://evil',
    query.replace('approved', 'captured'), query.replace(localId, '../bad'), query.replace('REMOTE1', '%0AREMOTE1'),
    query.replace('REMOTE1', '%ZZ'), query.replace('REMOTE1', '%FF'), query.replace('&token=REMOTE1', ''),
    query.replace('a'.repeat(43), 'a'.repeat(42)), query + '&PayerID=']) assert.throws(() => parseBuyerReturn('/payment-return', bad));
  assert.throws(() => parseBuyerReturn('/payment-return', query, '#fragment'));
});
test('return matching blocks stale/foreign/expired/consumed and never supplies capture intent', () => {
  const returned = parseBuyerReturn('/payment-return', query);
  const payload = buyerReturnPayload(returned, returnOrder, 4, offline);
  assert.deepEqual(Object.keys(payload).sort(), ['expected_revision', 'snapshot_hash', 'return_state', 'provider_order_id', 'outcome'].sort());
  for (const changed of [{...returnOrder, stale: true}, {...returnOrder, state: 'SERVER_RECHECKED'},
    {...returnOrder, order: {...returnOrder.order, order_id: 'foreign'}},
    {...returnOrder, order: {...returnOrder.order, provider_order_id: 'OTHER'}}]) {
    assert.throws(() => buyerReturnPayload(returned, changed, 4, offline));
  }
  for (const patch of [{consumed: true}, {cancelled: true}, {available: false}, {expires_at: 'bad'}, {expires_at: '2000-01-01T00:00:00Z'}]) {
    assert.throws(() => buyerReturnPayload(returned, {...returnOrder, order: {...returnOrder.order,
      buyer_return: {...returnOrder.order.buyer_return, ...patch}}}, 4, offline));
  }
});
