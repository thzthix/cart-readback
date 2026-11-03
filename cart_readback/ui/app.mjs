import {conditionLabel, confirmPayload, displayValue, formatMoney, isOrderLocked, mergedEvidenceRanges,
  operationKey, OUTCOMES, validateBootstrap, validateCheckout} from './core.mjs';

const $ = id => document.getElementById(id);
const state = {catalog: [], revision: 0, csrf: '', checkout: null, selected: '', busy: false,
  blocked: false, uncertain: false, epoch: 0, acknowledgements: new Set()};

/** Create elements without parsing catalog or model strings as HTML. */
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
function status(message) { $('status').textContent = message; }
function clearError() { $('error-summary').hidden = true; }
function showError(message) {
  $('error-message').textContent = message;
  $('error-summary').hidden = false;
  $('error-summary').focus();
}
function conditionInputs() {
  const conditions = [];
  if ($('want-layout').checked) conditions.push({kind: 'layout', value: $('layout').value});
  if ($('want-cable').checked) conditions.push({kind: 'included_cable', value: $('cable').value});
  return conditions;
}
function summaryRow(list, label, value, mono = false) {
  const row = node('div'); row.append(node('dt', label), node('dd', value, mono ? 'mono' : undefined)); list.append(row);
}
function updateControls() {
  const locked = state.busy || state.blocked || state.uncertain || isOrderLocked(state.checkout);
  document.querySelectorAll('input[name="sku"]').forEach(input => { input.disabled = locked; });
  $('want-layout').disabled = locked; $('want-cable').disabled = locked;
  $('layout').disabled = locked || !$('want-layout').checked;
  $('cable').disabled = locked || !$('want-cable').checked;
  $('analyze').disabled = locked || !state.selected || conditionInputs().length === 0;
  const reviewing = state.checkout?.state === 'REVIEW_REQUIRED' && !locked;
  $('confirm-snapshot').disabled = !reviewing;
  document.querySelectorAll('[data-ack]').forEach(input => { input.disabled = !reviewing; });
  let confirmable = false;
  try { confirmPayload(state.checkout, state.revision, $('confirm-snapshot').checked, state.acknowledgements); confirmable = true; } catch { /* Incomplete human review is an expected UI state. */ }
  $('confirm').disabled = !reviewing || !confirmable;
  $('reload').disabled = state.busy;
  document.querySelectorAll('[data-order-action]').forEach(button => { button.disabled = state.busy || state.blocked || state.uncertain || (state.checkout?.stale === true && button.dataset.orderAction !== 'reconcile'); });
  const final = $('final-capture');
  if (final) {
    final.disabled = state.busy || state.blocked || state.uncertain || state.checkout?.stale === true;
    const capture = $('capture');
    if (capture) capture.disabled = state.busy || state.blocked || state.uncertain || state.checkout?.stale === true || !final.checked;
  }
}
function invalidate() {
  if (isOrderLocked(state.checkout)) return;
  state.epoch += 1; state.checkout = null; state.acknowledgements.clear();
  $('confirm-snapshot').checked = false;
  $('review-section').hidden = true; $('order-section').hidden = true;
  clearError(); status('Selection changed. Read it back again; previous confirmation no longer applies.');
  document.querySelectorAll('#catalog-rows tr').forEach(row => row.classList.toggle('selected', row.dataset.sku === state.selected));
  renderSelectedSource(); updateControls();
}
function renderSelectedSource() {
  const product = state.catalog.find(item => item.sku_id === state.selected);
  $('catalog-source').hidden = !product;
  if (!product) return;
  $('catalog-source-meta').textContent = `${product.source.source_id} / revision ${product.source.revision}`;
  $('catalog-source-text').textContent = product.source.text;
}
function renderCatalog() {
  const rows = $('catalog-rows'); rows.replaceChildren();
  for (const product of state.catalog) {
    const row = node('tr'); row.dataset.sku = product.sku_id;
    row.classList.toggle('selected', state.selected === product.sku_id);
    const selectCell = node('td'); const label = node('label', undefined, 'product-label');
    const input = node('input'); input.type = 'radio'; input.name = 'sku'; input.value = product.sku_id;
    input.checked = state.selected === product.sku_id;
    input.addEventListener('change', () => {state.selected = product.sku_id; invalidate();});
    const description = node('span', product.name); description.append(node('span', product.sku_id, 'sku'));
    label.append(input, description); selectCell.append(label);
    row.append(selectCell, node('td', displayValue(product.baseline.layout) || 'Not stated'),
      node('td', displayValue(product.baseline.included_cable) || 'Not stated'),
      node('td', formatMoney(product.price_minor, product.currency), 'money'));
    rows.append(row);
  }
}
function renderSource(checkout) {
  const source = checkout.source;
  $('source-meta').textContent = `${source.source_id} / revision ${source.revision}`;
  $('source-hash').textContent = `SHA-256 ${source.sha256}`;
  const text = $('source-text'); text.replaceChildren();
  const codepoints = Array.from(source.text); let cursor = 0;
  for (const range of mergedEvidenceRanges(checkout)) {
    text.append(document.createTextNode(codepoints.slice(cursor, range.start).join('')));
    const mark = node('mark', codepoints.slice(range.start, range.end).join(''));
    mark.id = `source-span-${range.start}`; mark.tabIndex = -1; text.append(mark); cursor = range.end;
  }
  text.append(document.createTextNode(codepoints.slice(cursor).join('')));
}
function renderResults(checkout) {
  const results = $('readback-results'); results.replaceChildren();
  const acknowledgements = $('acknowledgements'); acknowledgements.replaceChildren();
  const ranges = mergedEvidenceRanges(checkout);
  for (const condition of checkout.conditions) {
    const result = checkout.results.find(item => item.condition_id === condition.condition_id);
    if (!result) continue;
    const item = node('div', undefined, 'result');
    const heading = node('div', undefined, 'result-heading');
    heading.append(node('h4', conditionLabel(condition)), node('span', OUTCOMES[result.status], `outcome ${result.status}`));
    item.append(heading, node('p', result.explanation));
    for (const span of result.evidence) {
      const quote = node('blockquote'); quote.append(node('p', span.quote));
      const link = node('a', `${span.source_id} · characters ${span.start}–${span.end}`, 'source-link');
      const target = ranges.find(range => range.start <= span.start && range.end >= span.end);
      link.href = `#source-span-${target.start}`;
      link.addEventListener('click', () => { $(link.hash.slice(1))?.focus(); });
      quote.append(link); item.append(quote);
    }
    if (result.evidence.length === 0) item.append(node('p', 'No supporting span supplied. Do not infer inclusion or compatibility.', 'caption'));
    results.append(item);
    if (result.status === 'unknown' || result.status === 'conflict') {
      const label = node('label', undefined, `check-label ack ${result.status}`);
      const input = node('input'); input.type = 'checkbox'; input.dataset.ack = condition.condition_id;
      input.checked = state.acknowledgements.has(condition.condition_id);
      input.addEventListener('change', () => {
        if (input.checked) state.acknowledgements.add(condition.condition_id); else state.acknowledgements.delete(condition.condition_id);
        $('confirm-snapshot').checked = false; updateControls();
      });
      const wording = result.status === 'unknown'
        ? `I understand “${conditionLabel(condition)}” is not established by this description. Continuing does not make it a match.`
        : `I understand “${conditionLabel(condition)}” conflicts with the description. I deliberately keep this SKU and condition unchanged.`;
      label.append(input, node('span', wording)); acknowledgements.append(label);
    }
  }
}
function renderReview() {
  const checkout = state.checkout;
  $('review-section').hidden = !checkout;
  if (!checkout) { $('order-section').hidden = true; return; }
  const historicalOrder = checkout.stale === true && Boolean(checkout.order);
  $('source-changed').hidden = !historicalOrder;
  $('source-changed').textContent = 'The product description, price, or analysis configuration changed after this order was made. This is the previous reviewed version, not the current catalog. The existing order is retained; capture and editing stay blocked. Do not create another order.';
  $('source-heading').textContent = historicalOrder ? 'Previous reviewed description — changed' : 'Original product description';
  renderSource(checkout); renderResults(checkout);
  const product = state.catalog.find(item => item.sku_id === checkout.sku_id);
  const details = $('snapshot-details'); details.replaceChildren();
  summaryRow(details, 'Exact product', `${product.name} / ${product.sku_id}`);
  summaryRow(details, 'Quantity / item total', `1 / ${formatMoney(checkout.amount.minor, checkout.amount.currency)}`);
  summaryRow(details, 'Your conditions', checkout.conditions.map(conditionLabel).join('; '));
  summaryRow(details, 'Description version', `${checkout.source.source_id} / ${checkout.source.revision}`);
  summaryRow(details, 'Review fingerprint', checkout.snapshot_hash || 'No confirmable review', true);
  $('review-blocked').hidden = checkout.state !== 'ANALYSIS_BLOCKED';
  $('review-blocked').textContent = 'Analysis blocked. No valid readback is available. Change your selection or reload; confirmation and order creation are unavailable.';
  $('snapshot').hidden = checkout.state === 'ANALYSIS_BLOCKED';
  const reviewing = checkout.state === 'REVIEW_REQUIRED' && !historicalOrder;
  $('acknowledgements').hidden = !reviewing;
  $('confirm-snapshot').parentElement.hidden = !reviewing;
  $('confirm').hidden = !reviewing;
  $('confirmation-state').textContent = checkout.confirmation_id
    ? 'This fixture review is confirmed. This is not PayPal approval or a payment.'
    : 'Confirmation is your decision, not the suggestion’s.';
  renderOrder(); updateControls();
}
function orderButton(text, action, path, extra = {}, idempotent = false) {
  const button = node('button', text); button.type = 'button'; button.dataset.orderAction = action;
  button.addEventListener('click', () => mutate(path, {...orderBody(), ...extra}, {action, idempotent}));
  $('order-controls').append(button); return button;
}
function orderBody() { return {expected_revision: state.revision, snapshot_hash: state.checkout.snapshot_hash}; }
function renderOrder() {
  const checkout = state.checkout;
  $('order-section').hidden = !checkout?.confirmation_id && !checkout?.order;
  if (!checkout?.confirmation_id && !checkout?.order) return;
  const controls = $('order-controls'); controls.replaceChildren();
  const details = $('order-details'); details.replaceChildren();
  summaryRow(details, 'Mode', 'Fixture provider — not PayPal');
  summaryRow(details, 'Order item', `${checkout.sku_id} × 1 / ${formatMoney(checkout.amount.minor, checkout.amount.currency)}`);
  summaryRow(details, 'Reviewed version', checkout.snapshot_hash, true);
  const order = checkout.order;
  if (order) {
    summaryRow(details, 'Local order', order.order_id, true);
    summaryRow(details, 'Synthetic provider ref.', order.provider_order_id || 'Not returned', true);
    summaryRow(details, 'Server state', checkout.state, true);
  }
  const base = order ? `/api/orders/${encodeURIComponent(order.order_id)}` : '';
  const states = {
    SNAPSHOT_CONFIRMED: ['Review confirmed; no order yet', 'Create a synthetic order bound to this exact reviewed item and conditions. This does not contact PayPal.'],
    ORDER_CREATED: ['Fixture order created; not approved', 'Rehearse buyer approval. This is a local simulation, not a PayPal window. Your selection is locked while this order is unresolved.'],
    PAYPAL_APPROVED: ['Fixture approval recorded; not captured', 'Approval and capture are separate. Ask the server to recheck this same synthetic order before final confirmation.'],
    SERVER_RECHECKED: ['Fixture order rechecked; final decision required', 'Check the SKU, conditions, and amount above again. Only your explicit final confirmation enables the simulated capture.'],
    ORDER_CREATE_PENDING: ['Fixture order creation is pending', 'Wait for the current operation. Reload current server state or reconcile this same operation; do not create another order.'],
    CAPTURE_PENDING: ['Fixture capture is pending', 'Completion has not been established. Reload current server state or reconcile the same order; do not capture again.'],
    PAYMENT_UNKNOWN: ['Fixture outcome unknown; do not start again', 'Reconcile this same order. Do not create a new order or assume this one failed.'],
    COMPLETED: ['Fixture capture recorded — not a payment', 'The local simulation reached its completed state. No PayPal API was called and no money moved.'],
  };
  const [title, help] = states[checkout.state] || ['Order is held', 'This state is not supported by this UI. No new action is enabled.'];
  $('order-state').textContent = title; $('order-help').textContent = help;
  if (checkout.stale === true && order) {
    if (checkout.state !== 'COMPLETED') {
      $('order-state').textContent = 'Reviewed item changed; capture is blocked';
      $('order-help').textContent = 'This order already exists, so the item cannot be changed here. Check this same order’s current state. The fixture has no cancel or new-order flow; no second order will be created.';
    }
    if (['PAYMENT_UNKNOWN', 'ORDER_CREATE_PENDING', 'CAPTURE_PENDING'].includes(checkout.state)) {
      orderButton('Reconcile the same fixture order', 'reconcile', `${base}/reconcile`);
    }
    const reload = node('button', 'Check current fixture state', 'secondary'); reload.type = 'button';
    reload.addEventListener('click', bootstrap); controls.append(reload);
    return;
  }
  if (checkout.state === 'SNAPSHOT_CONFIRMED') {
    orderButton('Create fixture order', 'create', '/api/orders', {review_id: checkout.review_id, confirmation_id: checkout.confirmation_id}, true);
  } else if (checkout.state === 'ORDER_CREATED') {
    orderButton('Simulate fixture buyer approval', 'approve', `${base}/fixture-approve`);
  } else if (checkout.state === 'PAYPAL_APPROVED') {
    orderButton('Recheck this fixture order', 'verify', `${base}/verify`);
  } else if (checkout.state === 'SERVER_RECHECKED') {
    const label = node('label', undefined, 'check-label final-check');
    const input = node('input'); input.type = 'checkbox'; input.id = 'final-capture';
    input.addEventListener('change', updateControls);
    label.append(input, node('span', 'I confirm this exact reviewed fixture order for simulated capture. No real payment will occur.'));
    controls.append(label);
    const button = orderButton('Simulate fixture capture', 'capture', `${base}/capture`, {confirmation_id: checkout.confirmation_id, final_confirmation: true}, true);
    button.id = 'capture';
  } else if (['PAYMENT_UNKNOWN', 'ORDER_CREATE_PENDING', 'CAPTURE_PENDING'].includes(checkout.state) && order) {
    orderButton('Reconcile the same fixture order', 'reconcile', `${base}/reconcile`);
  }
}
async function fixtureFetch(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    // A response is not established until its JSON body has been received.
    return await readResponse(response);
  } finally { clearTimeout(timeout); }
}
async function readResponse(response) {
  let data;
  try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response. Reload current state before trying anything else.'); }
  if (Number.isSafeInteger(data.revision)) state.revision = data.revision;
  if (!response.ok && !(response.status === 422 && data.checkout?.state === 'ANALYSIS_BLOCKED')) throw new Error(`${data.error?.code || 'REQUEST_FAILED'}: ${data.error?.message || 'The server refused the request.'}`);
  if (data.mode !== 'fixture' || data.api_version !== '1') throw new Error('Unsupported server mode or API version. All actions are blocked.');
  return data;
}
async function mutate(path, payload, options = {}) {
  if (state.busy || state.blocked || state.uncertain) return;
  if (state.checkout?.stale === true && state.checkout.order && options.action !== 'reconcile') return;
  const epoch = state.epoch; state.busy = true; clearError(); updateControls();
  status('Working on the local fixture…');
  try {
    const headers = {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf};
    if (options.idempotent) {
      headers['Idempotency-Key'] = operationKey(sessionStorage, payload.snapshot_hash, options.action, () => crypto.randomUUID());
    }
    const data = await fixtureFetch(path, {method: 'POST', credentials: 'same-origin', headers, body: JSON.stringify(payload)});
    const checkout = validateCheckout(data.checkout, state.catalog);
    if (epoch !== state.epoch) { status('Selection changed during the request. Read the new selection back again.'); return; }
    state.checkout = checkout; state.acknowledgements.clear(); $('confirm-snapshot').checked = false;
    renderReview(); status(`Fixture server state: ${checkout.state}. No real model or payment call.`);
    if (options.action === 'analyze') $('review-heading').focus();
  } catch (error) {
    // Any uncertain mutation response freezes further mutations until a bootstrap read.
    state.uncertain = true;
    showError(`${error.message}\nFurther actions are paused. Reload current server state to recover; do not start a second order.`);
    status('Response not established. Read current server state before continuing.');
  } finally { state.busy = false; updateControls(); }
}
async function bootstrap() {
  if (state.busy) return;
  state.busy = true; state.blocked = true; clearError(); updateControls();
  status('Loading current fixture state…');
  try {
    const data = validateBootstrap(await fixtureFetch('/api/bootstrap', {credentials: 'same-origin', cache: 'no-store'}));
    state.catalog = data.catalog; state.csrf = data.csrf_token;
    const previous = data.checkout;
    const stalePreorder = previous?.stale === true && !isOrderLocked(previous);
    state.checkout = stalePreorder ? null : validateCheckout(previous, state.catalog);
    state.selected = state.catalog.some(product => product.sku_id === previous?.sku_id) ? previous.sku_id : '';
    state.epoch += 1; state.acknowledgements.clear(); state.uncertain = false; state.blocked = false;
    $('confirm-snapshot').checked = false;
    $('want-layout').checked = false; $('want-cable').checked = false;
    for (const condition of (stalePreorder ? previous : state.checkout)?.conditions || []) {
      if (condition.kind === 'layout') { $('want-layout').checked = true; $('layout').value = condition.value; }
      if (condition.kind === 'included_cable') { $('want-cable').checked = true; $('cable').value = condition.value; }
    }
    renderCatalog(); renderSelectedSource(); renderReview();
    status(stalePreorder ? 'The product description or price changed. Previous confirmation was cleared. Read this selection back again.'
      : state.checkout ? `Current fixture state restored: ${state.checkout.state}. No real payment.` : 'Sample catalog ready. Choose one SKU and at least one condition.');
  } catch (error) { state.blocked = true; showError(error.message); status('Catalog or server state unavailable. All review and order actions are blocked.'); }
  finally { state.busy = false; updateControls(); }
}
$('conditions-form').addEventListener('submit', event => {
  event.preventDefault();
  if (!state.selected || conditionInputs().length === 0) return;
  state.acknowledgements.clear(); $('confirm-snapshot').checked = false;
  mutate('/api/analyze', {expected_revision: state.revision, sku_id: state.selected, conditions: conditionInputs()}, {action: 'analyze'});
});
for (const id of ['want-layout', 'want-cable', 'layout', 'cable']) $(id).addEventListener('change', invalidate);
$('confirm-snapshot').addEventListener('change', updateControls);
$('confirm').addEventListener('click', () => {
  try { mutate('/api/confirm', confirmPayload(state.checkout, state.revision, $('confirm-snapshot').checked, state.acknowledgements), {action: 'confirm'}); }
  catch (error) { showError(error.message); }
});
$('reload').addEventListener('click', bootstrap);
bootstrap();
