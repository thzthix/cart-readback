import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {start} from './viewer.mjs';
import {validateViewer} from './viewer-core.mjs';
const fixture = JSON.parse(readFileSync(0, 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  set innerHTML(_) { throw new Error('HTML injection'); }
}
const flatten = n => [n, ...n.children.flatMap(flatten)];
function dom() { const nodes = new Map(['viewer-content', 'viewer-status'].map(id => [id, new Element('div')])); return {readyState: 'complete', createElement: tag => new Element(tag), getElementById: id => nodes.get(id)}; }
test(`actual synthetic HTTP viewer ${fixture.scenario}`, async () => {
  let cookie; let envelope; const calls = [];
  const localFetch = async (path, options) => {
    calls.push(path);
    const headers = {...options.headers, 'Sec-Fetch-Site': 'same-origin'};
    if (options.method === 'POST') headers.Origin = fixture.origin;
    if (cookie) headers.Cookie = cookie;
    const response = await fetch(fixture.origin + path, {...options, headers});
    if (response.headers.has('set-cookie')) cookie = response.headers.get('set-cookie').split(';')[0];
    if (path.endsWith('/bootstrap') && response.ok) envelope = await response.clone().json();
    return response;
  };
  const document = dom();
  await start(fixture.capability, {document, fetch: localFetch});
  assert.deepEqual(calls, ['/gemini-viewer/api/redeem', '/gemini-viewer/api/bootstrap']);
  assert.match(document.getElementById('viewer-status').textContent, /Read-only result loaded/);
  validateViewer(envelope);
  assert.equal(envelope.catalog.length, 1);
  assert.equal(envelope.checkout.analysis.evidence_kind, fixture.scenario === 'protocol' ? 'none' : 'fabricated-offline');
  assert.equal(envelope.checkout.analysis.accounting_state, fixture.scenario === 'protocol' ? 'unknown' : 'known');
  assert.equal(envelope.checkout.state, ['protocol', 'semantic'].includes(fixture.scenario) ? 'ANALYSIS_BLOCKED' : 'REVIEW_REQUIRED');
  const nodes = flatten(document.getElementById('viewer-content'));
  assert.equal(nodes.some(n => ['button', 'input', 'select', 'form', 'a'].includes(n.tag)), false);
  const text = nodes.map(n => n.textContent).join(' ');
  assert.match(text, /PayPal is unconnected/);
  if (fixture.scenario === 'expired') assert.match(text, /STALE historical/);
  if (fixture.scenario === 'protocol') assert.match(text, /UNKNOWN is retained/);
  calls.length = 0;
  await start(null, {document, fetch: localFetch});
  assert.deepEqual(calls, ['/gemini-viewer/api/bootstrap']);
  const repeated = await localFetch('/gemini-viewer/api/redeem', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({launch_capability: fixture.capability})});
  assert.equal(repeated.status, 403);
  for (const path of ['/api/analyze', '/api/confirm', '/api/orders', '/gemini-viewer/api/analyze']) {
    const denied = await localFetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    assert.equal(denied.status, 403);
  }
});
