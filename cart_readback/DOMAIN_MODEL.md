# CartReadback domain model and invariants — CR-001

Status: normative design paired with `API_CONTRACT.md` v1, not a claim the proposed schema already exists. Theo | AI Architect. A small fixture implementation may combine physical tables/JSON columns while preserving these logical entities and constraints. Keep server-owned facts, AI suggestions, buyer consent and payment observations distinct.

## D01 — Logical entities

| Entity | Minimal fields and ownership |
| --- | --- |
| BrowserSession | Random opaque owner/session ID, hashed CSRF token, monotonic integer revision, active_review_id, created_at/expiry. Owner comes from HttpOnly cookie, not JSON. |
| CatalogItem | sku_id (unique), item name, positive-integer catalog revision, price_minor (exact integer), currency USD, quantity fixed 1; SourceDocument; same-source baseline; is_fixture. Six synthetic SKUs. |
| SourceDocument | source_id, positive-integer source revision, raw text, SHA-256 of exact UTF-8 text. Product text is untrusted data. No implicit normalization. Source ID/revision identifies provenance; hash identifies bytes, not truth. |
| BuyerCondition | review-scoped generated condition_id, kind and explicit chosen value, original input order. One/two unique kinds: language layout UK_QWERTY/DE_QWERTZ/US_QWERTY and included cable USB-C to USB-C/USB-A to USB-C/any cable. No geometry-to-language inference. |
| Review | random review_id, owner, generation, immutable SKU/catalog/source/money copy, conditions, typed results, full model identity, validator version, snapshot hash, created_at. New analysis creates a new Review; old reviews remain audit data and cannot be reactivated silently. |
| ConditionResult | exactly one known condition_id; match/conflict/unknown; bounded explanation; exact evidence spans. Acknowledging unknown/conflict does not rewrite this row. |
| EvidenceSpan | source_id, start/end Unicode codepoint offsets, exact quote. `source.text[start:end] == quote`. Match/conflict require span(s); schema validity is not semantic proof. |
| Consent | random confirmation_id, owner, review_id, snapshot hash, exact confirmed SKU/condition IDs, exact unknown and conflict ID sets, recorded_at; immutable. Active pointer may be invalidated. No model-generated consent. |
| LocalOrder | random local order_id allocated before create dispatch, owner, review_id, confirmation_id, snapshot hash, immutable merchant/environment/one-item/money expectation, nullable provider_order_id, local state, provider observation, completed capture_id if known. Exists even when create times out before provider ID returns. |
| PaymentOperation | operation_id, owner/order_id, kind CREATE or CAPTURE, canonical business payload/hash, server-generated provider UUID request key, status RESERVED/DISPATCHED/UNKNOWN/SUCCEEDED/DEFINITELY_FAILED, attempt metadata, nullable provider/capture IDs, timestamps/error code. Durable before remote side effect. |
| ClientIdempotencyBinding | client UUID key, owner, route/call type, canonical semantic payload hash, logical operation_id/result. Same key plus altered semantic payload is a conflict. A new key never overrides the unique operation rule. |
| AuditObservation | append-only event_id, owner/order/operation/review refs, before/after state and revision, reason code, redacted normalized observation and time. No secrets, auth headers, full raw provider payloads or browser session tokens. |

## D02 — Canonical representations

- Price uses integer minor USD units; reject bool/float/negative/out-of-scope values. Format provider decimal strings from integer arithmetic. A future provider parser must parse exact decimal strings, require currency USD and at most two decimal places, and reject extra precision rather than round. Do not use binary floating point for validation or totals.
- Canonical JSON: UTF-8 of `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`. Admit only strict schema types and no floats. Preserve array order where meaningful (condition/source text); sort duplicate-free ID sets before canonicalization. Record the canonicalization/schema version.
- Source SHA-256 hashes the raw UTF-8 text alone. Review snapshot SHA-256 hashes the immutable envelope: schema/canonicalization version, review_id/generation, SKU and name, catalog revision, authoritative money/currency/quantity, source ID/revision/hash, complete conditions/results/evidence, provider/model/version/prompt version or hash/adapter version, validator version. Source/model/prompt/adapter/validator, condition/result, SKU/name, price or currency changes produce a different binding and invalidate prior consent.
- Client idempotency's **semantic payload** excludes `expected_revision`, CSRF/header transport data and the idempotency key itself; it includes route, owned local identifiers, snapshot, consent and final-intent value. Revision is independently checked before any transition; excluding it from the semantic hash does not bypass concurrency. Upstream request hash covers the exact authoritative provider create/capture payload. Never reuse one provider key across different call types or bodies.
- Hashes are integrity identifiers, not signatures, authentication, semantic entailment or proof of human intent. Always look up current owned records and revalidate versions.

## D03 — Minimal SQLite safeguards

1. Enable foreign keys on every connection; use short atomic write transactions, parameterized SQL and a compare-and-set `UPDATE ... WHERE owner_id=? AND revision=?`. A failed update changes no business state. A process-local lock alone is insufficient durable concurrency protection.
2. Unique keys: SKU; (source_id, source_revision); (review_id, condition_id); confirmation_id; local order_id; non-null (provider_mode, provider_order_id); (order_id, operation_kind) for one logical create/capture; provider request key; (owner_id, call_type, client_idempotency_key). Distinct client keys cannot create two logical operations.
3. Persist pending operation, immutable payload/hash, key and allocated local order ID in the same transaction that reserves the transition. Dispatch only the winning reservation. No SQLite transaction should span an external network wait. Persist a returned observation using the reserved operation identity, never whichever review is now visible.
4. Block edits/new analysis while an order/create operation exists in this v1. A pending/unknown or completed operation cannot be erased by refreshing, changing tab, creating a new review or issuing a fresh request key. Retain state across service/browser restart.
5. On restart, a reserved/dispatched operation whose outcome cannot be established is UNKNOWN, not safe-to-retry. Do not assume a crashed worker never dispatched. Reconciliation is same-order read-only lookup; no automatic POST replay in v1.
6. Store all money with an exact-integer type check and domain constraints; validate currency and every JSON field in application code as well. SQL constraints supplement, not replace, strict request/model schema validation.
7. Inject clock/repository/model/payment interfaces for tests. FakePaymentAdapter state must survive restart (SQLite or persisted fake order observations), or a reload may falsely turn a completed fake capture into a missing/new order. Fixture tests are not evidence of real provider idempotency or durability guarantees.

## D04 — State/transition invariants

| Action | Preconditions | Result / guard |
| --- | --- | --- |
| Analyze | exact owner/revision, valid SKU/conditions, no existing order/create | New immutable active review; REVIEW_REQUIRED or ANALYSIS_BLOCKED; all prior consent invalid |
| Confirm | current review/source/model/price/hash, all condition checks, exact per-unknown/conflict acknowledgement | SNAPSHOT_CONFIRMED and immutable consent |
| Create | valid owned active consent and unchanged snapshot; no logical CREATE | Reserve ORDER_CREATE_PENDING, then ORDER_CREATED or PAYMENT_UNKNOWN; never fresh create to clear uncertainty |
| Fixture approve | fixture provider only, same owned order/snapshot, CREATED | PAYPAL_APPROVED; explicitly synthetic |
| Verify | same owned order/snapshot; server-side same-order GET | SERVER_RECHECKED only for complete exact approved observation |
| Capture | explicit final true + consent, current snapshot, SERVER_RECHECKED; no unresolved operation; repeat full GET verification | Reserve CAPTURE_PENDING, then COMPLETED only for fully validated completed capture, otherwise pending/unknown/definite failure |
| Reconcile | same owned local operation/order | GET same provider ID only; preserve uncertainty unless evidence resolves the particular operation. Approved alone cannot disprove an in-flight capture. |

Authorization linearizes at the atomic capture reservation after current-version verification. Serialize local changes against this reservation; there is no promise to cancel a remote capture after dispatch. Any source/configuration change found before reservation blocks capture. The local fixture service exposes no administrative source-update API; tests may inject updates at controlled boundaries.

## D05 — Required test families and limits

- Data validation: missing/extra/duplicate JSON fields, booleans-as-ints, NaN, floats, overlong body/text, malformed UTF-8, foreign/duplicate SKU or condition IDs; all leave payment undispatched.
- Grounding: exact codepoint span checks including an astral character before quote; wrong quote/source ID/range; instruction text in catalog; absent cable remains unknown; UK and DE both ISO must conflict when language layout differs; conflicting prose is not automatically match.
- Consent: unchecked/missing/extra/duplicated unknown/conflict IDs; changed source text/revision, source hash, catalog price, SKU, conditions, results, model/prompt/adapter/validator identity; foreign review/consent/order; UI unsent edit invalidation and late responses.
- Payment: wrong merchant/environment/order/reference/custom ID, item/SKU/name/quantity, amount/currency or missing fields; approval alone; 2xx without completed capture; provider pending/timeout; process crash before/after dispatch; repeated/concurrent create/capture and new client key; create timeout without provider ID; startup with unresolved ledger.
- HTTP/UI: CSRF/origin/host/session ownership, GET no mutation, static traversal and HTML injection; default adapters cannot make network calls; reload recovers same order; fixture badge and same-material baseline remain visible; payment steps remain distinct.

A successful deterministic suite refutes selected implementation defects only. It does not establish semantic model reliability, customer time savings, merchant demand, production security, PayPal sandbox success or real-money readiness.
