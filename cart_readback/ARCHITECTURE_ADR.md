# ADR-001: source-backed suggestions inside a deterministic modular monolith

Status: **accepted for local fixture implementation** by Theo | AI Architect, 2026-11-02 UTC. Supersedes the earlier proposed state sketch. Not a real-model/PayPal integration approval. Exact wire contract: `API_CONTRACT.md` C01–C10. Domain/hash/storage constraints: `DOMAIN_MODEL.md` D01–D05.

## A01 — Context and decision

CartReadback reviews an already selected keyboard against one/two buyer-stated conditions, then binds deliberate consent to a no-money fixture order. Six text-source synthetic SKUs, language layout (UK_QWERTY/DE_QWERTZ/US_QWERTY) and included cable only. UK and DE can both be ISO; geometry is not language layout. A good structured catalog using identical material is the falsification baseline. AI value, demand and buyer effort remain unproven.

Use **one Python standard-library HTTP service plus SQLite**, served on loopback, with vanilla HTML/CSS/JS on the same origin. Internally separate catalog, analysis/grounding validation, review/consent, order/ledger, adapters and HTTP/UI serialization. Modules are boundaries for reasoning/tests, not separate deployable services. Do not add an agent orchestrator, vector database, message broker, generic shopping agent, login provider or build pipeline to demonstrate six SKUs.

FixtureReadbackAdapter is deterministic synthetic output, never labelled genuine AI. FixturePaymentAdapter simulates approval/get/capture without network or money. Future real model and PayPal sandbox adapters are interfaces only until separately configured/authorized and independently verified. There is no live endpoint fallback and no secret/account discovery.

## A02 — Alternatives and strongest objections

| Alternative | Decision and trade-off |
| --- | --- |
| Structured catalog/checklist only | **Retain as baseline and possible final product.** It may be simpler and cheaper than AI; same-source comparison may justify stopping AI entirely. Implementation is not evidence AI is useful. |
| React/Next + separate Python API + PostgreSQL | Defer: adds toolchain, session/CORS and deployment surfaces without a current requirement. Reconsider if user testing establishes app value and richer UI/state needs. |
| FastAPI/Flask/Django monolith | Plausible production-minded alternative, but dependencies/setup are unnecessary for the offline contract proof. Stdlib HTTP is deliberately local/demo only, not a production-security endorsement. Reconsider framework for public deployment rather than extending hand-built security indefinitely. |
| Microservices/event-driven payment platform | Reject for one merchant/one order: distributed failure, deployment and observability cost obscure consent and payment invariants. SQLite durable operation ledger is enough to test crash/unknown paths. |
| Model directly calls payment tools or arbitrary browser checkout | Reject: untrusted source/model text must not acquire financial authority, alter SKU/money or synthesize buyer consent. |
| Multi-agent application runtime | Reject: a multi-role development team does not imply runtime agents improve a two-condition review. One replaceable analysis adapter is enough. |
| SessionClose reuse/rebrand | Reject active-product evidence transfer; existing historical code/tests cannot establish CartReadback works. Preserve archives and write new scoped tests. |

Main cost of stdlib choice: explicit schema/session/CSRF/static-serving/error and threading details must be implemented/tested. Keep the API small, strict and loopback-only. If these safeguards are not actually verified, call the demo unverified instead of treating this ADR as proof.

## A03 — Module responsibilities and dependency direction

1. **Catalog repository** owns six SKUs, price integer minor units, currency, exact source/version/hash and fair same-source baseline. No browser/model price writes. Text is untrusted plain data.
2. **Analysis service** gives only source/typed conditions to a ReadbackAdapter, strictly validates schema and exact spans, retains model/prompt/adapter/validator identity. No payment dependency or credentials. Match/conflict/unknown remain proposals and require semantic review beyond schema checks.
3. **Review service** creates immutable reviews and canonical snapshot hashes, records individually explicit buyer acknowledgements, rejects stale/foreign versions, clears prior consent on new analysis. UNKNOWN acknowledgement never turns UNKNOWN into MATCH.
4. **Order service** revalidates current owned consent/snapshot, derives one-item server-owned money, reserves create/capture operations durably, validates complete normalized provider observations and records ambiguity. Only this layer invokes PaymentAdapter; model cannot construct a payment request.
5. **Payment adapters** offer create/get/capture, not autonomous workflow or retry. Fixture is default and labelled; sandbox requires explicit gate and no live fallback. No auto-capture/recreate/refund. Configured merchant/environment and returned item/money bindings must agree.
6. **HTTP/session boundary** resolves owner from cookie, checks origin/host/CSRF, imposes strict JSON/body limits, rejects unexpected fields and uses revision compare-and-set. Static serving must not traverse outside ui/. Use textContent/escaped text in UI.
7. **UI** shows same-source clear catalog baseline, chosen conditions, original evidence and non-green unknown/conflict states. New edit immediately invalidates local consent; late responses cannot restore an old review. Fixture approval, server verify and final explicit capture are three separate steps. Once an order exists, v1 freezes selection and permits only that order's continuation/reconciliation.
8. **Storage/clock** are injected infrastructure dependencies. Pure validators/canonicalizers/state guards are testable without HTTP or external systems. Preserve durable operation/provider fixtures across restart; logging is redacted.

Allowed direction: HTTP -> application services -> domain/repository/adapter interfaces. Adapters depend on typed domain contracts, not UI. Analysis cannot import order/payment logic. Domain never reads environment secrets or opens network sockets.

## A04 — Consent and payment safety boundary

The hash binds exact immutable facts, suggestions and versions; it is neither authentication nor proof the suggestion is correct. Recheck owned current records at confirm, create and capture. Change of SKU/condition/source/catalog/money/model/prompt/adapter/validator invalidates consent. All typed inputs and ID sets are exact and bounded. Fixed quantity one; money never floats or comes from the model/browser.

Browser approval is not payment completion. Server requery must establish exact sandbox environment, merchant, owned order, CAPTURE intent, expected reference/custom snapshot binding, one SKU/name/quantity, amount/currency and complete status. Missing fields fail closed. A future PayPal adapter must document real endpoint field mapping and sandbox evidence before enabling; a persisted create payload alone does not prove a remote order is unchanged.

Reserve a unique create/capture ledger operation and server UUID before dispatch, atomically with state/revision. External network waits occur outside SQLite transactions. An uncertain attempt remains PAYMENT_UNKNOWN against the same operation/order/key; no new order or automatic POST replay to clear it. Reconciliation is read-only provider GET, and an immediate APPROVED response does not prove a previously dispatched capture cannot still complete. Restarted in-flight work is unknown unless its outcome can be established. Capture authorization linearizes at its reservation; the service cannot recall a remote side effect already dispatched.

Client idempotency keys supplement, not replace, owned snapshot checks, revision concurrency and durable unique operation constraints. `expected_revision` is not part of the semantic idempotency hash; it is a separate mandatory concurrency precondition. Fresh client keys cannot manufacture new logical create/capture operations.

## A05 — Evidence and release gates

Independent review must attempt stale approval, foreign IDs, forged amount/source/model identity, unknown-as-match, injected catalog text, malformed model output, crash/timeout/concurrent duplicate operations, HTTP boundary bypass, reload and late UI responses. Use original contracts before the author's self-score. Author fixes and independent reruns remain distinguishable.

Official PayPal pages inspected (documentation only): [Orders v2](https://developer.paypal.com/api/orders/v2), [API request hosts](https://developer.paypal.com/api/rest/requests/), [idempotency](https://developer.paypal.com/api/rest/reference/idempotency/). A separate reviewer notes minimal/default responses and GET examples may omit verification fields; request full representation where supported, but fail closed if still incomplete. These references are not a successful sandbox integration.

Not run by this ADR: real AI inference, PayPal sandbox E2E, real browser behavior, customer study, public deployment, credentials/account/legal setup, GitHub issues/branches/PRs. Local CR task IDs are planning identifiers only. Do not retry the user-aborted browser authentication or claim the unsupported repository-create connector made a repository.

## A06 — Ownership and change control

CR-001 Theo: contract/domain/ADR; CR-002 Ryan: server/storage/fixture tests; CR-003 Chloe: UI/accessibility/same-source baseline; CR-004 Blair: independent boundary review. Alex records scope and verified evidence; dot decides scope/authority. Contract changes go to both implementation owners and reviewer before dependent changes. Every handoff cites original path + SHA-256 + section IDs, actual changed files/checks, unknown/not-run, strongest objection and next acceptance gate.

Issue-first workflow begins only after an actual repository exists: real issue -> numbered branch -> draft PR -> separate-role review under the actual account. Current local files are pre-repository work, not retroactive issue/PR evidence. No public posting, secret access, paid service, account/legal acceptance, merge, deploy or contest submission is implied by this ADR.
