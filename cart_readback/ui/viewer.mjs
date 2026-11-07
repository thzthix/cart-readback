import {validateViewer, accountingText} from './viewer-core.mjs';
import {formatMoney, displayValue, conditionLabel, OUTCOMES} from './core.mjs';
export function renderViewer(data, document) {
  validateViewer(data);
  const node = (tag, value) => { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; return n; };
  const section = (heading, lines) => { const n = node('section'); n.className = 'section'; n.append(node('h2', heading)); lines.forEach(line => n.append(node('p', line))); return n; };
  const content = document.getElementById('viewer-content'); const product = data.catalog[0]; const c = data.checkout;
  content.replaceChildren();
  const selection = section('Same-source baseline · no AI required', [
    'Original approved SKU, price and source; this is not a fresh current-catalog claim.',
    `${product.name} · ${product.sku_id} · quantity 1 · ${formatMoney(product.price_minor, product.currency)}`,
    `Layout: ${displayValue(product.baseline.layout)}. Included cable: ${displayValue(product.baseline.included_cable)}.`,
    'Not stated is different from explicitly not included. ISO geometry does not establish a language layout.']);
  selection.children[2].className = 'selection-title';
  content.append(selection);
  const columns = node('div'); columns.className = 'review-columns';
  const original = node('article'); original.className = 'source-column';
  original.append(node('h2', 'Approved original source'));
  const sourceText = node('p', product.source.text); sourceText.className = 'source-text'; original.append(sourceText);
  const sourceIdentity = node('p', `${product.source.source_id} · revision ${product.source.revision}`); sourceIdentity.className = 'mono caption'; original.append(sourceIdentity);
  const retained = node('article'); retained.className = 'readback-column';
  retained.append(node('h2', 'Retained review · no action authority'));
  if (c) {
    const state = node('p', `State: ${c.state}. ${c.stale ? 'STALE historical review; not current consent or a usable result.' : 'Read-only review; confirmation and checkout are unavailable.'}`); state.className = 'notice'; retained.append(state);
    retained.append(node('p', 'Exact quotes establish text identity, not semantic correctness or buyer benefit.'));
    if (c.stale) {
      retained.append(node('h3', 'Historical source for retained quotations'));
      const historical = node('p', c.source.text); historical.className = 'source-text'; retained.append(historical);
    }
    if (!c.results.length) retained.append(node('p', 'No accepted proposal. Blocked or UNKNOWN analysis remains nonactionable.'));
    c.results.forEach((r, i) => {
      const article = node('article'); article.className = 'result';
      const heading = node('div'); heading.className = 'result-heading'; heading.append(node('h3', conditionLabel(c.conditions[i])));
      const outcome = node('span', OUTCOMES[r.status]); outcome.className = `outcome ${r.status}`; heading.append(outcome);
      article.append(heading, node('p', r.explanation));
      r.evidence.forEach(span => {
        const identity = node('p', `${span.source_id} · code points ${span.start}–${span.end}`); identity.className = 'mono caption';
        article.append(node('blockquote', span.quote), identity);
      });
      if (!r.evidence.length) article.append(node('p', 'No supporting span supplied. Absence is not evidence of exclusion.'));
      retained.append(article);
    });
  } else retained.append(node('p', 'No retained review. No accepted proposal or action is available.'));
  columns.append(original, retained); content.append(columns);
  const configuration = section('Configured analysis, not proof of a call', [
    `Gemini execution: ${data.providers.analysis.execution_kind}. Host dispatch availability: ${data.providers.analysis.dispatch_available ? 'available' : 'unavailable or expired'}.`,
    'Configuration does not establish successful inference, free-tier eligibility, actual price or no-charge execution. Inference may incur charges. Payments are fixture-only; PayPal is unconnected.',
    accountingText(c)]);
  configuration.className = 'section configuration';
  if (c) configuration.append(node('p', `Configured model: ${c.model.model_version}. Expected returned version (configuration only): ${data.viewer.expected_model_version}. The actual returned wire version is not exposed in this public view.`));
  content.append(configuration);
  document.getElementById('viewer-status').textContent = 'Read-only result loaded. No analysis or payment action is available.';
}
export async function start(capability, {document = globalThis.document, fetch = globalThis.fetch} = {}) {
  if (document.readyState === 'loading') await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, {once: true}));
  try {
    if (capability !== null) {
      if (typeof capability !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(capability)) throw new Error();
      const body = JSON.stringify({launch_capability: capability}); capability = null;
      const redemption = await fetch('/gemini-viewer/api/redeem', {method: 'POST', credentials: 'same-origin', redirect: 'error', cache: 'no-store', headers: {'Content-Type': 'application/json'}, body});
      if (!redemption.ok) throw new Error();
    }
    const response = await fetch('/gemini-viewer/api/bootstrap', {method: 'GET', credentials: 'same-origin', redirect: 'error', cache: 'no-store'});
    if (!response.ok) throw new Error();
    renderViewer(await response.json(), document);
  } catch {
    document.getElementById('viewer-content').replaceChildren();
    document.getElementById('viewer-status').textContent = 'Review unavailable or inconsistent. No action was sent after a failed request. No automatic retry occurs. Reload only reads existing state; it does not renew access or replay analysis.';
  }
}
