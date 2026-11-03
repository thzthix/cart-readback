/** Real local HTTP + pure client contract checks. Still NOT a browser/rendered E2E test. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {confirmPayload, validateBootstrap, validateCheckout} from './core.mjs';

const origin = process.env.CART_READBACK_TEST_ORIGIN;
if (origin) {
  const url = new URL(origin);
  assert.equal(url.protocol, 'http:'); assert.equal(url.hostname, '127.0.0.1');
  assert.equal(url.origin, origin); assert.equal(url.username + url.password, '');
}
async function session() {
  const response = await fetch(`${origin}/api/bootstrap`);
  assert.equal(response.status, 200);
  const cookie = response.headers.get('set-cookie')?.split(';')[0];
  assert.ok(cookie, 'new synthetic test session');
  const bootstrap = validateBootstrap(await response.json());
  const client = {cookie, csrf: bootstrap.csrf_token, revision: bootstrap.revision, catalog: bootstrap.catalog, checkout: bootstrap.checkout};
  client.post = async (path, payload, action, expectedStatus = 200) => {
    const headers = {'Content-Type': 'application/json', 'Origin': origin, 'Cookie': cookie, 'X-CSRF-Token': client.csrf};
    if (['create', 'capture'].includes(action)) headers['Idempotency-Key'] = crypto.randomUUID();
    const response = await fetch(`${origin}${path}`, {method: 'POST', headers, body: JSON.stringify({expected_revision: client.revision, ...payload})});
    const data = await response.json(); assert.equal(response.status, expectedStatus, JSON.stringify(data.error));
    client.revision = data.revision;
    if (data.checkout) client.checkout = validateCheckout(data.checkout, client.catalog);
    return data;
  };
  return client;
}
function base(client) { return {snapshot_hash: client.checkout.snapshot_hash}; }
async function analyze(client, sku, conditions) { return client.post('/api/analyze', {sku_id: sku, conditions}); }
async function confirm(client, acknowledged = new Set()) {
  return client.post('/api/confirm', confirmPayload(client.checkout, client.revision, true, acknowledged));
}

test('HTTP serves the actual UI with correct MIME and same-origin protections', {skip: !origin}, async () => {
  for (const [path, mime, text] of [['/', 'text/html', 'Fixture mode'], ['/app.mjs', 'text/javascript', "from './core.mjs'"],
    ['/core.mjs', 'text/javascript', 'FEATURE_FLAGS'], ['/styles.css', 'text/css', '@media(max-width:480px)']]) {
    const response = await fetch(`${origin}${path}`); assert.equal(response.status, 200);
    assert.ok(response.headers.get('content-type').startsWith(mime));
    assert.match(response.headers.get('content-security-policy'), /connect-src 'self'/);
    assert.ok((await response.text()).includes(text));
  }
});
test('real fixture HTTP happy path agrees with client validation and explicit final confirmation', {skip: !origin}, async () => {
  const client = await session();
  await analyze(client, 'KB-UK-C2C', [{kind: 'layout', value: 'UK_QWERTY'}, {kind: 'included_cable', value: 'USB-C to USB-C'}]);
  assert.deepEqual(client.checkout.results.map(result => result.status), ['match', 'match']);
  await confirm(client);
  await client.post('/api/orders', {...base(client), review_id: client.checkout.review_id, confirmation_id: client.checkout.confirmation_id}, 'create');
  assert.equal(client.checkout.order.provider_mode, 'fixture'); assert.equal(client.checkout.order.approval_url, null);
  const route = `/api/orders/${client.checkout.order.order_id}`;
  await client.post(`${route}/fixture-approve`, base(client)); assert.equal(client.checkout.state, 'PAYPAL_APPROVED');
  await client.post(`${route}/verify`, base(client)); assert.equal(client.checkout.state, 'SERVER_RECHECKED');
  await client.post(`${route}/capture`, {...base(client), confirmation_id: client.checkout.confirmation_id, final_confirmation: true}, 'capture');
  assert.equal(client.checkout.state, 'COMPLETED'); assert.equal(client.checkout.order.status, 'COMPLETED');
  const restored = await fetch(`${origin}/api/bootstrap`, {headers: {Cookie: client.cookie}});
  const data = validateBootstrap(await restored.json());
  assert.equal(validateCheckout(data.checkout, data.catalog).order.order_id, client.checkout.order.order_id);
  assert.equal(data.checkout.state, 'COMPLETED');
});
test('real fixture HTTP unknown/conflict status and acknowledgements align with client', {skip: !origin}, async () => {
  const unknown = await session();
  await analyze(unknown, 'KB-UK-UNKNOWN', [{kind: 'included_cable', value: 'any cable'}]);
  assert.equal(unknown.checkout.results[0].status, 'unknown');
  assert.throws(() => confirmPayload(unknown.checkout, unknown.revision, true, new Set()));
  const id = unknown.checkout.conditions[0].condition_id;
  await confirm(unknown, new Set([id])); assert.equal(unknown.checkout.state, 'SNAPSHOT_CONFIRMED');
  assert.equal(unknown.checkout.results[0].status, 'unknown');
  const conflict = await session();
  await analyze(conflict, 'KB-DE-A2C', [{kind: 'layout', value: 'UK_QWERTY'}]);
  assert.equal(conflict.checkout.results[0].status, 'conflict');
  const mismatchId = conflict.checkout.conditions[0].condition_id;
  await confirm(conflict, new Set([mismatchId])); assert.equal(conflict.checkout.state, 'SNAPSHOT_CONFIRMED');
  assert.equal(conflict.checkout.results[0].status, 'conflict');
});
