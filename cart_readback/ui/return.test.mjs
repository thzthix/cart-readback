/** Minimal DOM only; no native browser or genuine PayPal/network claim. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
function harness() {
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

return {storedKeys, elements, $: id => document.getElementById(id)};
}
const flush = async () => { for (let i = 0; i < 6; i += 1) await new Promise(resolve => setImmediate(resolve)); };
const providers = {analysis: {mode: 'injected-offline', is_fixture: false}, payment: {mode: 'paypal-sandbox-offline', is_fixture: false}, network_enabled: false};
const id = '11111111-1111-4111-8111-111111111111';
const secret = 's'.repeat(43);
const query = `?order_id=${id}&state=${secret}&outcome=approved&token=REMOTE1`;
let sequence = 0;
async function launch(search = query, patch = {}) {
  const ui = harness();
  const events = new Map();
  globalThis.addEventListener = (type, fn) => events.set(type, fn);
  globalThis.location = {pathname: '/payment-return', search, hash: ''};
  const stripped = [];
  globalThis.history = {replaceState: (value, unused, url) => {
    assert.equal(value, null); stripped.push(url); globalThis.location.search = '';
  }};
  const source = {source_id: 'source', revision: 1, sha256: 'a'.repeat(64), text: 'UK QWERTY'};
  const product = {sku_id: 'KB', name: 'Keyboard', price_minor: 7900, currency: 'USD', source, baseline: {layout: 'UK_QWERTY', included_cable: 'unknown'}};
  const catalog = [product, ...Array.from({length: 5}, (_, i) => ({...product, sku_id: `KB${i}`}))];
  let checkout = {review_id: 'review', snapshot_hash: 'b'.repeat(64), state: 'ORDER_CREATED', sku_id: 'KB', source,
    model: {is_fixture: false}, amount: {minor: 7900, currency: 'USD'}, confirmation_id: 'confirmation',
    conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'}],
    results: [{condition_id: 'c1', status: 'match', explanation: 'Exact', evidence: [{source_id: 'source', start: 0, end: 9, quote: 'UK QWERTY'}]}],
    order: {order_id: id, provider_order_id: 'REMOTE1', provider_mode: 'paypal-sandbox-offline',
      approval_url: 'https://www.sandbox.paypal.com/checkoutnow?token=REMOTE1',
      buyer_return: {available: true, consumed: false, cancelled: false, expires_at: '2099-01-01T00:00:00Z'}}, ...patch};
  let revision = 3;
  const requests = [];
  const transport = {fail: false};
  globalThis.fetch = async (path, options = {}) => {
    assert.equal(stripped.length > 0, true, 'query stripped before bootstrap');
    assert.equal(path.startsWith('/api/'), true, 'no external fetch');
    if (options.method === 'POST') {
      const body = JSON.parse(options.body); requests.push({path, body});
      if (transport.fail) { transport.fail = false; throw new Error('Interrupted return response'); }
      assert.equal(options.headers['X-CSRF-Token'], 'csrf');
      assert.equal(body.expected_revision, revision);
      if (path.endsWith('/buyer-return')) {
        assert.equal(body.return_state, secret); assert.equal(body.provider_order_id, 'REMOTE1');
        checkout.order.buyer_return.consumed = true;
        if (body.outcome === 'cancelled') checkout.order.buyer_return.cancelled = true;
        else checkout.state = 'SERVER_RECHECKED';
      } else if (path.endsWith('/capture')) checkout.state = 'COMPLETED';
      else if (path.endsWith('/verify')) checkout.state = 'SERVER_RECHECKED';
      else throw Error(`Unexpected route ${path}`);
      revision += 1;
    }
    return {ok: true, json: async () => structuredClone({api_version: '1', mode: 'offline', providers, revision, csrf_token: 'csrf', catalog, checkout})};
  };
  await import(`./app.mjs?return-test=${++sequence}`); await flush();
  return {...ui, requests, stripped, events, transport, button: action => ui.elements().find(e => e.dataset.orderAction === action)};
}
test('offline return strips secrets, requires explicit recheck and fresh final confirmation, never navigates', async () => {
  const ui = await launch();
  assert.deepEqual(ui.stripped, ['/payment-return']);
  assert.equal(ui.requests.length, 0);
  assert.match(ui.$('analysis-label').textContent, /Injected-offline/);
  assert.match(ui.$('payment-label').textContent, /Fabricated PayPal/);
  assert.equal(ui.elements().some(e => (e.href || '').includes('paypal')), false);
  assert.equal(ui.button('approve'), undefined);
  assert.equal(ui.storedKeys.size, 0);
  ui.button('buyer-return').click(); ui.button('buyer-return').click(); await flush();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.button('buyer-return'), undefined);
  assert.equal(ui.$('capture').disabled, true);
  ui.$('final-capture').checked = true; ui.$('final-capture').dispatch('change');
  assert.equal(ui.$('capture').disabled, false);
  ui.events.get('pageshow')({persisted: true}); await flush();
  assert.equal(ui.$('final-capture').checked, false);
  assert.equal(ui.$('capture').disabled, true);
  ui.events.get('popstate')({}); await flush();
  assert.equal(ui.requests.length, 1, 'history and BFCache never POST');
  assert.equal(ui.storedKeys.size, 0, 'no return secret persisted');
  assert.equal(ui.elements().some(e => e.textContent.includes(secret)), false);
  ui.$('final-capture').checked = true; ui.$('final-capture').dispatch('change');
  ui.$('capture').click(); ui.$('capture').click(); await flush();
  assert.equal(ui.requests.filter(r => r.path.endsWith('/capture')).length, 1);
  assert.equal(ui.requests[1].body.final_confirmation, true);
  assert.equal(Object.hasOwn(ui.requests[1].body, 'return_state'), false);
  assert.match(ui.$('order-state').textContent, /not a payment/);
});
test('cancellation records local return only and retains same order with verify, never fixture approval', async () => {
  const ui = await launch(query.replace('approved', 'cancelled'));
  ui.button('buyer-return').click(); await flush();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0].body.outcome, 'cancelled');
  assert.match(ui.$('order-details').textContent, /Cancellation recorded/);
  assert.ok(ui.button('verify')); assert.equal(ui.button('approve'), undefined); assert.equal(ui.button('capture'), undefined);
  assert.equal(ui.button('create'), undefined);
});
test('invalid, missing, foreign and stale returns fail closed without POST', async () => {
  for (const [search, patch] of [[query + '&token=REMOTE1', {}], ['?', {}], [query.replace('REMOTE1', 'OTHER'), {}], [query, {stale: true}]]) {
    const ui = await launch(search, patch);
    assert.equal(ui.requests.length, 0);
    assert.equal(ui.$('error-summary').hidden, false);
    assert.equal(ui.button('buyer-return'), undefined);
    assert.equal(ui.$('analyze').disabled, true);
    assert.equal(ui.storedKeys.size, 0);
  }
});

test('interrupted return POST cannot replay after reload or history restoration', async () => {
  const ui = await launch();
  ui.transport.fail = true;
  ui.button('buyer-return').click(); await flush();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.$('error-summary').hidden, false);
  ui.button('buyer-return').click(); await flush();
  assert.equal(ui.requests.length, 1);
  ui.$('reload').click(); await flush();
  assert.equal(ui.button('buyer-return'), undefined);
  assert.ok(ui.button('verify'));
  ui.events.get('pageshow')({persisted: true}); await flush();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.button('create'), undefined);
  assert.equal(ui.button('capture'), undefined);
});

test('hard reload on stripped return route restores same order without replay or capture', async () => {
  const ui = await launch('');
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.$('error-summary').hidden, true);
  assert.equal(ui.button('buyer-return'), undefined);
  assert.ok(ui.button('verify'));
  assert.equal(ui.button('capture'), undefined);
  assert.equal(ui.button('create'), undefined);
  assert.equal(ui.storedKeys.size, 0);
  assert.match(ui.$('order-details').textContent, new RegExp(id));
});

test('explicit reload discards malformed return and recovers authoritative order without POST', async () => {
  const ui = await launch(query + '&token=REMOTE1');
  assert.equal(ui.$('error-summary').hidden, false);
  assert.equal(ui.$('analyze').disabled, true);
  assert.equal(ui.requests.length, 0);
  ui.$('reload').click(); await flush();
  assert.equal(ui.$('error-summary').hidden, true);
  assert.equal(ui.button('buyer-return'), undefined);
  assert.ok(ui.button('verify'));
  assert.equal(ui.button('verify').disabled, false);
  assert.equal(ui.button('capture'), undefined);
  assert.equal(ui.button('create'), undefined);
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.storedKeys.size, 0);
  assert.match(ui.$('order-details').textContent, new RegExp(id));
});
