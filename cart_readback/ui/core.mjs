/** Pure client checks. The server remains the authorization boundary. */
export const FEATURE_FLAGS = Object.freeze({fixture: true, live: false});
export const CONDITION_LABELS = Object.freeze({layout: 'Keyboard layout', included_cable: 'Included cable'});
export const OUTCOMES = Object.freeze({match: 'Matches', conflict: 'Conflicts', unknown: 'Not enough information'});
const PREORDER_STATES = new Set(['REVIEW_REQUIRED', 'ANALYSIS_BLOCKED', 'SNAPSHOT_CONFIRMED']);

export function formatMoney(minor, currency) {
  if (!Number.isSafeInteger(minor) || minor < 0 || currency !== 'USD') {
    throw new Error('Unsupported item amount or currency. Review is blocked.');
  }
  return `${currency} ${(minor / 100).toFixed(2)}`;
}

export function isOrderLocked(checkout) {
  return Boolean(checkout?.order) || Boolean(checkout && !PREORDER_STATES.has(checkout.state));
}

export function displayValue(value) {
  return ({UK_QWERTY: 'UK QWERTY', DE_QWERTZ: 'German QWERTZ', US_QWERTY: 'US QWERTY', unknown: 'Not stated', none: 'Not included (explicit)'})[value] || value;
}

export function conditionLabel(condition) {
  if (!Object.hasOwn(CONDITION_LABELS, condition.kind)) throw new Error('Unsupported condition.');
  const allowed = condition.kind === 'layout' ? ['UK_QWERTY', 'DE_QWERTZ', 'US_QWERTY']
    : ['USB-C to USB-C', 'USB-A to USB-C', 'any cable'];
  if (!allowed.includes(condition.value)) throw new Error('Unsupported condition value.');
  return `${CONDITION_LABELS[condition.kind]}: ${displayValue(condition.value)}`;
}

export function evidenceText(source, span) {
  if (!source || span.source_id !== source.source_id || !Number.isInteger(span.start)
      || !Number.isInteger(span.end) || span.start < 0 || span.end <= span.start) {
    throw new Error('The suggestion has an invalid source reference. Review is blocked.');
  }
  const codepoints = Array.from(source.text);
  if (span.end > codepoints.length || codepoints.slice(span.start, span.end).join('') !== span.quote) {
    throw new Error('A quoted span does not match the current source. Review is blocked.');
  }
  return span.quote;
}

const FIXTURE_PROVIDERS = Object.freeze({analysis: {mode: 'fixture', is_fixture: true},
  payment: {mode: 'fixture', is_fixture: true}, network_enabled: false});

const CONTEXT_MODE = 'genuine-context-capacity';
const EXECUTION_KINDS = ['unavailable', 'fabricated-offline', 'provider-runtime'];
function exactKeys(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

export function validateProviders(providers = FIXTURE_PROVIDERS) {
  const analysis = providers?.analysis;
  const payment = providers?.payment;
  const context = analysis?.mode === CONTEXT_MODE;
  if (!exactKeys(providers, ['analysis', 'payment', 'network_enabled'])
      || !exactKeys(payment, ['mode', 'is_fixture'])
      || !['fixture', 'paypal-sandbox-offline'].includes(payment.mode)
      || payment.is_fixture !== (payment.mode === 'fixture')
      || (context ? (!exactKeys(analysis, ['mode', 'is_fixture', 'dispatch_available', 'execution_kind'])
        || analysis.is_fixture !== false || payment.mode !== 'fixture'
        || typeof analysis.dispatch_available !== 'boolean'
        || !EXECUTION_KINDS.includes(analysis.execution_kind)
        || (analysis.execution_kind === 'unavailable' && analysis.dispatch_available)
        || providers.network_enabled !== (analysis.execution_kind === 'provider-runtime' && analysis.dispatch_available))
        : (!exactKeys(analysis, ['mode', 'is_fixture'])
          || !['fixture', 'injected-offline'].includes(analysis.mode)
          || analysis.is_fixture !== (analysis.mode === 'fixture')
          || providers.network_enabled !== false))) {
    throw new Error('Unsupported provider or network mode. All actions are blocked.');
  }
  return providers;
}

export function validateEnvelope(data) {
  if (data.api_version !== '1' || !['fixture', 'offline', 'mixed'].includes(data.mode)
      || (data.mode !== 'fixture' && !data.providers)) {
    throw new Error('Unsupported server mode or API version. All actions are blocked.');
  }
  const providers = validateProviders(data.providers);
  const expected = providers.analysis.mode === CONTEXT_MODE ? 'mixed'
    : providers.analysis.is_fixture && providers.payment.is_fixture ? 'fixture' : 'offline';
  if (data.mode !== expected) throw new Error('Inconsistent provider mode.');
  return providers;
}

function validateContextAnalysis(checkout) {
  const analysis = checkout.analysis;
  const model = checkout.model;
  if (!exactKeys(analysis, ['strategy', 'dispatch_state', 'accounting_state', 'usage_observed', 'evidence_kind'])
      || analysis.strategy !== 'context-capacity-v1'
      || !['not-attempted', 'attempted'].includes(analysis.dispatch_state)
      || !['unobserved', 'known', 'unknown'].includes(analysis.accounting_state)
      || typeof analysis.usage_observed !== 'boolean'
      || !['none', 'fabricated-offline', 'provider-observation'].includes(analysis.evidence_kind)
      || !exactKeys(model, ['provider', 'model_version', 'prompt_version', 'adapter_version',
        'validator_version', 'is_fixture', 'execution_mode', 'execution_kind'])
      || model.provider !== 'openai-responses' || model.model_version !== 'gpt-6-luna'
      || model.prompt_version !== 'cartreadback-prompt-v2-wire'
      || model.adapter_version !== 'genuine-context-responses-v1'
      || model.validator_version !== 'strict-spans-v1+ordered-results-v1'
      || model.is_fixture !== false || model.execution_mode !== CONTEXT_MODE
      || !EXECUTION_KINDS.includes(model.execution_kind)) {
    throw new Error('Unsupported context analysis metadata. All actions are blocked.');
  }
  const attempted = analysis.dispatch_state === 'attempted';
  const observedKind = model.execution_kind === 'fabricated-offline' ? 'fabricated-offline' : 'provider-observation';
  if ((analysis.usage_observed && (!attempted || model.execution_kind === 'unavailable'
        || analysis.evidence_kind !== observedKind))
      || (!analysis.usage_observed && analysis.evidence_kind !== 'none')
      || (analysis.accounting_state === 'known' && !analysis.usage_observed)
      || (analysis.accounting_state === 'unobserved' && analysis.usage_observed)
      || (model.execution_kind === 'unavailable' && attempted)
      || (checkout.state !== 'ANALYSIS_BLOCKED' && (!attempted || analysis.accounting_state !== 'known'))
      || (checkout.state === 'ANALYSIS_BLOCKED' && (checkout.snapshot_hash || checkout.confirmation_id || checkout.order))) {
    throw new Error('Inconsistent context analysis outcome. All actions are blocked.');
  }
  return analysis;
}

/** A claim is not proof of a network send; accounting is not semantic truth. */
export function contextAnalysisText(checkout) {
  if (!checkout) return 'No owned analysis attempt is shown.';
  const analysis = validateContextAnalysis(checkout);
  const claim = analysis.dispatch_state === 'attempted'
    ? 'Dispatch claim recorded; this does not prove a provider request was sent.'
    : 'No dispatch claim recorded.';
  const usage = !analysis.usage_observed ? 'No usage observation.'
    : analysis.evidence_kind === 'fabricated-offline'
      ? 'Fabricated offline usage recorded; not a provider observation.'
      : 'Provider usage recorded; this is not an invoice or a correctness judgment.';
  const accounting = {unobserved: 'Accounting is unobserved.', known: 'Accounting is known; this does not validate the suggestion.',
    unknown: 'Accounting remains UNKNOWN; capacity stays held. Do not retry the analysis.'}[analysis.accounting_state];
  return `${claim} ${usage} ${accounting}`;
}

/** Retain accounting only; an obsolete proposal/source/consent grants no action. */
export function contextAnalysisHistory(checkout) {
  if (!checkout || checkout.stale !== true || checkout.order) return null;
  if (!checkout.analysis && checkout.model?.execution_mode !== CONTEXT_MODE) return null;
  const analysis = validateContextAnalysis(checkout);
  return {accounting_state: analysis.accounting_state, evidence_kind: analysis.evidence_kind,
    text: contextAnalysisText(checkout)};
}

/** Return secrets live only in this page's memory, never history or storage. */
export function parseBuyerReturn(pathname, search, hash = '') {
  if (pathname !== '/payment-return' || (search === '' && hash === '')) return null;
  const invalid = () => { throw new Error('Invalid buyer return. No action was sent.'); };
  if (hash || typeof search !== 'string' || !search.startsWith('?') || search.length > 1024
      || /%(?![0-9a-f]{2})/i.test(search)) invalid();
  const params = new URLSearchParams(search);
  const allowed = new Set(['order_id', 'state', 'outcome', 'token', 'PayerID']);
  for (const key of params.keys()) if (!allowed.has(key) || params.getAll(key).length !== 1) invalid();
  const result = {order_id: params.get('order_id'), return_state: params.get('state'),
    outcome: params.get('outcome'), provider_order_id: params.get('token')};
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(result.order_id || '')
      || !/^[A-Za-z0-9_-]{43}$/.test(result.return_state || '')
      || !['approved', 'cancelled'].includes(result.outcome)
      || !/^[A-Z0-9]{1,36}$/.test(result.provider_order_id || '')
      || (params.has('PayerID') && !/^[A-Z0-9]{1,36}$/.test(params.get('PayerID')))) invalid();
  return result;
}

export function buyerReturnPayload(returned, checkout, revision, providers, now = Date.now()) {
  validateProviders(providers);
  const order = checkout?.order;
  const prepared = order?.buyer_return;
  if (!returned || providers?.payment.mode !== 'paypal-sandbox-offline' || checkout.stale === true
      || !['ORDER_CREATED', 'PAYPAL_APPROVED'].includes(checkout.state)
      || order?.order_id !== returned.order_id || order?.provider_order_id !== returned.provider_order_id
      || prepared?.available !== true || prepared.consumed !== false || prepared.cancelled !== false
      || !Number.isFinite(Date.parse(prepared.expires_at)) || Date.parse(prepared.expires_at) <= now) {
    throw new Error('This return is stale, expired, consumed, or belongs to another order. No action was sent.');
  }
  return {expected_revision: revision, snapshot_hash: checkout.snapshot_hash,
    return_state: returned.return_state, provider_order_id: returned.provider_order_id, outcome: returned.outcome};
}

export function validateBootstrap(data) {
  validateEnvelope(data);
  if (!Number.isSafeInteger(data.revision) || typeof data.csrf_token !== 'string' || !data.csrf_token
      || !Array.isArray(data.catalog) || data.catalog.length !== 6) {
    throw new Error('The sample catalog contract is incomplete. No order can be created.');
  }
  const seen = new Set();
  for (const product of data.catalog) {
    if (seen.has(product.sku_id) || typeof product.sku_id !== 'string' || !product.source
        || typeof product.source.text !== 'string' || !product.baseline) {
      throw new Error('The sample catalog contains an invalid or duplicate SKU.');
    }
    formatMoney(product.price_minor, product.currency);
    seen.add(product.sku_id);
  }
  return data;
}

export function validateCheckout(checkout, catalog, providers) {
  if (!checkout) return null;
  const product = catalog.find(item => item.sku_id === checkout.sku_id);
  const historicalOrder = checkout.stale === true && Boolean(checkout.order);
  if (!product || !checkout.review_id || (!checkout.snapshot_hash && checkout.state !== 'ANALYSIS_BLOCKED') || !checkout.source
      || typeof checkout.source.text !== 'string'
      || typeof checkout.source.source_id !== 'string'
      || !Number.isInteger(checkout.source.revision) || checkout.source.revision < 1
      || !/^[a-f0-9]{64}$/.test(checkout.source.sha256)
      || (!historicalOrder && (checkout.source.source_id !== product.source.source_id
        || checkout.source.sha256 !== product.source.sha256
        || checkout.source.revision !== product.source.revision
        || checkout.source.text !== product.source.text))) {
    throw new Error('The review no longer matches the current catalog source. Reload and review again.');
  }
  formatMoney(checkout.amount.minor, checkout.amount.currency);
  if (!historicalOrder && (checkout.amount.minor !== product.price_minor || checkout.amount.currency !== product.currency)) {
    throw new Error('The reviewed item total differs from the catalog. No order can be created.');
  }
  const modes = validateProviders(providers);
  const context = modes.analysis.mode === CONTEXT_MODE;
  const historicalContext = checkout.stale === true && checkout.model?.execution_mode === CONTEXT_MODE
    && modes.payment.mode === 'fixture';
  const historicalLegacy = context && checkout.stale === true && !checkout.analysis
    && checkout.model?.execution_mode !== CONTEXT_MODE && typeof checkout.model?.is_fixture === 'boolean';
  if ((context && !historicalLegacy) || historicalContext) {
    validateContextAnalysis(checkout);
    if (checkout.stale !== true && checkout.model.execution_kind !== modes.analysis.execution_kind) {
      throw new Error('The analysis configuration no longer matches this review.');
    }
  } else if (checkout.analysis || checkout.model?.execution_mode === CONTEXT_MODE) {
    throw new Error('Context analysis requires its explicit server mode.');
  }
  if ((!historicalContext && !historicalLegacy && checkout.model?.is_fixture !== modes.analysis.is_fixture)
      || (checkout.order && checkout.order.provider_mode !== modes.payment.mode)) {
    throw new Error('An inconsistent adapter response was blocked.');
  }
  const order = checkout.order;
  if (order?.approval_url != null && (modes.payment.mode !== 'paypal-sandbox-offline'
      || !/^[A-Z0-9]{1,36}$/.test(order.provider_order_id)
      || order.approval_url !== `https://www.sandbox.paypal.com/checkoutnow?token=${order.provider_order_id}`)) {
    throw new Error('Unsupported approval URL. No navigation is permitted.');
  }
  if (!Array.isArray(checkout.conditions) || checkout.conditions.length < 1 || checkout.conditions.length > 2
      || !Array.isArray(checkout.results)) throw new Error('The review conditions are incomplete.');
  const conditionIds = new Set(checkout.conditions.map(condition => condition.condition_id));
  if (conditionIds.size !== checkout.conditions.length) throw new Error('Duplicate review conditions.');
  checkout.conditions.forEach(conditionLabel);
  if (checkout.state !== 'ANALYSIS_BLOCKED') {
    const resultIds = new Set(checkout.results.map(result => result.condition_id));
    if (resultIds.size !== conditionIds.size || checkout.results.length !== conditionIds.size
        || [...conditionIds].some(id => !resultIds.has(id))) throw new Error('A condition result is missing.');
  }
  for (const result of checkout.results) {
    if (!conditionIds.has(result.condition_id) || !Object.hasOwn(OUTCOMES, result.status)
        || !Array.isArray(result.evidence)) throw new Error('Invalid fixture result.');
    if (result.status !== 'unknown' && result.evidence.length === 0) throw new Error('A match or conflict needs source evidence.');
    result.evidence.forEach(span => evidenceText(checkout.source, span));
  }
  return checkout;
}

export function requiredAcknowledgements(checkout, status) {
  return checkout.results.filter(result => result.status === status).map(result => result.condition_id);
}

export function confirmPayload(checkout, revision, reviewed, acknowledged) {
  if (!checkout || checkout.stale === true || checkout.order || checkout.state !== 'REVIEW_REQUIRED' || !reviewed) {
    throw new Error('Review this snapshot before confirming.');
  }
  const unknown = requiredAcknowledgements(checkout, 'unknown');
  const conflicts = requiredAcknowledgements(checkout, 'conflict');
  if ([...unknown, ...conflicts].some(id => !acknowledged.has(id))) {
    throw new Error('Acknowledge each unknown or conflicting condition separately.');
  }
  return {
    expected_revision: revision,
    review_id: checkout.review_id,
    snapshot_hash: checkout.snapshot_hash,
    confirmed_sku_id: checkout.sku_id,
    confirmed_condition_ids: checkout.conditions.map(condition => condition.condition_id),
    acknowledged_unknown_ids: unknown,
    acknowledged_conflict_ids: conflicts,
  };
}

export function mergedEvidenceRanges(checkout) {
  const ranges = checkout.results.flatMap(result => result.evidence)
    .map(span => ({start: span.start, end: span.end})).sort((a, b) => a.start - b.start);
  const merged = [];
  for (const range of ranges) {
    const previous = merged.at(-1);
    if (previous && range.start < previous.end) previous.end = Math.max(previous.end, range.end);
    else merged.push({...range});
  }
  return merged;
}

/** Persist only random operation keys, never CSRF/owner credentials or source text. */
export function operationKey(storage, snapshotHash, action, createUUID) {
  if (!['create', 'capture'].includes(action) || !/^[a-f0-9]{64}$/.test(snapshotHash)) {
    throw new Error('Invalid operation key binding.');
  }
  const name = `cart-readback:fixture:v1:${snapshotHash}:${action}`;
  const existing = storage.getItem(name);
  const key = existing || createUUID();
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(key)) {
    throw new Error('The stored operation key is invalid. No request was sent.');
  }
  if (!existing) storage.setItem(name, key);
  return key;
}
