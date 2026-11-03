/** Application logic in a minimal fake DOM; NOT a rendered/browser accessibility test. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createServer} from 'node:http';
import test from 'node:test';

class Element {
  constructor(tag, id = '') {
    this.tagName = tag; this.id = id; this.children = []; this.listeners = new Map(); this.dataset = {};
    this.hidden = false; this.disabled = false; this.checked = false; this.value = ''; this._text = '';
    this.className = ''; this.parentElement = null;
    this.classList = {toggle: (name, on) => {
      const classes = new Set(this.className.split(' ').filter(Boolean));
      if (on) classes.add(name); else classes.delete(name); this.className = [...classes].join(' ');
    }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  replaceChildren(...children) { this._text = ''; this.children = []; this.append(...children); }
  addEventListener(type, callback) { const callbacks = this.listeners.get(type) || []; callbacks.push(callback); this.listeners.set(type, callbacks); }
  dispatch(type) { for (const callback of this.listeners.get(type) || []) callback({preventDefault() {}}); }
  click() { if (!this.disabled) this.dispatch('click'); }
  focus() { globalThis.document.activeElement = this; }
}
const nativeFetch = globalThis.fetch;
const nativeSetTimeout = globalThis.setTimeout;
const ids = new Map();
const html = fs.readFileSync(new URL('./index.html', import.meta.url), 'utf8');
for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
  const element = new Element(match[1], match[2]);
  element.hidden = /\bhidden\b/.test(match[0]); element.disabled = /\bdisabled\b/.test(match[0]); ids.set(match[2], element);
}
// Supply native template relationships the tiny harness does not parse.
const reviewLabel = new Element('label'); reviewLabel.append(ids.get('confirm-snapshot'));
ids.set('review-label-harness', reviewLabel);
ids.get('layout').value = 'UK_QWERTY'; ids.get('cable').value = 'any cable';
function descendants(root) { return [root, ...root.children.flatMap(descendants)]; }
function elements() { return [...new Set([...ids.values()].flatMap(descendants))]; }
function matches(element, selector) {
  if (selector === 'input[name="sku"]') return element.tagName === 'input' && element.name === 'sku';
  if (selector === '[data-ack]') return Object.hasOwn(element.dataset, 'ack');
  if (selector === '[data-order-action]') return Object.hasOwn(element.dataset, 'orderAction');
  return false;
}
globalThis.document = {
  activeElement: null,
  getElementById: id => ids.get(id) || elements().find(element => element.id === id) || null,
  createElement: tag => new Element(tag),
  createTextNode: text => { const element = new Element('#text'); element.textContent = text; return element; },
  querySelectorAll: selector => selector === '#catalog-rows tr' ? ids.get('catalog-rows').children : elements().filter(element => matches(element, selector)),
};
const storedKeys = new Map();
globalThis.sessionStorage = {getItem: key => storedKeys.get(key) || null, setItem: (key, value) => storedKeys.set(key, value)};
const source = {source_id: 'synthetic:KB-UK', revision: 1, sha256: 'a'.repeat(64), text: 'Layout: UK QWERTY. Included cable: USB-C to USB-C. <script>capture()</script>'};
const product = {sku_id: 'KB-UK', name: 'Synthetic keyboard', price_minor: 7900, currency: 'USD', source,
  baseline: {layout: 'UK_QWERTY', included_cable: 'USB-C to USB-C'}};
const catalog = [product, ...Array.from({length: 5}, (_, i) => ({...structuredClone(product), sku_id: `KB-${i}`}))];
let revision = 0; let checkout = null; let failNext = false; const requests = [];
let envelopeMode = 'fixture'; let activeProviders; let releaseInitialBootstrap;
const response = data => ({ok: true, json: async () => structuredClone({api_version: '1', mode: envelopeMode,
  ...(activeProviders ? {providers: activeProviders} : {}), revision, ...data})});
const contextProviders = (execution_kind = 'fabricated-offline', dispatch_available = true) => ({
  analysis: {mode: 'genuine-context-capacity', is_fixture: false, execution_kind, dispatch_available},
  payment: {mode: 'fixture', is_fixture: true}, network_enabled: execution_kind === 'provider-runtime' && dispatch_available});
const contextModel = execution_kind => ({provider: 'openai-responses', model_version: 'gpt-6-luna',
  prompt_version: 'cartreadback-prompt-v2-wire', adapter_version: 'genuine-context-responses-v1',
  validator_version: 'strict-spans-v1+ordered-results-v1', is_fixture: false, execution_mode: 'genuine-context-capacity', execution_kind});
globalThis.fetch = async (path, options = {}) => {
  if (failNext) { failNext = false; throw new TypeError('Synthetic transport interruption'); }
  if (path === '/api/bootstrap') {
    if (!releaseInitialBootstrap) return new Promise(resolve => { releaseInitialBootstrap = () => resolve(response({csrf_token: 'synthetic-token', catalog, checkout})); });
    return response({csrf_token: 'synthetic-token', catalog, checkout});
  }
  const payload = JSON.parse(options.body); requests.push({path, payload, headers: options.headers});
  assert.equal(payload.expected_revision, revision);
  assert.equal(options.headers['X-CSRF-Token'], 'synthetic-token');
  if (path === '/api/analyze') {
    checkout = {review_id: `r${revision}`, state: 'REVIEW_REQUIRED', sku_id: payload.sku_id, snapshot_hash: 'b'.repeat(64),
      source, amount: {minor: 7900, currency: 'USD'}, model: {is_fixture: true}, confirmation_id: null, order: null,
      conditions: payload.conditions.map((condition, index) => ({condition_id: `c${index + 1}`, ...condition}))};
    if (envelopeMode === 'mixed') {
      checkout.model = contextModel(activeProviders.analysis.execution_kind);
      checkout.analysis = {strategy: 'context-capacity-v1', dispatch_state: 'attempted', accounting_state: 'known', usage_observed: true,
        evidence_kind: activeProviders.analysis.execution_kind === 'fabricated-offline' ? 'fabricated-offline' : 'provider-observation'};
    }
    checkout.results = checkout.conditions.map(condition => ({condition_id: condition.condition_id, status: 'match', explanation: 'Explicit synthetic description.',
      evidence: [{source_id: source.source_id, start: 8, end: 17, quote: 'UK QWERTY'}]}));
  } else if (path === '/api/confirm') {
    assert.equal(payload.confirmed_sku_id, checkout.sku_id); checkout.state = 'SNAPSHOT_CONFIRMED'; checkout.confirmation_id = 'confirm1';
  } else if (path === '/api/orders') {
    assert.match(options.headers['Idempotency-Key'], /^[\da-f-]{36}$/i);
    checkout.state = 'ORDER_CREATED'; checkout.order = {order_id: 'local1', provider_order_id: 'FIXTURE-1', provider_mode: 'fixture', status: 'CREATED', approval_url: null};
  } else if (path.endsWith('/fixture-approve')) checkout.state = 'PAYPAL_APPROVED';
  else if (path.endsWith('/verify')) checkout.state = 'SERVER_RECHECKED';
  else if (path.endsWith('/capture')) {
    assert.equal(payload.final_confirmation, true); assert.equal(payload.confirmation_id, 'confirm1');
    assert.match(options.headers['Idempotency-Key'], /^[\da-f-]{36}$/i); checkout.state = 'COMPLETED'; checkout.order.status = 'COMPLETED';
  } else if (path.endsWith('/reconcile')) checkout.state = 'PAYMENT_UNKNOWN';
  else throw new Error(`Unexpected fixture route ${path}`);
  revision += 1; return response({checkout});
};
const $ = id => document.getElementById(id);
const flush = async () => { for (let i = 0; i < 4; i += 1) await new Promise(resolve => setImmediate(resolve)); };
const change = (id, value, checked) => { const element = $(id); if (value !== undefined) element.value = value; if (checked !== undefined) element.checked = checked; element.dispatch('change'); };
const orderButton = action => elements().find(element => element.dataset.orderAction === action);
await import('./app.mjs');
await flush();

test('initial delayed bootstrap is configuration-unestablished, never fixture or no-charge evidence', async () => {
  assert.match(html, /id="mode-label">Loading provider configuration/);
  assert.match(html, /id="mode-notice">Configuration is not established/);
  assert.match(html, /id="analysis-label"[^>]*>Analysis configuration is not established/);
  assert.match($('mode-label').textContent, /unestablished/);
  assert.match($('mode-notice').textContent, /actions are paused/);
  assert.doesNotMatch($('analysis-label').textContent, /Scripted|no model call/);
  assert.equal($('analyze').disabled, true);
  releaseInitialBootstrap(); await flush();
  assert.equal($('mode-label').textContent, 'Fixture mode · sample shop');
});

test('app fixture workflow, stale consent, final intent, recovery and uncertainty guards', async () => {
  assert.equal($('catalog-rows').children.length, 6);
  assert.equal($('analyze').disabled, true, 'no inferred default product or conditions');
  assert.equal($('review-section').hidden, true);
  const radios = document.querySelectorAll('input[name="sku"]');
  radios[0].checked = true; radios[0].dispatch('change');
  assert.equal($('catalog-source').hidden, false);
  assert.equal($('catalog-source-text').textContent, source.text, 'non-AI baseline can inspect the identical original source before analysis');
  change('want-layout', undefined, true);
  assert.equal($('analyze').disabled, false);
  $('conditions-form').dispatch('submit'); await flush();
  assert.equal($('review-section').hidden, false);
  assert.equal($('review-heading'), document.activeElement);
  assert.equal($('confirm').disabled, true);
  assert.equal($('source-text').textContent, source.text, 'catalog injection stays plain text');
  assert.equal(elements().filter(element => element.tagName === 'script').length, 0, 'no script element is created from catalog text');
  change('confirm-snapshot', undefined, true);
  assert.equal($('confirm').disabled, false);
  change('want-cable', undefined, true);
  assert.equal($('review-section').hidden, true, 'unsent condition change removes previous review');
  assert.equal($('confirm-snapshot').checked, false, 'consent immediately revoked');
  $('conditions-form').dispatch('submit'); await flush();
  // Invalid model output can be shown as blocked, then explicitly reanalyzed.
  checkout.state = 'ANALYSIS_BLOCKED'; checkout.snapshot_hash = null; checkout.results = [];
  $('reload').click(); await flush();
  assert.equal($('review-blocked').hidden, false);
  assert.equal($('snapshot').hidden, true);
  assert.equal($('analyze').disabled, false);
  $('conditions-form').dispatch('submit'); await flush();
  // A catalog refresh clears the obsolete pre-order review without stranding the buyer.
  checkout.stale = true; checkout.source = {...source, text: 'Obsolete source text'};
  $('reload').click(); await flush();
  assert.equal($('review-section').hidden, true);
  assert.equal($('analyze').disabled, false);
  assert.match($('status').textContent, /description or price changed/);
  $('conditions-form').dispatch('submit'); await flush();
  change('confirm-snapshot', undefined, true); $('confirm').click(); await flush();
  assert.equal($('order-section').hidden, false);
  assert.equal($('confirm').hidden, true, 'saved confirmation displayed separately, not an editable unchecked box');
  orderButton('create').click(); orderButton('create').click(); await flush();
  assert.equal(requests.filter(request => request.path === '/api/orders').length, 1, 'busy gate prevents double dispatch');
  assert.equal($('want-layout').disabled, true, 'existing order freezes edits');
  orderButton('approve').click(); await flush();
  assert.equal(requests.some(request => request.path.endsWith('/capture')), false, 'approval never captures');
  orderButton('verify').click(); await flush();
  assert.equal($('capture').disabled, true);
  change('final-capture', undefined, true);
  assert.equal($('capture').disabled, false);
  $('capture').click(); $('capture').click(); await flush();
  assert.equal(requests.filter(request => request.path.endsWith('/capture')).length, 1);
  assert.match($('order-state').textContent, /not a payment/);
  assert.equal($('order-controls').children.length, 0);
  assert.equal(storedKeys.size, 2);
  assert.ok(requests.every(request => request.path.startsWith('/api/')));
  assert.ok(requests.every(request => !Object.hasOwn(request.payload, 'amount')));
  // Bootstrap recovers the current checkout instead of inventing a fresh operation.
  $('reload').click(); await flush();
  assert.match($('order-state').textContent, /not a payment/);
  assert.equal($('analyze').disabled, true);
  // Explicit unknown result retains same-order reconciliation only.
  checkout.state = 'PAYMENT_UNKNOWN'; $('reload').click(); await flush();
  assert.equal(orderButton('create'), undefined);
  assert.equal(orderButton('capture'), undefined);
  assert.ok(orderButton('reconcile'));
  // A stale post-order version remains visible and keeps only same-order reconciliation.
  checkout.stale = true; checkout.confirmation_id = null; checkout.source = {...source, revision: 2};
  $('reload').click(); await flush();
  assert.equal($('source-changed').hidden, false);
  assert.equal($('order-section').hidden, false);
  assert.equal($('confirm').hidden, true);
  assert.equal($('analyze').disabled, true);
  assert.ok(orderButton('reconcile'));
  assert.equal(orderButton('create'), undefined);
  // A transport interruption pauses all mutation controls until a read succeeds.
  failNext = true; orderButton('reconcile').click(); await flush();
  assert.equal($('error-summary').hidden, false);
  assert.equal(orderButton('reconcile').disabled, true);
  assert.match($('error-message').textContent, /paused/);
  $('reload').click(); await flush();
  assert.equal(orderButton('reconcile').disabled, false);
});


test('partial HTTP response body retains deadline, pauses mutation and allows state reload', async () => {
  const mockedFetch = globalThis.fetch;
  const sockets = new Set();
  let dispatched = 0;
  const server = createServer((request, response) => {
    if (request.url === '/warm') { response.end('fixture warmup'); return; }
    dispatched += 1;
    request.resume();
    response.writeHead(200, {'Content-Type': 'application/json'});
    response.flushHeaders();
    response.write('{"api_version":'); // Deliberately never finish this fixture body.
  });
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  // Warm native Fetch before the short deadline so headers arrive before it.
  await (await nativeFetch(`${origin}/warm`)).text();
  let responseSignal;
  // Accelerate only the app deadline; use real native Fetch/AbortController/body parsing.
  globalThis.setTimeout = (callback, milliseconds, ...args) => nativeSetTimeout(callback, milliseconds === 15000 ? 40 : milliseconds, ...args);
  globalThis.fetch = (path, options) => {
    responseSignal = options.signal;
    return nativeFetch(`${origin}${path}`, options);
  };
  try {
    orderButton('reconcile').click();
    await new Promise(resolve => nativeSetTimeout(resolve, 200));
    assert.equal(dispatched, 1, 'no replay after a partial response');
    assert.equal(responseSignal.aborted, true, 'deadline covers the response body, not just headers');
    assert.equal($('error-summary').hidden, false);
    assert.match($('error-message').textContent, /paused/);
    assert.equal($('reload').disabled, false, 'authoritative reload remains reachable after timeout');
    assert.equal(orderButton('reconcile').disabled, true, 'uncertain mutation cannot be replayed');
    globalThis.fetch = mockedFetch;
    $('reload').click(); await flush();
    assert.equal(orderButton('reconcile').disabled, false);
    assert.equal(orderButton('create'), undefined, 'recovery retains the same existing order');
    assert.equal(dispatched, 1);
  } finally {
    globalThis.fetch = mockedFetch;
    globalThis.setTimeout = nativeSetTimeout;
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  }
});


test('C12 unavailable analysis keeps baseline readable without sending an attempt', async () => {
  envelopeMode = 'mixed'; activeProviders = contextProviders('unavailable', false); checkout = null;
  $('reload').click(); await flush();
  document.querySelectorAll('input[name="sku"]')[0].dispatch('change');
  change('want-layout', undefined, true);
  assert.equal($('catalog-source-text').textContent, source.text);
  assert.equal($('analyze').disabled, true);
  const before = requests.length;
  $('conditions-form').dispatch('submit'); await flush();
  assert.equal(requests.length, before, 'even a submitted disabled form sends no analysis');
  assert.match($('analysis-label').textContent, /dispatch unavailable/);
  assert.match($('mode-notice').textContent, /may incur API charges/);
  assert.doesNotMatch($('mode-notice').textContent, /No money moves|connected checkout/);
});
test('C12 fabricated analysis labels usage honestly through explicit simulated checkout', async () => {
  activeProviders = contextProviders(); $('reload').click(); await flush();
  const first = document.querySelectorAll('input[name="sku"]')[0]; first.checked = true; first.dispatch('change');
  change('want-layout', undefined, true);
  const before = requests.length;
  $('conditions-form').dispatch('submit'); $('conditions-form').dispatch('submit'); await flush();
  assert.equal(requests.length, before + 1, 'repeated analyze submits claim once');
  assert.equal($('review-heading'), document.activeElement);
  assert.match($('suggestion-label').textContent, /Fabricated offline usage recorded; not a provider observation/);
  assert.match($('suggestion-label').textContent, /does not validate/);
  assert.equal($('analysis-badge').textContent, 'Fabricated offline');
  assert.match($('scope-label').textContent, /simulated checkout/);
  assert.doesNotMatch($('scope-label').textContent, /offline only/);
  change('confirm-snapshot', undefined, true); $('confirm').click(); await flush();
  assert.match($('payment-label').textContent, /no checkout payment/);
  assert.doesNotMatch($('payment-label').textContent, /No money moves/);
  orderButton('create').click(); await flush();
  orderButton('approve').click(); await flush();
  orderButton('verify').click(); await flush();
  assert.equal($('capture').disabled, true, 'known usage does not grant final payment intent');
  change('final-capture', undefined, true); $('capture').click(); await flush();
  assert.match($('order-help').textContent, /Analysis API charges are separate/);
  assert.doesNotMatch($('order-help').textContent, /no money moved/);
});
test('C12 historical context order stays readable under a current fixture configuration', async () => {
  checkout.stale = true; checkout.confirmation_id = null; checkout.state = 'PAYMENT_UNKNOWN';
  envelopeMode = 'fixture'; activeProviders = undefined;
  $('reload').click(); await flush();
  assert.equal($('error-summary').hidden, true);
  assert.match($('mode-label').textContent, /Previous context review/);
  assert.match($('analysis-label').textContent, /Scripted fixture analysis is configured now/);
  assert.match($('suggestion-label').textContent, /Fabricated offline usage/);
  assert.equal($('analyze').disabled, true);
  assert.ok(orderButton('reconcile'));
  assert.equal(orderButton('capture'), undefined);
  assert.equal(orderButton('create'), undefined);
});
test('C12 UNKNOWN usage survives reload and selection change without retry or confirmation', async () => {
  envelopeMode = 'mixed'; activeProviders = contextProviders();
  checkout = {...checkout, stale: false, state: 'ANALYSIS_BLOCKED', snapshot_hash: null, confirmation_id: null, order: null, results: [],
    analysis: {...checkout.analysis, accounting_state: 'unknown'}};
  $('reload').click(); await flush();
  assert.equal($('snapshot').hidden, true);
  assert.match($('suggestion-label').textContent, /Fabricated offline usage/);
  assert.match($('analysis-label').textContent, /UNKNOWN accounting/);
  assert.equal($('analyze').disabled, true);
  const before = requests.length;
  change('want-cable', undefined, true);
  assert.equal($('analyze').disabled, true);
  assert.match($('status').textContent, /remains held by UNKNOWN/);
  $('conditions-form').dispatch('submit'); await flush();
  assert.equal(requests.length, before);
  $('reload').click(); await flush();
  assert.match($('suggestion-label').textContent, /UNKNOWN; capacity stays held/);
});
test('C12 configured provider capability does not claim a call, observation or connected payment', async () => {
  checkout = null; activeProviders = contextProviders('provider-runtime');
  $('reload').click(); await flush();
  assert.match($('analysis-label').textContent, /Availability does not prove a call/);
  assert.match($('suggestion-label').textContent, /No owned analysis attempt/);
  assert.equal($('analysis-badge').textContent, 'No usage observed');
  assert.match($('mode-notice').textContent, /may incur API charges/);
  assert.match($('payment-label').textContent, /PayPal is unconnected/);
  assert.equal($('review-section').hidden, true);
});
test('C12 stale async analysis response cannot restore invalidated review consent', async () => {
  activeProviders = contextProviders(); $('reload').click(); await flush();
  const radio = document.querySelectorAll('input[name="sku"]')[0]; radio.checked = true; radio.dispatch('change');
  change('want-layout', undefined, true);
  const original = globalThis.fetch; let finish;
  globalThis.fetch = async (...args) => { await new Promise(resolve => { finish = resolve; }); return original(...args); };
  try {
    $('conditions-form').dispatch('submit');
    change('want-cable', undefined, true); // A newer client selection wins, even during interruption.
    finish(); await flush();
    assert.equal($('review-section').hidden, true);
    assert.equal($('confirm-snapshot').checked, false);
    assert.equal($('confirm').disabled, true);
    assert.match($('status').textContent, /Selection changed during the request/);
  } finally { globalThis.fetch = original; }
});
test('C12 unsupported envelope and server-private error text fail closed without exposing identifiers', async () => {
  checkout = null; activeProviders = contextProviders(); $('reload').click(); await flush();
  document.querySelectorAll('input[name="sku"]')[0].dispatch('change'); change('want-layout', undefined, true);
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ok: false, status: 503, json: async () => ({api_version: '1', mode: 'mixed', providers: activeProviders,
    revision, error: {code: 'PRIVATE-request-id', message: 'private-project/private-approval/private-credential'}})});
  try {
    $('conditions-form').dispatch('submit'); await flush();
    assert.equal($('analyze').disabled, true);
    assert.match($('error-message').textContent, /request was refused/);
    assert.doesNotMatch($('error-message').textContent, /private-|PRIVATE/);
  } finally { globalThis.fetch = original; }
  activeProviders = {...contextProviders(), network_enabled: true};
  $('reload').click(); await flush();
  assert.equal($('analyze').disabled, true);
  assert.match($('error-message').textContent, /Unsupported provider or network mode/);
  assert.match($('mode-label').textContent, /unestablished/);
  assert.match($('mode-notice').textContent, /actions are paused/);
  assert.doesNotMatch($('analysis-label').textContent, /available\./);
});

test('C12 legacy order is a previous fixture review, not a new context observation', async () => {
  activeProviders = contextProviders();
  checkout = {review_id: 'legacy-review', state: 'PAYMENT_UNKNOWN', sku_id: 'KB-UK', snapshot_hash: 'b'.repeat(64),
    source, amount: {minor: 7900, currency: 'USD'}, model: {is_fixture: true}, confirmation_id: null, stale: true,
    order: {order_id: 'legacy-order', provider_order_id: 'FIXTURE-OLD', provider_mode: 'fixture'},
    conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'}],
    results: [{condition_id: 'c1', status: 'match', explanation: 'Previous fixture.',
      evidence: [{source_id: source.source_id, start: 8, end: 17, quote: 'UK QWERTY'}]}]};
  $('reload').click(); await flush();
  assert.equal($('error-summary').hidden, true);
  assert.match($('suggestion-label').textContent, /Previous scripted fixture suggestions/);
  assert.equal($('analysis-badge').textContent, 'Previous offline review');
  assert.equal($('confirm').hidden, true);
  assert.equal(orderButton('create'), undefined);
  assert.equal(orderButton('capture'), undefined);
  assert.ok(orderButton('reconcile'));
});

test('C12 UNKNOWN history keeps analysis held after returning to default fixture', async () => {
  envelopeMode = 'fixture'; activeProviders = undefined;
  checkout = {...checkout, state: 'ANALYSIS_BLOCKED', snapshot_hash: null, order: null, results: [],
    model: contextModel('fabricated-offline'),
    analysis: {strategy: 'context-capacity-v1', dispatch_state: 'attempted', accounting_state: 'unknown',
      usage_observed: true, evidence_kind: 'fabricated-offline'}};
  $('reload').click(); await flush();
  change('want-layout', undefined, true);
  assert.equal($('analyze').disabled, true);
  const before = requests.length;
  $('conditions-form').dispatch('submit'); await flush();
  assert.equal(requests.length, before);
});


test('C12 unobserved pending accounting cannot be retried after reload', async () => {
  envelopeMode = 'mixed'; activeProviders = contextProviders();
  checkout = {...checkout, stale: false, analysis: {...checkout.analysis,
    accounting_state: 'unobserved', usage_observed: false, evidence_kind: 'none'}};
  $('reload').click(); await flush();
  assert.equal($('analyze').disabled, true);
  assert.match($('analysis-label').textContent, /unobserved/);
  assert.doesNotMatch($('analysis-label').textContent, /UNKNOWN/);
  const before = requests.length;
  change('want-cable', undefined, true); $('conditions-form').dispatch('submit'); await flush();
  assert.equal(requests.length, before);
  assert.match($('status').textContent, /remains unobserved/);
});


test('C12 stale no-order context accounting remains visible without reviving obsolete consent', async () => {
  for (const [kind, evidence] of [['provider-runtime', 'provider-observation'], ['fabricated-offline', 'fabricated-offline']]) {
    envelopeMode = 'fixture'; activeProviders = undefined;
    checkout = {review_id: 'old-context', state: 'ANALYSIS_BLOCKED', sku_id: 'KB-UK',
      snapshot_hash: null, confirmation_id: null, order: null, results: [], stale: true,
      source: {...source, text: 'Obsolete source is not restored'}, amount: {minor: 7900, currency: 'USD'},
      conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'}], model: contextModel(kind),
      analysis: {strategy: 'context-capacity-v1', dispatch_state: 'attempted', accounting_state: 'unknown',
        usage_observed: true, evidence_kind: evidence}};
    $('reload').click(); await flush();
    assert.equal($('error-summary').hidden, true);
    assert.match($('mode-label').textContent, /Previous context review/);
    assert.match($('analysis-label').textContent, /Scripted fixture analysis is configured now/);
    assert.equal($('analysis-history').hidden, false);
    assert.match($('analysis-history').textContent, /UNKNOWN; capacity stays held/);
    assert.match($('analysis-history').textContent, kind === 'provider-runtime' ? /Provider usage recorded/ : /Fabricated offline usage/);
    assert.doesNotMatch($('mode-notice').textContent, /No real AI inference|No money moves/);
    assert.equal($('review-section').hidden, true);
    assert.equal($('order-section').hidden, true);
    assert.equal($('confirm-snapshot').checked, false);
    assert.equal($('confirm').disabled, true);
    assert.equal($('analyze').disabled, true);
    const before = requests.length;
    change('want-cable', undefined, true); $('conditions-form').dispatch('submit'); await flush();
    assert.equal(requests.length, before);
    assert.equal($('analysis-history').hidden, false, 'selection does not erase retained accounting');
  }
});

test('C12 late response keeps UNKNOWN accounting even after a newer selection', async () => {
  envelopeMode = 'mixed'; activeProviders = contextProviders(); checkout = null;
  $('reload').click(); await flush();
  document.querySelectorAll('input[name="sku"]')[0].dispatch('change'); change('want-layout', undefined, true);
  const original = globalThis.fetch; let finish;
  globalThis.fetch = async (...args) => {
    await new Promise(resolve => { finish = resolve; });
    await original(...args);
    checkout = {...checkout, state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: [],
      analysis: {...checkout.analysis, accounting_state: 'unknown'}};
    return response({checkout});
  };
  try {
    $('conditions-form').dispatch('submit'); change('want-cable', undefined, true); finish(); await flush();
    assert.equal($('review-section').hidden, true);
    assert.equal($('analysis-history').hidden, false);
    assert.match($('analysis-history').textContent, /UNKNOWN/);
    assert.equal($('analyze').disabled, true);
    assert.equal($('confirm-snapshot').checked, false);
  } finally { globalThis.fetch = original; }
});
