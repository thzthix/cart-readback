import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {validateViewer} from './viewer-core.mjs';
import {renderViewer, start} from './viewer.mjs';
const source = {source_id: 'catalog:KB-UK', revision: 1, sha256: 'a'.repeat(64), text: 'UK QWERTY <script>unsafe()</script>'};
function fixture() {
  return {api_version: '1', mode: 'mixed', revision: 1, notice: 'Host-configured analysis; fixture payments.',
    viewer: {version: 'gemini-host-result-viewer-v1', review_only: true, configured_model: 'gemini-2.5-flash-lite', expected_model_version: 'gemini-2.5-flash-lite-001'},
    providers: {analysis: {mode: 'genuine-gemini-capacity', is_fixture: false, dispatch_available: true, execution_kind: 'fabricated-offline'}, payment: {mode: 'fixture', is_fixture: true}, network_enabled: false},
    catalog: [{sku_id: 'KB-UK', name: 'Synthetic keyboard', price_minor: 7900, currency: 'USD', quantity: 1, catalog_revision: 1, source, baseline: {layout: 'UK_QWERTY', included_cable: 'unknown'}}],
    checkout: {review_id: 'review', state: 'REVIEW_REQUIRED', sku_id: 'KB-UK', source, amount: {minor: 7900, currency: 'USD'}, snapshot_hash: 'b'.repeat(64), confirmation_id: null, order: null,
      conditions: [{condition_id: 'c1', kind: 'layout', value: 'UK_QWERTY'}],
      results: [{condition_id: 'c1', status: 'match', explanation: 'Synthetic match', evidence: [{source_id: source.source_id, start: 0, end: 9, quote: 'UK QWERTY'}]}],
      model: {provider: 'google-gemini-generate-content', model_version: 'gemini-2.5-flash-lite', prompt_version: 'cartreadback-prompt-v2-wire', adapter_version: 'genuine-gemini-generation-v1', validator_version: 'strict-spans-v1+ordered-results-v1', is_fixture: false, execution_mode: 'genuine-gemini-capacity', execution_kind: 'fabricated-offline'},
      analysis: {strategy: 'gemini-capacity-v1', dispatch_state: 'attempted', accounting_state: 'known', usage_observed: true, evidence_kind: 'fabricated-offline'}}};
}
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  set innerHTML(_) { throw new Error('HTML injection'); }
}
function dom() { const nodes = new Map(['viewer-content', 'viewer-status'].map(id => [id, new Element('div')])); return {readyState: 'complete', createElement: tag => new Element(tag), getElementById: id => nodes.get(id)}; }
const flatten = n => [n, ...n.children.flatMap(flatten)];
const response = data => ({ok: true, json: async () => data});
test('exact Gemini contract accepts both configured models, null and expired history', () => {
  assert.equal(validateViewer(fixture()).checkout.analysis.evidence_kind, 'fabricated-offline');
  const d = fixture(); d.viewer.configured_model = d.checkout.model.model_version = 'gemini-3.5-flash-lite'; d.viewer.expected_model_version = 'gemini-3.5-flash-lite'; validateViewer(d);
  d.providers.analysis.dispatch_available = false; d.checkout.stale = true; validateViewer(d);
  d.checkout = null; validateViewer(d);
});
test('provider/model/version/adapter/accounting contradictions fail closed', () => {
  const changes = [d => d.mode = 'fixture', d => d.csrf_token = 'forbidden', d => d.viewer.review_only = false,
    d => d.viewer.expected_model_version = 'gemini-3.5-flash-lite', d => d.viewer.configured_model = 'gpt-6-luna',
    d => d.providers.network_enabled = true, d => d.providers.payment.mode = 'paypal-sandbox-offline',
    d => d.providers.analysis.execution_kind = 'unavailable', d => d.checkout.model.provider = 'openai-responses',
    d => d.checkout.model.model_version = 'gemini-3.5-flash-lite', d => d.checkout.model.adapter_version = 'other',
    d => d.checkout.model.prompt_version = 'other', d => d.checkout.model.validator_version = 'other',
    d => d.checkout.analysis.strategy = 'context-capacity-v1', d => d.checkout.analysis.evidence_kind = 'provider-observation',
    d => d.checkout.analysis.usage_observed = false, d => d.checkout.analysis.dispatch_state = 'not-attempted',
    d => d.checkout.analysis.accounting_state = 'unknown', d => d.checkout.order = {}, d => d.checkout.confirmation_id = 'yes',
    d => d.checkout.results[0].evidence[0].quote = 'not source', d => d.checkout.results.push(d.checkout.results[0])];
  for (const change of changes) { const d = structuredClone(fixture()); change(d); assert.throws(() => validateViewer(d)); }
});
test('blocked UNKNOWN and late usage remain visible, stale source explicitly historical', () => {
  const d = structuredClone(fixture()); d.checkout.state = 'ANALYSIS_BLOCKED'; d.checkout.snapshot_hash = null; d.checkout.results = []; d.checkout.analysis.accounting_state = 'unknown';
  d.checkout.stale = true; d.catalog[0].source.text = 'New current source';
  const document = dom(); renderViewer(d, document);
  const all = flatten(document.getElementById('viewer-content')); const text = all.map(x => x.textContent).join(' ');
  assert.match(text, /UNKNOWN is retained/); assert.match(text, /STALE historical/); assert.match(text, /Historical source/);
  assert.equal(all.some(x => ['button', 'input', 'form', 'select', 'a'].includes(x.tag)), false);
});
test('render source only as text with honest configuration and fabricated evidence', () => {
  const document = dom(); renderViewer(fixture(), document); const text = flatten(document.getElementById('viewer-content')).map(x => x.textContent).join(' ');
  assert.match(text, /<script>unsafe\(\)<\/script>/); assert.match(text, /Fabricated offline/); assert.match(text, /not proof of a call/); assert.match(text, /not exposed/); assert.match(text, /Inference may incur charges/);
});
test('redemption precedes bootstrap and does not forge browser headers', async () => {
  const calls = []; await start('x'.repeat(43), {document: dom(), fetch: async (url, options) => { calls.push({url, options}); return response(fixture()); }});
  assert.deepEqual(calls.map(x => x.url), ['/gemini-viewer/api/redeem', '/gemini-viewer/api/bootstrap']);
  assert.deepEqual(calls[0].options.headers, {'Content-Type': 'application/json'});
  assert.equal(calls[0].options.credentials, 'same-origin'); assert.deepEqual(JSON.parse(calls[0].options.body), {launch_capability: 'x'.repeat(43)});
});
test('reload only reads, failures never retry or proceed after uncertain redemption', async () => {
  for (const mode of ['reload', 'network', 'denied', 'invalid']) {
    const calls = []; const document = dom(); await start(mode === 'reload' ? null : mode === 'invalid' ? 'bad' : 'x'.repeat(43), {document, fetch: async url => { calls.push(url); if (mode === 'network') throw new Error('private detail'); if (mode === 'denied') return {ok: false}; return response(fixture()); }});
    assert.deepEqual(calls, mode === 'reload' ? ['/gemini-viewer/api/bootstrap'] : mode === 'invalid' ? [] : ['/gemini-viewer/api/redeem']);
    assert.doesNotMatch(document.getElementById('viewer-status').textContent, /private detail/);
  }
});
const html = readFileSync(new URL('./viewer.html', import.meta.url), 'utf8');
const inline = html.match(/<script>([\s\S]*?)<\/script>/)[1];
test('first inline bootstrap strips capability before any module/asset request', async () => {
  const events = []; const code = inline.replace("import('/viewer.mjs')", "load('/viewer.mjs')");
  vm.runInNewContext(code, {location: {pathname: '/viewer', search: '', hash: '#launch=' + 'x'.repeat(43)}, history: {replaceState: (...args) => { assert.deepEqual(Array.from(args), [null, '', '/viewer']); events.push('strip'); }}, load: async () => { events.push('import'); return {start: c => { assert.equal(c, 'x'.repeat(43)); events.push('start'); }}; }});
  await Promise.resolve(); assert.deepEqual(events, ['strip', 'import', 'start']);
  assert.equal(/(?:src=|stylesheet|preload)/.test(html.split('<script>')[0]), false);
});
test('malformed fragments, query, wrong path and history failure cannot fetch', () => {
  for (const [pathname, search, hash, throws] of [['/viewer', '', '#launch=short'], ['/viewer', '?x=y', '#launch=' + 'x'.repeat(43)], ['/viewer', '', '#launch=' + 'x'.repeat(43) + '&extra=x'], ['/other', '', ''], ['/viewer', '', '#launch=' + 'x'.repeat(43), true]]) {
    let imports = 0; let stripped = 0;
    vm.runInNewContext(inline.replace("import('/viewer.mjs')", "load('/viewer.mjs')"), {location: {pathname, search, hash}, history: {replaceState: () => { stripped++; if (throws) throw new Error(); }}, load: () => { imports++; }});
    assert.equal(imports, 0); assert.equal(stripped, 1);
  }
});
test('clean reload imports without redemption capability', async () => {
  let observed = 'unset'; vm.runInNewContext(inline.replace("import('/viewer.mjs')", "load('/viewer.mjs')"), {location: {pathname: '/viewer', search: '', hash: ''}, history: {replaceState() {}}, load: async () => ({start: c => { observed = c; }})});
  await Promise.resolve(); assert.equal(observed, null);
});
test('UNKNOWN cannot retain a snapshot, consent, order or accepted proposal', () => {
  const blocked = () => {
    const d = structuredClone(fixture()); Object.assign(d.checkout, {state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: [], stale: true});
    d.checkout.analysis.accounting_state = 'unknown'; return d;
  };
  validateViewer(blocked());
  for (const change of [d => d.checkout.snapshot_hash = 'a'.repeat(64), d => d.checkout.confirmation_id = 'consent',
    d => d.checkout.order = {}, d => d.checkout.state = 'REVIEW_REQUIRED', d => d.checkout.results = fixture().checkout.results]) {
    const d = blocked(); change(d); assert.throws(() => validateViewer(d));
  }
});
test('historical fixture metadata and contradictory retained evidence fail closed', () => {
  for (const change of [d => { d.checkout.model.provider = 'fixture'; d.checkout.model.is_fixture = true; },
    d => d.checkout.model.execution_mode = 'fixture',
    d => d.checkout.analysis.evidence_kind = 'provider-observation',
    d => { d.checkout.model.execution_kind = 'provider-runtime'; d.checkout.analysis.evidence_kind = 'fabricated-offline'; }]) {
    const d = structuredClone(fixture()); d.checkout.stale = true; change(d); assert.throws(() => validateViewer(d));
  }
});
test('expired provider observations remain historical, including UNKNOWN late accounting', () => {
  const d = structuredClone(fixture()); d.providers.analysis.execution_kind = 'provider-runtime';
  d.providers.analysis.dispatch_available = false; d.providers.network_enabled = false;
  d.checkout.model.execution_kind = 'provider-runtime'; d.checkout.stale = true;
  d.checkout.analysis.evidence_kind = 'provider-observation';
  const document = dom(); renderViewer(d, document);
  assert.match(flatten(document.getElementById('viewer-content')).map(x => x.textContent).join(' '), /Provider usage recorded/);
  assert.equal(d.checkout.analysis.accounting_state, 'known');
  Object.assign(d.checkout, {state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: []});
  d.checkout.analysis.accounting_state = 'unknown'; renderViewer(d, document);
  const text = flatten(document.getElementById('viewer-content')).map(x => x.textContent).join(' ');
  assert.match(text, /Provider usage recorded/); assert.match(text, /UNKNOWN is retained/); assert.match(text, /STALE historical/);
  assert.equal(d.checkout.analysis.usage_observed, true); assert.equal(d.checkout.analysis.accounting_state, 'unknown');
});
test('exact public schemas reject extra fields at every displayed boundary', () => {
  const selectors = [d => d, d => d.viewer, d => d.providers, d => d.catalog[0], d => d.catalog[0].source,
    d => d.catalog[0].baseline, d => d.checkout, d => d.checkout.amount, d => d.checkout.model,
    d => d.checkout.analysis, d => d.checkout.conditions[0], d => d.checkout.results[0], d => d.checkout.results[0].evidence[0]];
  for (const select of selectors) {
    const d = structuredClone(fixture()); select(d).unexpected_private_field = 'synthetic'; assert.throws(() => validateViewer(d));
  }
  const d = fixture(); d.checkout.analysis_error = 'MODEL_PENDING'; assert.throws(() => validateViewer(d));
  Object.assign(d.checkout, {state: 'ANALYSIS_BLOCKED', snapshot_hash: null, results: []}); validateViewer(d);
});
test('approved original source and amount are not labelled current catalog facts', () => {
  const document = dom(); const d = fixture(); d.checkout.stale = true; renderViewer(d, document);
  const text = flatten(document.getElementById('viewer-content')).map(x => x.textContent).join(' ');
  assert.match(text, /Approved original source/); assert.match(text, /Original approved SKU, price and source/);
  assert.doesNotMatch(text, /Current original source/);
});


test('viewer design stays embedded and uses the existing buying-desk tokens', () => {
  const styles = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)];
  assert.equal(styles.length, 1);
  const css = styles[0][1];
  for (const token of ['--paper:#f8f7f2', '--ink:#242a27', '--green:#274d3a']) assert.ok(css.includes(token));
  assert.match(css, /minmax\(0,1fr\)/);
  assert.match(css, /@media\(max-width:800px\)/);
  assert.match(css, /@media\(max-width:480px\)/);
  assert.match(css, /overflow-wrap:anywhere/);
  assert.doesNotMatch(css, /url\s*\(|@import/i);
  assert.doesNotMatch(html, /<link\b|\ssrc=|<iframe\b|<form\b/i);
});
test('source and retained results are neighboring text-only regions, including no result', () => {
  for (const noCheckout of [false, true]) {
    const document = dom(); const data = fixture(); if (noCheckout) data.checkout = null;
    renderViewer(data, document);
    const content = document.getElementById('viewer-content');
    const columns = content.children.find(n => n.className === 'review-columns');
    assert.deepEqual(columns.children.map(n => n.className), ['source-column', 'readback-column']);
    assert.equal(columns.children[0].children.find(n => n.className === 'source-text').textContent, source.text);
    assert.ok(content.children[0].textContent === '');
    const all = flatten(content);
    assert.equal(all.some(n => ['button', 'input', 'select', 'form', 'a', 'link', 'style', 'script'].includes(n.tag)), false);
    if (noCheckout) assert.match(all.map(n => n.textContent).join(' '), /No retained review/);
    else assert.ok(all.some(n => n.className === 'outcome match'));
  }
});


test('blocked UNKNOWN keeps all approved conditions visible without accepted results', () => {
  const data = fixture(); data.checkout.state = 'ANALYSIS_BLOCKED'; data.checkout.snapshot_hash = null; data.checkout.results = []; data.checkout.analysis.accounting_state = 'unknown';
  data.checkout.conditions.push({condition_id: 'c2', kind: 'included_cable', value: 'any cable'});
  const document = dom(); renderViewer(data, document);
  const summary = flatten(document.getElementById('viewer-content')).find(n => n.textContent.startsWith('Approved conditions:'));
  assert.ok(summary); assert.match(summary.textContent, /UK QWERTY/); assert.match(summary.textContent, /any cable/);
  assert.match(flatten(document.getElementById('viewer-content')).map(n => n.textContent).join(' '), /No accepted proposal/);
});
