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

export function validateBootstrap(data) {
  if (data.api_version !== '1' || data.mode !== 'fixture' || !FEATURE_FLAGS.fixture) {
    throw new Error('This UI supports fixture mode only. Live/model/PayPal integrations are not enabled.');
  }
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

export function validateCheckout(checkout, catalog) {
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
  if (checkout.model?.is_fixture !== true || (checkout.order && checkout.order.provider_mode !== 'fixture')) {
    throw new Error('An unsupported non-fixture adapter response was blocked.');
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
