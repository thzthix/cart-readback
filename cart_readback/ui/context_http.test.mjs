/** Actual loopback HTTP; provider exchange/host authority are fabricated. Not browser E2E. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {confirmPayload, contextAnalysisText, validateBootstrap, validateCheckout, validateEnvelope} from './core.mjs';

const origin = process.env.CART_READBACK_CONTEXT_ORIGIN;
const cookie = process.env.CART_READBACK_CONTEXT_COOKIE;
const scenario = process.env.CART_READBACK_CONTEXT_SCENARIO;
if (origin) {
  const url = new URL(origin);
  assert.equal(url.protocol, 'http:'); assert.equal(url.hostname, '127.0.0.1');
  assert.equal(url.origin, origin); assert.equal(url.username + url.password, '');
  assert.match(cookie, /^cr_session=[a-zA-Z0-9_-]+$/);
  assert.ok(['unavailable', 'known', 'semantic', 'protocol'].includes(scenario));
}
const conditions = [{kind: 'layout', value: 'UK_QWERTY'}, {kind: 'included_cable', value: 'USB-C to USB-C'}];

test(`actual C12 loopback: ${scenario || 'runner required'}`, {skip: !origin}, async () => {
  const initial = await fetch(`${origin}/api/bootstrap`, {headers: {Cookie: cookie}});
  assert.equal(initial.status, 200);
  let data = validateBootstrap(await initial.json());
  let revision = data.revision;
  const catalog = data.catalog;
  const csrf = data.csrf_token;
  const providers = validateEnvelope(data);
  assert.equal(data.mode, 'mixed'); assert.equal(providers.network_enabled, false);
  assert.equal(providers.analysis.execution_kind, scenario === 'unavailable' ? 'unavailable' : 'fabricated-offline');
  assert.equal(providers.analysis.dispatch_available, scenario !== 'unavailable');
  assert.equal(data.checkout, null);

  async function post(path, payload, statuses = [200], idempotent = false) {
    const headers = {'Content-Type': 'application/json', Origin: origin, Cookie: cookie, 'X-CSRF-Token': csrf};
    if (idempotent) headers['Idempotency-Key'] = crypto.randomUUID();
    const response = await fetch(`${origin}${path}`, {method: 'POST', headers,
      body: JSON.stringify({expected_revision: revision, ...payload})});
    const result = await response.json();
    assert.ok(statuses.includes(response.status), `${path}: ${response.status} ${JSON.stringify(result.error)}`);
    const currentProviders = validateEnvelope(result);
    if (result.checkout) validateCheckout(result.checkout, catalog, currentProviders);
    assert.doesNotMatch(JSON.stringify(result), /org_fabricated_private|proj_fabricated_private|host_binding_record|pricing_adoption|credential_version|req_fabricated|runtime_sha256/);
    revision = result.revision;
    data = result;
    return result;
  }
  const input = {sku_id: 'KB-UK-C2C', conditions};
  for (const field of ['provider', 'approval', 'credential', 'rate', 'ceiling', 'live']) {
    await post('/api/analyze', {...input, [field]: 'forged-browser-authority'}, [400]);
    assert.equal(revision, 0, 'rejected authority must not reserve or dispatch');
  }
  await post('/api/analyze', input, scenario === 'unavailable' ? [503] : scenario === 'known' ? [200] : [422]);
  if (scenario === 'unavailable') {
    assert.equal(data.providers.analysis.dispatch_available, false);
    assert.equal(data.checkout ?? null, null);
    return;
  }
  assert.equal(data.checkout.analysis.dispatch_state, 'attempted');
  assert.equal(data.checkout.analysis.usage_observed, true);
  assert.equal(data.checkout.analysis.evidence_kind, 'fabricated-offline');
  assert.match(contextAnalysisText(data.checkout), /not a provider observation/);
  assert.equal(data.checkout.analysis.accounting_state, scenario === 'protocol' ? 'unknown' : 'known');
  if (scenario !== 'known') {
    assert.equal(data.checkout.state, 'ANALYSIS_BLOCKED');
    assert.equal(data.checkout.snapshot_hash, null);
    assert.throws(() => confirmPayload(data.checkout, revision, true, new Set()));
    if (scenario === 'protocol') await post('/api/analyze', input, [409, 503]);
    const restored = await fetch(`${origin}/api/bootstrap`, {headers: {Cookie: cookie}});
    const current = validateBootstrap(await restored.json());
    validateCheckout(current.checkout, catalog, current.providers);
    assert.equal(current.checkout.analysis.usage_observed, true);
    assert.equal(current.checkout.analysis.accounting_state, scenario === 'protocol' ? 'unknown' : 'known');
    return;
  }
  assert.deepEqual(data.checkout.results.map(result => result.status), ['match', 'match']);
  await post('/api/confirm', confirmPayload(data.checkout, revision, true, new Set()));
  await post('/api/orders', {review_id: data.checkout.review_id, snapshot_hash: data.checkout.snapshot_hash,
    confirmation_id: data.checkout.confirmation_id}, [200], true);
  assert.equal(data.checkout.order.provider_mode, 'fixture');
  const orderId = data.checkout.order.order_id;
  const path = `/api/orders/${orderId}`;
  const snapshot = data.checkout.snapshot_hash;
  await post(`${path}/fixture-approve`, {snapshot_hash: snapshot});
  await post(`${path}/verify`, {snapshot_hash: snapshot});
  assert.equal(data.checkout.state, 'SERVER_RECHECKED');
  await post(`${path}/capture`, {snapshot_hash: snapshot, confirmation_id: data.checkout.confirmation_id, final_confirmation: true}, [200], true);
  assert.equal(data.checkout.state, 'COMPLETED');
  assert.equal(data.checkout.order.order_id, orderId);
  assert.equal(data.checkout.analysis.evidence_kind, 'fabricated-offline');
  const restored = validateBootstrap(await (await fetch(`${origin}/api/bootstrap`, {headers: {Cookie: cookie}})).json());
  validateCheckout(restored.checkout, catalog, restored.providers);
  assert.equal(restored.checkout.state, 'COMPLETED');
  assert.equal(restored.checkout.order.order_id, orderId);
});
