# CartReadback HTTP API contract — CR-001

Status: v1 implementation contract, frozen for Ryan/Chloe on 2026-11-02 UTC. Not an executed integration result. All sample catalog/model/payment data is synthetic. API v1 defaults to offline `fixture` mode. Live money is outside scope; real sandbox/model adapters are disabled unless separately configured **and authorized**. Merely finding credentials is not authorization.

## C01 — Transport, authority and response envelope

- Local-only Python service, bound to loopback, serves `ui/` and `/api/*` on the same origin. No permissive CORS. Validate exact configured Host and Origin; reject non-loopback binding. A production/public deployment requires a new review, HTTPS and real identity/session controls.
- `GET /api/bootstrap` may initialize a random browser session and returns a session-bound CSRF token. Cookie: random opaque owner/session ID, `HttpOnly; SameSite=Strict; Path=/`; `Secure` when HTTPS. Do not put ownership/CSRF in URL/localStorage. Missing owner on later requests is not a wildcard owner.
- `/api/orders` and `/capture` additionally require `Idempotency-Key`: a UUID generated once for each buyer create/capture action, reused for that action after transport retries or reload. Persist its binding to owner + route + canonical semantic payload hash (excluding expected_revision, which is checked independently); reuse with different semantic content is a 409 `IDEMPOTENCY_CONFLICT`. These browser keys are not upstream PayPal request IDs: upstream keys remain separate server-generated UUIDs and never derive money/authority from the client. Durable unique business-operation constraints remain necessary even if client sends a fresh key.
- Every POST requires `Content-Type: application/json`, an exact allowed Origin and `X-CSRF-Token`. The expected owner is resolved from the cookie, never a JSON field. GET/HEAD never approve, verify, capture, reconcile or alter business state. Fixture approval is an explicit POST, never an automatic timer.
- Body maximum 16 KiB; reject malformed UTF-8/JSON, duplicate JSON keys, NaN/Infinity, unexpected fields, wrong exact scalar types (`bool` is not an integer), unexpected nesting (maximum four levels) or oversized values and unsupported methods. Reject unknown route/query parameters. Client sends no money, currency, merchant, arbitrary provider URL or provider idempotency key. C11 narrowly allows read-only buyer-return query fields and a correlated provider token in its explicit return POST.
- All mutation requests include `expected_revision`: an integer >= 0, exact current **session aggregate** revision. Validate ownership and revision within the same SQLite write transaction as the transition. Every accepted state transition increments revision once; read-only bootstrap does not. Reserve pending provider work durably before dispatch; that transition also advances revision. Responses return the final current revision. Invalid requests cause no business-state transition; a detected stale business binding may explicitly transition to `REVIEW_REQUIRED` and return the new revision.
- Success envelope: `{ "api_version":"1", "mode":"fixture", "revision":1, "checkout":{...} }`. C11 adds independent provider descriptors and aggregate `offline` mode for injected nonfixture seams. Every displayed output retains the fixture/offline/sandbox distinction. No field calls fixture output real AI or PayPal evidence.
- Error envelope: `{ "api_version":"1", "mode":"fixture", "revision":1, "error":{"code":"STALE_REVISION","message":"Reload the current review before continuing."} }`. Do not expose stack traces, secrets, provider credentials or complete provider request headers. Bootstrap after an error retrieves current authoritative state; do not silently replay a payment intent.
- HTTP: 400 invalid schema/body, 403 CSRF/origin/owner failure (unknown or foreign entity may be 404), 404 missing owned resource, 409 stale revision/snapshot/state or payment uncertainty, 413 oversized body, 415 content type, 422 invalid source/model result, 503 disabled adapter/provider unavailable. Error codes are stable; UI does not parse English text.

## C02 — Bootstrap and catalog

`GET /api/bootstrap` ->

```json
{
  "api_version":"1", "mode":"fixture", "notice":"Synthetic catalog, model and payment fixtures. No money moves.",
  "csrf_token":"opaque-session-token", "revision":0,
  "catalog":[{
    "sku_id":"KB-UK-C2C", "name":"Synthetic keyboard example", "price_minor":7900, "currency":"USD",
    "source":{"source_id":"catalog:KB-UK-C2C","revision":1,"sha256":"64-lowercase-hex","text":"Exact source text"},
    "baseline":{"layout":"UK_QWERTY","included_cable":"USB-C to USB-C"}
  }],
  "checkout":null
}
```

Source and catalog revisions are server-owned positive exact integers (bool rejected). There are exactly six distinct server-owned keyboard SKUs, one unit per checkout, one currency USD. `baseline` is a good structured table derived from **the identical source**, including explicit `unknown` when missing; it is not privileged information withheld from AI. `baseline.layout` uses the three language-layout enum values or `unknown`; `baseline.included_cable` uses the two cable-type strings, `none` only for explicit exclusion, or `unknown` for absent/insufficient information. Catalog names and text are escaped/rendered as plain text. UI may not convert absent inclusion text to “not included.”

## C03 — Analyze the buyer's stated conditions

`POST /api/analyze`

```json
{"expected_revision":0,"sku_id":"KB-UK-C2C","conditions":[{"kind":"layout","value":"UK_QWERTY"},{"kind":"included_cable","value":"USB-C to USB-C"}]}
```

- `sku_id`: exact known catalog ID, maximum 64 ASCII characters. `conditions`: 1–2 objects, no duplicate kind, no duplicate or unknown fields. `layout` values: `UK_QWERTY`, `DE_QWERTZ`, or `US_QWERTY`. These are language/keycap layouts, not physical ANSI/ISO geometry; UK and DE may both be ISO. Never infer UK from ISO. `included_cable` values: `USB-C to USB-C`, `USB-A to USB-C`, or `any cable`. These typed buyer inputs keep the first scope narrow; no compatibility/arrival/performance inference. Empty requirements are rejected rather than invented by the model.
- This creates a new immutable review, makes it the session's active review, and invalidates any older confirmation. Any editable field change must immediately clear UI consent and disable old order/capture buttons, even before the next analysis. The server can authorize only the last submitted state, so the UI must not submit old hashes after displaying unsent edits.
- A new analysis is blocked while any create/capture operation is in flight/unknown, or after a completed checkout. This v1 freezes selected SKU and conditions after order creation: no new analysis after any order or create operation exists. Expose the block honestly. There is no unsafe “restart” that replaces an unknown or existing payment; reconciliation remains attached to the same order. A later explicit cancel/new-checkout flow needs a separate contract.
- Server-generated `condition_id` is stable within this review only (e.g. `c1`, `c2`); input order is retained. The model receives text and conditions only, with no payment tools, secrets or authority.

`checkout` in the response:

```json
{
  "review_id":"opaque-review-id", "state":"REVIEW_REQUIRED", "sku_id":"KB-UK-C2C",
  "conditions":[{"condition_id":"c1","kind":"layout","value":"UK_QWERTY"}],
  "results":[{"condition_id":"c1","status":"match","explanation":"The source explicitly names UK QWERTY.","evidence":[{"source_id":"catalog:KB-UK-C2C","start":0,"end":9,"quote":"UK QWERTY"}]}],
  "snapshot_hash":"64-lowercase-hex", "confirmation_id":null,
  "amount":{"minor":7900,"currency":"USD"},
  "source":{"source_id":"catalog:KB-UK-C2C","revision":1,"sha256":"64-lowercase-hex","text":"UK QWERTY ..."},
  "model":{"provider":"fixture","model_version":"fixture-v1","prompt_version":"readback-v1","adapter_version":"fixture-v1","is_fixture":true},
  "order":null
}
```

- Exactly one result per condition ID, no missing/duplicate/foreign conditions. Status is exactly lowercase `match`, `conflict` or `unknown`. Explanation is plain text <= 500 Unicode code points. Maximum four evidence spans per result; quote <= 1000 code points, entire source <= 16,000 code points. Source bytes/revisions/hash and allowed model configuration are server-owned.
- Spans use **Unicode code point** offsets, zero-based, half-open `[start,end)`, not UTF-8 bytes or JavaScript UTF-16 units. Exact integer `0 <= start < end <= len(source.text)` and `source.text[start:end] == quote` must hold. JS should use `Array.from(text)` for slicing or convert offsets explicitly. Reject source-ID mismatch. Preserve source as received; no invisible Unicode normalization before hashing/slicing.
- `match`/`conflict` require at least one explicit supporting span. `unknown` may have no spans; evidence must not pretend absence is proof of exclusion. A valid quote proves text identity, not semantic entailment. Contradictory or insufficient source content should remain unknown/block, not be repaired by the model. Fixture expectations and adversarial human/independent review test grounding separately.
- Schema/span failure yields `ANALYSIS_BLOCKED`, no confirmable snapshot and a 422 error/result; never silently replace malformed evidence with a successful result. The implementation may expose `analysis_error` as a stable code on this checkout. Payment is unavailable for blocked analysis.

## C04 — Review confirmation

`POST /api/confirm`

```json
{"expected_revision":1,"review_id":"opaque-review-id","snapshot_hash":"64-lowercase-hex","confirmed_sku_id":"KB-UK-C2C","confirmed_condition_ids":["c1"],"acknowledged_unknown_ids":[],"acknowledged_conflict_ids":[]}
```

- `confirmed_sku_id` must equal the active SKU. `confirmed_condition_ids` must be the exact duplicate-free set of all review condition IDs. Bootstrap must restore the owned current review/order/operation after reload, including pending/unknown state; it never synthesizes a fresh payment.

- UNKNOWN and conflict acknowledgement arrays must each equal exactly the corresponding current result-ID set (not a boolean “accept all”). No extra IDs. All three arrays may contain at most two IDs. Each acknowledgement is an individual unchecked-by-default UI control.
- UNKNOWN wording: “The source does not establish [condition]. I choose to continue without knowing this.” Conflict wording: “The source conflicts with [condition]. I keep this SKU and understand the mismatch.” Buyer may instead change SKU/conditions and reanalyze. Acknowledgement changes neither the proposed status nor source facts.
- Require active review, current catalog/price/source/model/prompt/adapter/validator versions and exact snapshot hash. A stale check invalidates confirmation and requires fresh analysis/review. Consent never migrates to a newer source or model version automatically.
- Success: `state=SNAPSHOT_CONFIRMED`, new opaque `confirmation_id`, persisted immutable consent details/time/snapshot hash; revision increments. Matching an opaque hash is not sufficient without owned current records.

## C05 — Create an order

`POST /api/orders`

```json
{"expected_revision":2,"review_id":"opaque-review-id","snapshot_hash":"64-lowercase-hex","confirmation_id":"opaque-confirmation-id"}
```

Server revalidates C04 and calculates amount from current catalog in integer minor units. Quantity is fixed at one, zero tax/shipping/discount in this fixture scope. Persist create payload hash and server-generated UUID idempotency key before adapter dispatch. One logical create operation and at most one provider order for this snapshot. A repeated equivalent request returns the existing operation/order without dispatching a second logical create; stale revision still fails before action. Concurrent callers cannot bypass the unique operation constraint.

Success: `state=ORDER_CREATED` and

```json
{"order_id":"opaque-local-order-id","provider_order_id":"FIXTURE-opaque-id","provider_mode":"fixture","status":"CREATED","approval_url":null}
```

Provider mode `sandbox` would require a separately authorized adapter and validated PayPal approval URL; the browser never supplies or chooses a provider API URL. Fixture `approval_url` is always null and the UI says “Simulate PayPal approval (fixture).” No automatic approval, redirect-to-success or capture.

## C06 — Approve and verify, not capture

All paths use the **local** opaque `order_id`, resolved with owner + snapshot binding. IDs are never authorization. Base request:

```json
{"expected_revision":3,"snapshot_hash":"64-lowercase-hex"}
```

- `POST /api/orders/{order_id}/fixture-approve`: exists only when payment provider is fixture; simulates buyer approval and moves to `PAYPAL_APPROVED`. Must be visibly labelled fixture. In real sandbox there is no local approve endpoint.
- `POST /api/orders/{order_id}/verify`: queries the stored provider order ID server-side and compares the normalized verification object (C09). Moves to `SERVER_RECHECKED` only if approved and all required identity/items/money checks pass. An unapproved order remains `ORDER_CREATED` with `ORDER_NOT_APPROVED` error. Browser return parameters, text, query order ID or approval callback alone never establish approval. No GET return route mutates business state; it may render UI which offers this POST.
- Provider response mismatch or omitted mandatory verification facts blocks capture, records a reason and requires reconciliation. Do not mark `SERVER_RECHECKED` because a response merely has `status=APPROVED`.

## C07 — Explicit final capture and reconciliation

`POST /api/orders/{order_id}/capture`

```json
{"expected_revision":5,"snapshot_hash":"64-lowercase-hex","confirmation_id":"opaque-confirmation-id","final_confirmation":true}
```

- Require exact true (not truthy), current owned confirmation, `SERVER_RECHECKED`, fresh source/catalog/model bindings, and no unresolved create/capture operation. UI presents final SKU, conditions/statuses, money and fixture/sandbox badge beside the explicit button. Nothing about page visitation, model output, source text or PayPal approval supplies this final intent.
- Requery and fully validate the provider order again **inside the capture operation**, then recheck all current bindings and reserve a single capture operation with an atomic compare-and-set before external dispatch. No capture on stale/mismatched/unknown verification. Serialize local edits against capture reservation; authorization is evaluated at this reservation boundary, not as a promise that an already-dispatched remote operation can be recalled.
- On valid completed capture, persist provider capture ID, exact amount/currency and completed status: `COMPLETED`; `order.status=COMPLETED`. A pending capture is not completion. A returned page or 2xx alone is not completion.
- Timeout, lost response, process crash after dispatch, malformed/ambiguous provider response: persist `PAYMENT_UNKNOWN`, whether operation is create or capture, same idempotency key/payload hash and any known provider ID. Never auto-capture, auto-refund, auto-recreate or label success/failure from timeout alone.
- `POST /api/orders/{order_id}/reconcile` uses C06 base request and is a **read-only provider lookup**, though the resulting local recorded observation/revision may change. It may move known completed capture to `COMPLETED`, known un-captured approved order to `SERVER_RECHECKED` (fresh explicit final capture intent is still required), or remain `PAYMENT_UNKNOWN`. A query result that is not completed does not prove an earlier request can never complete. Do not clear an unresolved capture simply because an immediate GET is still APPROVED. No new capture dispatch while unresolved.
- A create timeout may have no local order ID yet: bootstrap must still expose its pending/unknown operation under `checkout.order` with an allocated local `order_id` and nullable provider ID. Reconcile may honestly remain unknown with `CREATE_OUTCOME_UNKNOWN`; do not invent a provider-order lookup without an ID. Safe same-key replay, if ever added, requires separately reviewed documented retention/endpoint semantics; v1 does not auto-replay POSTs.
- A double click or retry for a terminal captured order returns the stored completed representation, without dispatch. Supplying a stale revision may instead return 409 and bootstrap shows completion. UI must not offer “start another payment” to clear uncertainty.

## C08 — Required state and error vocabulary

States: `REVIEW_REQUIRED`, `ANALYSIS_BLOCKED`, `SNAPSHOT_CONFIRMED`, `ORDER_CREATE_PENDING`, `ORDER_CREATED`, `PAYPAL_APPROVED`, `SERVER_RECHECKED`, `CAPTURE_PENDING`, `PAYMENT_UNKNOWN`, `COMPLETED`. Optional internal `STALE` marker belongs to old reviews/orders; they are never capturable. UI must tolerate pending and unknown states and disable monetary actions.

Minimum stable error codes: `INVALID_INPUT`, `PAYLOAD_TOO_LARGE`, `CSRF_REJECTED`, `ORIGIN_REJECTED`, `NOT_FOUND`, `STALE_REVISION`, `STALE_SNAPSHOT`, `INVALID_STATE`, `ANALYSIS_BLOCKED`, `ACKNOWLEDGEMENT_REQUIRED`, `ORDER_NOT_APPROVED`, `ORDER_MISMATCH`, `PAYMENT_UNKNOWN`, `CREATE_OUTCOME_UNKNOWN`, `ADAPTER_DISABLED`, `IDEMPOTENCY_CONFLICT`. An implementation-specific diagnostic may add context, not downgrade these guarantees.

## C09 — Adapter boundaries and sandbox gate

`ReadbackAdapter.analyze(source, conditions) -> typed candidate`; service validates the returned strict schema and exact spans. Adapter configuration identity includes provider, model/version, prompt hash/version, adapter version and validator schema version. Current fixture is a deterministic test double, not genuine AI. It must be replaceable without granting payment tools to a model.

`PaymentAdapter.create_order(authoritative_request, request_id)`, `get_order(provider_order_id)`, `capture_order(provider_order_id, request_id)` -> normalized typed observations. Monetary observations contain no floating point. Adapter performs no independent workflow retry/capture and has no live fallback.

Minimum normalized verification fields: `provider_mode`, `provider_order_id`, `status`, `intent`, `merchant_id`, `reference_id`, `custom_id`, `items[{sku_id,name,quantity,unit_amount_minor,currency}]`, `amount_minor`, `currency`, `captures[{capture_id,status,amount_minor,currency}]`. Exactly one purchase unit and one item, quantity one, expected intent CAPTURE; configured sandbox merchant ID must match. `reference_id` binds the local order; `custom_id` binds the snapshot. Source of each normalized field must be documented by the actual sandbox adapter. Future create/capture requests should request `Prefer: return=representation`; default/minimal responses are not evidence of fields they omit. Follow with a server-side GET when needed; GET may still omit required fields and must then fail closed. Unknown/missing fields fail closed. Comparing persisted create payload alone does not prove the remote order is unchanged; if PayPal cannot return a required field, revise this contract with explicit evidence and guard design before enabling the adapter.

PayPal upstream shapes to investigate: `intent`, `purchase_units[].{reference_id,custom_id,payee.merchant_id,amount,items[]}`, `items[].{sku,name,quantity,unit_amount}`, and completed `purchase_units[].payments.captures[]`. Exact create/get/capture response behavior, merchant-ID availability and full expected verification are **not tested here**. Do not implement a fake assurance from this candidate map. Capture adapter must not treat `payer.payer_id` as merchant identity.

Official sources inspected 2026-11-02 UTC: [Orders v2 reference](https://developer.paypal.com/api/orders/v2) lists distinct create/get/capture endpoints; [API requests](https://developer.paypal.com/api/rest/requests/) documents distinct sandbox and live API hosts; [idempotency guidance](https://developer.paypal.com/api/rest/reference/idempotency/) warns header support/retention vary by endpoint and simultaneous same-key requests may fail. These are documentation references, not successful sandbox calls. Only allow `https://api-m.sandbox.paypal.com` in a future approved API adapter; do not follow arbitrary redirects or response links as API destinations.

## C10 — Handoff and acceptance

Local planning identifiers CR-001 (contract), CR-002 (backend), CR-003 (UI), and CR-004 (independent safety review) are historical planning labels, **not GitHub issue numbers**. The private repository now exists; issue #1 and branch `chore/1-repository-scaffold` cover this documentation/API-contract scaffold import. Executable imports require their own real issues and branches. Draft PR existence and final head must be verified in GitHub; this contract is not evidence of either. Ryan owns deterministic backend/fixture tests; Chloe owns UI and same-material baseline; Blair independently attacks stale/forged/unknown/race flows; dot resolves scope changes.

Acceptance: six fixture SKUs; full no-money happy path; individually unchecked conflict/unknown acknowledgement; stale catalog/source/model/intent cannot capture; money forgery rejected; duplicate/foreign IDs rejected; CSRF/origin/body limits enforced; durable timeout/crash unknown path and no recreation; repeated/concurrent operations do not double-dispatch; malformed/injected model/source cannot cross payment boundary; UI Unicode highlights agree with backend source; no external calls in default mode. Report actual checks only. Real AI inference, real PayPal sandbox, customer demand/time savings and public deployment remain not run.


## C11 — Offline buyer-return and independent provider modes

Issue #19 extends v1 without enabling provider network I/O. Every server envelope,
including errors, includes `providers` with independent `analysis` and `payment`
objects and `network_enabled:false`. Analysis `mode` is `fixture` when metadata
`is_fixture:true`, otherwise `injected-offline`; payment `mode` is the adapter's
own identity (`fixture` or supported `paypal-sandbox-offline`). Both objects carry
an exact boolean `is_fixture`. Aggregate `mode` is `fixture` only when both are
fixtures, otherwise `offline`. Unsupported adapter identities fail closed in the
UI. Legacy all-fixture client test envelopes may omit descriptors; offline ones
cannot. These describe this build's configured offline seams, not a guarantee
about arbitrary executable adapter code supplied by an embedding application.
A future network-capable factory must revise/review this contract before use.

Only an explicitly injected offline PayPal adapter may prepare buyer callbacks
by setting `buyer_return_origin` to the exact literal-loopback server origin.
`LocalServer` rejects an origin mismatch at construction. The CLI has no selector.
The Service generates 32 random state bytes, stores an owner/order/snapshot-bound
hash and 20-minute expiry in private checkout context, and freezes callback URLs
in the existing create-operation wire ledger. Origin/configuration changes alter
the adapter identity. The raw state is not in bootstrap/checkout/error/audit
output; it is present only in the private durable callback request. Private DBs
must remain private.

Create preparation uses `payment_source.paypal.experience_context` with
`user_action:CONTINUE`, `shipping_preference:NO_SHIPPING`, fixed return/cancel
URLs under `/payment-return`, and outcome `approved`/`cancelled`. These are
fabricated-envelope tests, not proof PayPal accepts this payload, literal-loopback
URLs or the exact chosen callback query shape.

`GET /payment-return?order_id=<uuid-v4>&state=<43-base64url>&outcome=approved|cancelled&token=<provider-id>`
only serves the same static app. Optional bounded `PayerID` is ignored. Duplicate,
unknown, missing, malformed or oversized fields fail closed. This GET does not
resolve an owner, initialize a session, query a provider, consume state or capture.
After immediate query removal, `/payment-return` remains a reloadable static
route. Strict cookies are unchanged: the app obtains the existing owner/CSRF via
same-origin bootstrap. No cookie relaxation is inferred from a return.

The UI strips the callback query synchronously before bootstrap and keeps return
values only in page memory. It checks the returned local/provider IDs against
owned current state and offers an explicit return recheck button. It never
navigates a fabricated sandbox URL, auto-POSTs on landing, restores a return from
storage, or treats a callback as approval. Refresh/Back/Forward do not replay the
POST and clear final capture intent.

`POST /api/orders/{order_id}/buyer-return` requires the normal exact Origin,
existing owner, CSRF, current revision/snapshot, and exactly these extra fields:
`return_state`, `provider_order_id`, `outcome`. It accepts only ORDER_CREATED or
PAYPAL_APPROVED, current configuration/source/consent and the unexpired,
unconsumed matching state. It performs a read-only GET for the same stored
provider order outside the DB lock, then revalidates all bindings before commit.

Only complete verified APPROVED facts can establish SERVER_RECHECKED. A forged
approved return while provider facts remain CREATED consumes state and retains
ORDER_CREATED. Mismatch/timeout consumes state and preserves PAYMENT_UNKNOWN,
with reconciliation on the same order. A successful cancellation return consumes
state, records cancellation intent and preserves the existing CREATED or APPROVED
order. It never asserts a remote void/refund/failure, unlocks editing, recreates an
order or captures. All returns still require a separate fresh explicit final
capture action, with the existing mandatory provider GET and durable reservation.

Public `order.buyer_return` exposes only availability, expiry, consumed/cancelled
flags. Validated `order.approval_url`, when prepared, is nonnavigable offline text.
The exact required PayPal return parameters, actual session/cookie behavior,
provider approval/capture/recovery and native browser behavior remain unverified.
