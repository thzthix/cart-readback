# Offline PayPal Orders wire boundary

This is issue #16's **offline-only prerequisite**. Initial wire preparation used
main `d54f6353`; final integration uses `4640d083359c19ae60f6e472078470fc9ab5c36e`
after issue #15's analysis lifecycle merge. This slice does not change those
merged service/storage/analysis files.
`cartreadback_app/paypal_sandbox.py` has an injected fake transport contract and
no network implementation, credential fields, OAuth flow, environment lookup,
runtime switch, SDK or live fallback. The default server still uses its existing
fixture provider. Genuine PayPal sandbox and payments remain **UNCONNECTED**.
Neither offline test success nor this module authorizes connecting an account,
accepting agreements, using credentials, running a payment or deploying anything.

## Mapping and dispatch

The adapter implements the existing pure `prepare`, one-shot `dispatch` and
read-only `get` seam. It does not allocate an alternative operation identity,
retry a POST, search by request ID, recreate an unknown order or patch remote
orders. Existing Service reservation, single claim, out-of-transaction I/O,
observation fence and UNKNOWN recovery remain authoritative and unchanged.
The transport receives the exact persisted canonical body. Each POST carries the
Service-generated UUIDv4 as `PayPal-Request-Id`, plus a representation preference.
GET has no monetary request ID. No authorization value is accepted or produced.

Only one USD purchase unit, one item and quantity one are supported. Integer
server cents become fixed two-decimal strings with no float or rounding step.
The request includes the immutable local order reference, snapshot hash, payee,
item, amount and matching item-total breakdown. Capture is exactly `{}`. Input
and wire round-trip validation rejects unsupported fields, money/types, altered
payee, paths, duplicate JSON keys and extra create instructions. API routing is
fixed to the sandbox host and exact Orders create/get/capture paths; arbitrary
HATEOAS API links are never followed. This is a mapping choice for this narrow
product, not full PayPal schema support or tested provider acceptance.

Adapter settings are frozen. The version fence includes merchant, timeout,
fixed endpoint and parser bounds. The only shipped transport implementations are
in-memory test doubles. Injected Python code is trusted test code, not a sandbox
or a mechanism that prevents an arbitrary injected implementation from doing I/O.
Adding a network transport would be a separately reviewed, unauthorized stage.

## Returned facts and uncertainty

Normalization takes only provider JSON. It never receives an expected request,
never copies missing merchant/item/reference/snapshot facts from a local order,
and never treats a request field as provider evidence. A malformed successful
representation retains only its independently validated order identity, never
its unverified status or other facts. Invalid JSON, duplicate keys and HTTP errors
cannot supply such identity evidence. A sparse response returns
only its validated facts, including a known valid provider ID, so the existing
Service can retain that ID while keeping PAYMENT_UNKNOWN. An ID lost before any
usable response stays unknown; no replacement ID is manufactured.

All immutable expected facts must compare exactly before create, approval or
capture authorization can advance. PayPal's documented GET example omits optional
payee, item and custom-ID data. Such an observation intentionally fails closed
here. A successful response preference is not proof those facts were returned.
No compatibility claim is made until genuine authorized lifecycle testing shows
what representations this merchant/API combination actually returns.

The narrow shared verifier adjustment permits an absent capture collection only
for offline sandbox observations outside capture verification. This avoids
inventing `captures: []` before capture. Fixture shape validation is unchanged.
A nonempty returned capture collection blocks pre-capture verification, even if
the enclosing order says APPROVED; it cannot authorize another capture.
Capture success still requires a returned, single, final COMPLETED capture with
matching integer amount and USD. Pending, malformed, incomplete, mismatched and
unavailable outcomes stay unknown. Transport, deadline and worker-start failures
are sanitized. Bodies are capped at 64 KiB and JSON depth 16; raw bodies,
exception strings, payer details and arbitrary URLs are not persisted.

There is one exchange at a time per adapter. A timeout or worker-start failure
permanently blocks that instance because worker startup or completion may be
uncertain. A thread resource/start error becomes a sanitized unknown observation,
not a raw exception or a new dispatch right. No late result
is reused or causes another dispatch. Local deadlines do not prove real TCP
cancellation, bounded network allocation, OAuth/HTTP behavior or settlement.

## Approval and return preparation remain offline

`sandbox_approval_url` checks one exact HTTPS sandbox checkout URL whose sole
`token` equals the returned provider order ID. Live hosts, host suffixes,
userinfo, ports, fragments, escapes, duplicate parameters and multiple approval
links are rejected. By default public `approval_url` remains null. An explicitly
injected `buyer_return_origin` enables inert callback preparation and exposes the
validated fabricated URL as nonnavigable text. The CLI never selects this adapter.
No external browser visit or genuine buyer approval has occurred.

The new [buyer-return contract](OFFLINE_BUYER_RETURN.md) preserves Strict cookies,
exact CSRF/Origin checks and fresh final capture intent. The GET landing renders
static UI without session creation or business mutation; only an explicit
same-origin POST can consume a bound return state and requery the same order.
This preparation does not establish provider acceptance of loopback URLs, return
parameters, actual buyer behavior or a genuine end-to-end PayPal lifecycle.

## Primary references and unverified gates

Reviewed 2026-11-03 UTC:

- [Orders create](https://developer.paypal.com/api/orders/v2/orders-create)
- [Orders get](https://developer.paypal.com/api/orders/v2/orders-get)
- [Orders capture](https://developer.paypal.com/api/orders/v2/orders-capture)
- [PayPal idempotency](https://developer.paypal.com/api/rest/reference/idempotency/)
- [Published Orders schema](https://developer.paypal.com/api/orders/v2/schema.json)

These references informed endpoint/field mapping, response preference, UUID
header use and conservative normalization. They do not verify this payload with
PayPal. The app deliberately retains its stronger no-POST-retry rule regardless
of the provider's time-limited idempotency support. Current docs and sandbox
behavior must be rechecked before a separately authorized real integration.
OAuth/access handling, TLS/redirect enforcement, actual request/response schemas,
merchant identity, approval/return, retention, network/crash ambiguity, settlement,
refunds, genuine model integration and production security remain unverified.

Run `python -m unittest discover -s tests -p 'test_paypal_sandbox.py' -v` from
`cart_readback/`. Fabricated tests cover mapping, malformed/sparse observations,
host/token restrictions, one-attempt failures/timeouts, durable create/capture
identity, SQLite transaction isolation, unknown ID retention, pending capture and
same-order GET recovery. The complete final-candidate check receipt is recorded
separately; earlier component checks do not certify a changed integrated tree.
