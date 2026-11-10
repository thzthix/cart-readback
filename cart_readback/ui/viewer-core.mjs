/** Separate read-only Gemini contract. This module grants no action authority. */
import {formatMoney, conditionLabel, evidenceText} from './core.mjs';
const MODE = 'genuine-gemini-capacity';
const KINDS = ['unavailable', 'fabricated-offline', 'provider-runtime'];
const exact = (v, keys) => v !== null && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const text = (v, max = 16000) => typeof v === 'string' && v.length > 0 && Array.from(v).length <= max;
const fail = () => { throw new Error('Unsupported or inconsistent review data. No action is available.'); };
const DIAGNOSTIC_STAGES = new Set(['preconnect', 'guard', 'connect', 'credential', 'request', 'status', 'body', 'cleanup', 'exchange', 'exchange-validation']);
const DIAGNOSTIC_CATEGORIES = new Set(['MODEL_TIMEOUT', 'MODEL_UNAVAILABLE', 'GEMINI_CAPACITY_BLOCKED', 'GEMINI_RUN_BLOCKED', 'UNEXPECTED_FAILURE', 'MODEL_OUTCOME_UNKNOWN', 'MODEL_REFUSED', 'MODEL_INCOMPLETE', 'INVALID_PROPOSAL', 'STALE_SNAPSHOT']);
function validateDiagnostic(checkout) {
  const d = checkout.analysis_diagnostic;
  if (checkout.state !== 'ANALYSIS_BLOCKED' || !exact(d, ['stage', 'category', 'http_status'])
      || !DIAGNOSTIC_STAGES.has(d.stage) || !DIAGNOSTIC_CATEGORIES.has(d.category)
      || !(d.http_status === null || (Number.isInteger(d.http_status) && d.http_status >= 100 && d.http_status <= 599))) fail();
}
function source(s) {
  if (!exact(s, ['source_id', 'revision', 'sha256', 'text']) || !text(s.source_id, 128)
      || !Number.isSafeInteger(s.revision) || s.revision < 1 || !/^[a-f0-9]{64}$/.test(s.sha256)
      || !text(s.text)) fail();
}
export function validateViewer(data) {
  if (!exact(data, ['api_version', 'mode', 'providers', 'revision', 'checkout', 'notice', 'catalog', 'viewer'])
      || !text(data.notice, 2000) || data.api_version !== '1' || data.mode !== 'mixed'
      || !exact(data.viewer, ['version', 'review_only', 'configured_model', 'expected_model_version'])
      || data.viewer.version !== 'gemini-host-result-viewer-v1' || data.viewer.review_only !== true
      || !['gemini-2.5-flash-lite', 'gemini-3.5-flash-lite'].includes(data.viewer.configured_model)
      || typeof data.viewer.expected_model_version !== 'string'
      || !(new RegExp('^' + data.viewer.configured_model.replaceAll('.', '\\.') + '(?:-[a-z0-9.-]{1,64})?$')).test(data.viewer.expected_model_version)
      || Object.hasOwn(data, 'csrf_token') || !Number.isSafeInteger(data.revision) || data.revision < 0) fail();
  const p = data.providers; const a = p?.analysis;
  if (!exact(p, ['analysis', 'payment', 'network_enabled'])
      || !exact(p.payment, ['mode', 'is_fixture']) || p.payment.mode !== 'fixture' || p.payment.is_fixture !== true
      || !exact(a, ['mode', 'is_fixture', 'dispatch_available', 'execution_kind'])
      || a.mode !== MODE || a.is_fixture !== false || typeof a.dispatch_available !== 'boolean'
      || !KINDS.includes(a.execution_kind) || (a.execution_kind === 'unavailable' && a.dispatch_available)
      || p.network_enabled !== (a.execution_kind === 'provider-runtime' && a.dispatch_available)) fail();
  if (!Array.isArray(data.catalog) || data.catalog.length !== 1) fail();
  const product = data.catalog[0];
  if (!exact(product, ['sku_id', 'name', 'price_minor', 'currency', 'quantity', 'catalog_revision', 'source', 'baseline'])
      || product.quantity !== 1 || !Number.isSafeInteger(product.catalog_revision) || product.catalog_revision < 1
      || !text(product.sku_id, 64) || !text(product.name, 500)
      || !exact(product.baseline, ['layout', 'included_cable'])
      || !['UK_QWERTY', 'DE_QWERTZ', 'US_QWERTY', 'unknown'].includes(product.baseline.layout)
      || !['USB-C to USB-C', 'USB-A to USB-C', 'none', 'unknown'].includes(product.baseline.included_cable)) fail();
  source(product.source); formatMoney(product.price_minor, product.currency);
  const c = data.checkout;
  if (c === null) return data;
  const m = c?.model; const outcome = c?.analysis;
  const checkoutKeys = ['review_id', 'state', 'sku_id', 'conditions', 'results', 'snapshot_hash', 'confirmation_id', 'order', 'amount', 'source', 'model', 'analysis'];
  if (c && Object.hasOwn(c, 'stale')) checkoutKeys.push('stale');
  if (c && Object.hasOwn(c, 'analysis_error')) checkoutKeys.push('analysis_error');
  if (c && Object.hasOwn(c, 'analysis_diagnostic')) {
    checkoutKeys.push('analysis_diagnostic');
    validateDiagnostic(c);
  }
  if (!exact(c, checkoutKeys) || (Object.hasOwn(c, 'analysis_error')
      && (c.state !== 'ANALYSIS_BLOCKED' || !text(c.analysis_error, 128)))
      || !exact(c.amount, ['minor', 'currency']) || !['REVIEW_REQUIRED', 'ANALYSIS_BLOCKED'].includes(c.state)
      || c.order !== null || c.confirmation_id !== null || !text(c.review_id, 128)
      || c.sku_id !== product.sku_id || (Object.hasOwn(c, 'stale') && typeof c.stale !== 'boolean')
      || !exact(m, ['provider', 'model_version', 'prompt_version', 'adapter_version', 'validator_version', 'is_fixture', 'execution_mode', 'execution_kind'])
      || m.provider !== 'google-gemini-generate-content'
      || !['gemini-2.5-flash-lite', 'gemini-3.5-flash-lite'].includes(m.model_version)
      || m.model_version !== data.viewer.configured_model
      || m.prompt_version !== 'cartreadback-prompt-v2-wire'
      || m.adapter_version !== 'genuine-gemini-generation-v1'
      || m.validator_version !== 'strict-spans-v1+ordered-results-v1'
      || m.is_fixture !== false || m.execution_mode !== MODE || !KINDS.includes(m.execution_kind)
      || (c.stale !== true && m.execution_kind !== a.execution_kind)
      || !exact(outcome, ['strategy', 'dispatch_state', 'accounting_state', 'usage_observed', 'evidence_kind'])
      || outcome.strategy !== 'gemini-capacity-v1'
      || !['not-attempted', 'attempted'].includes(outcome.dispatch_state)
      || !['unobserved', 'known', 'unknown'].includes(outcome.accounting_state)
      || typeof outcome.usage_observed !== 'boolean'
      || !['none', 'fabricated-offline', 'provider-observation'].includes(outcome.evidence_kind)) fail();
  const attempted = outcome.dispatch_state === 'attempted';
  const observedKind = m.execution_kind === 'fabricated-offline' ? 'fabricated-offline' : 'provider-observation';
  if ((m.execution_kind === 'unavailable' && attempted)
      || (outcome.usage_observed && (!attempted || outcome.evidence_kind !== observedKind))
      || (!outcome.usage_observed && outcome.evidence_kind !== 'none')
      || (outcome.accounting_state === 'known' && !outcome.usage_observed)
      || (outcome.accounting_state === 'unobserved' && outcome.usage_observed)
      || (c.state === 'REVIEW_REQUIRED' && (!attempted || outcome.accounting_state !== 'known'
        || !/^[a-f0-9]{64}$/.test(c.snapshot_hash)))
      || (outcome.accounting_state === 'unknown' && (c.state !== 'ANALYSIS_BLOCKED'
        || c.snapshot_hash !== null || c.confirmation_id !== null || c.order !== null))
      || (c.state === 'ANALYSIS_BLOCKED' && c.snapshot_hash !== null)) fail();
  source(c.source); formatMoney(c.amount?.minor, c.amount?.currency);
  if (c.stale !== true && (['source_id', 'revision', 'sha256', 'text'].some(k => c.source[k] !== product.source[k])
      || c.amount.minor !== product.price_minor || c.amount.currency !== product.currency)) fail();
  if (!Array.isArray(c.conditions) || c.conditions.length < 1 || c.conditions.length > 2
      || !Array.isArray(c.results) || new Set(c.conditions.map(x => x.condition_id)).size !== c.conditions.length
      || new Set(c.conditions.map(x => x.kind)).size !== c.conditions.length) fail();
  for (const condition of c.conditions) {
    if (!exact(condition, ['condition_id', 'kind', 'value']) || !text(condition.condition_id, 64)) fail();
    conditionLabel(condition);
  }
  if (c.state === 'ANALYSIS_BLOCKED' ? c.results.length !== 0 : c.results.length !== c.conditions.length) fail();
  c.results.forEach((r, i) => {
    if (!exact(r, ['condition_id', 'status', 'explanation', 'evidence']) || r.condition_id !== c.conditions[i].condition_id || !['match', 'conflict', 'unknown'].includes(r.status)
        || !text(r.explanation, 500) || !Array.isArray(r.evidence) || r.evidence.length > 4
        || (r.status !== 'unknown' && !r.evidence.length)) fail();
    r.evidence.forEach(span => { if (!exact(span, ['source_id', 'start', 'end', 'quote']) || !text(span.quote, 1000)) fail(); evidenceText(c.source, span); });
  });
  return data;
}
export function accountingText(c) {
  if (!c) return 'No owned analysis attempt is shown.';
  const a = c.analysis;
  return `${a.dispatch_state === 'attempted' ? 'Dispatch claim recorded; this does not prove a request reached Google.' : 'No dispatch claim recorded.'} ${
    !a.usage_observed ? 'No usage observation.' : a.evidence_kind === 'fabricated-offline'
      ? 'Fabricated offline usage recorded; not a provider observation.'
      : 'Provider usage recorded; not an invoice or a correctness judgment.'} Accounting: ${a.accounting_state.toUpperCase()}. ${
    a.accounting_state === 'unknown' ? 'UNKNOWN is retained; capacity stays held. Do not retry or renew the analysis.' : 'Accounting does not establish semantic truth.'}`;
}

