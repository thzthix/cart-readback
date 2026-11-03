# Offline count preflight and exact CAS, issue #29

Base: `0f458bf08a29ceee2263df6f4304f5446762c125`. This moves explicitly injected
count work outside application SQLite transactions and fences its result before
the existing atomic budget/analysis reservation. It is a **contract and offline
lifecycle implementation**, not a Responses token-count HTTP client, accurate
real counter, current price, credential flow or enabled service. Default server
and CLI behavior remain synthetic fixture-only; nonfixture mode is still denied
without explicit offline budget/count injection.

## Why this change is bounded

A real count operation may wait on I/O. Running it inside the reservation write
transaction would block unrelated owners and bootstrap. Moving it to an
untracked callback before reservation would instead permit stale count reuse,
unlimited repeated count requests and ambiguous retries. This change adds one
small durable preflight journal, a single claim, bounded attempts and a final
compare-and-swap. It does not add a second database or a new public endpoint.

The counter still accepts the exact immutable generation request bytes and
returns a strictly typed `OfflineInputCount` binding those bytes, model and count
implementation revision. No provider-supplied digest is trusted or required.
The host owns the request/config/policy identity. The separate future provider
client must establish the correct API count-parameter projection, authenticated
account/project, deadlines, response parsing and complete input semantics. This
slice neither sends the full generation payload to a real count endpoint nor
claims the provider accepts it unchanged.

## Durable phases

1. A short transaction validates owner/revision, typed conditions and server
   product facts; checks existing generation admission, immutable policy and
   legacy history; and rejects already-known impossible remaining capacity.
   It freezes owner, session revision, current checkout hash, request-body hash,
   full catalog/source/conditions, host model/settings, exact policy document and
   request SHA-256. It commits an unconfirmable count-intent review and clears
   older consent, together with one PREPARED preflight row, before counter work.
   No successful snapshot or generation budget reservation is invented.
2. A second short transaction compares that frozen identity to current state,
   requires PREPARED, and commits one random count claim token with COUNTING.
   A duplicate claim cannot invoke the counter. A change found before claim
   records STALE and retains the slot without invoking count or generation.
3. One injected counter runs outside all application transactions. The caller's
   watchdog has an explicit finite positive deadline, default five seconds and
   maximum twenty, rejecting booleans/unbounded settings before callback start.
   Counter exceptions are sanitized. This is not a cancellation proof: a timed
   out daemon worker may continue, but it has no database/result-attachment
   callback and cannot publish its late result.
4. A final transaction checks row/token/frozen identity, validates count binding
   and compares owner/revision/checkout/body/catalog/config/policy/request again.
   A current valid count atomically reserves budget+analysis and records USED
   with the resulting analysis operation ID. The generation input document
   contains the preflight ID/hash. Existing generation claim, exact-byte adapter
   fence, result accounting and consent rules then run unchanged.
5. Valid stale counts record STALE with their private count receipt, with no
   generation reservation or change to a newer review/order/confirmation. A
   known count followed by a business-rule quota rejection records BLOCKED.
   A savepoint rolls back any partial generation reservation while retaining
   that known receipt. Invalid/missing/failed/timed-out counts record UNKNOWN,
   with no invented zero usage. A failed final SQL write rolls the entire final
   transaction back; the durable COUNTING row and unconfirmable intent survive
   conservatively. Failed/stale/unknown count blocks that same intent only when
   it remains current, never overwriting a newer review or checkout.
6. Under the service's existing exclusive DB lease, startup converts surviving
   PREPARED/COUNTING to UNKNOWN in the same recovery transaction as budget and
   analysis recovery and blocks the matching current count intent. Startup,
   bootstrap, replacing adapters and new sessions
   never replay a count. No clear/reset/retry/reconciliation API is provided.

All count work, including a callback that immediately fails, requires a committed
claim. No callback runs for a stale initial revision, unavailable budget, unknown
history, exhausted count allowance or known impossible generation capacity.
Counts returned after a timeout are ignored; there is no automatic retry or
fallback estimate.

## Availability, CAS and retained capacity

The preflight immediately invalidates prior consent and exposes an
ANALYSIS_BLOCKED/MODEL_PENDING count intent while counting. An older tab cannot
confirm or create an order from its old snapshot. Concurrent bootstrap and
unrelated writes can still proceed. A newer review, confirmation, order,
price/source revision, trusted adapter/budget replacement, timeout setting or
request byte change defeats the final comparison. Even an identical-looking
replacement budget/counter object cannot finish an older in-memory preflight.
The request body is copied before count work, so a caller's mutable dictionary
cannot rewrite the frozen selection while the callback waits.

Count attempts are database-wide and independent of generation reservations.
Every durable row, including STALE/BLOCKED/UNKNOWN and definitely unclaimed
PREPARED history, consumes a slot permanently. The cap is the smaller of the
existing analysis-attempt bound and immutable budget max-calls. One PREPARED or
COUNTING operation blocks overlap; any UNKNOWN count blocks later nonfixture
count/generation attempts across restart. There is no refund for a cheap or zero
result, stale attempt, local error or a new session.

Before count, the service rejects known exhausted calls/output capacity,
unresolved budget rows, insufficient remaining input for even one token, or
insufficient synthetic cost for one input token plus the full output reserve.
This is only a cheap lower-bound rejection to avoid clearly wasted counts. Final
exact-count admission remains authoritative. It does not guess the actual count
or reject every future over-budget request without counting.

Count receipt and generation reservation share the final transaction. A
preflight can be USED only once, and cannot be reused for a different owner,
request/config/policy or revision. All existing full generation capacity remains
reserved after known lower usage, error, stale result or restart. Source/proposal
text, provider errors, credentials and raw responses are not stored in count
receipts; the private input document holds the owned frozen synthetic catalog and
nonsecret policy just as analysis does. None is public bootstrap data.

## Economic decision and limits

**Proceed with this offline refactor, not with live counting.** It removes a
known lock-availability hazard and bounds future extra count attempts. It does
not establish that a second provider request is economically beneficial for a
small two-condition keyboard check. An extra count round trip can add latency,
requests and operational failure modes. No real latency, count accuracy, API fee
or buyer-effort comparison has been measured here.

The [official token-counting guide](https://developers.openai.com/api/docs/guides/token-counting),
reviewed 2026-11-03, describes input counting including request-structure tokens
that ordinary local text tokenization can omit. The
[count API reference](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)
describes a separate count endpoint. These references do not certify our frozen
model/schema/parameter combination or this application's pricing/authorization.
No claim that counting is free is made. Count slots are a request-count bound,
**not dollar accounting for any future count endpoint fee**. Before live use,
count/data transmission and possible fees need explicit bounded authorization
and verified current billing, as do generation calls.

A verified conservative local tokenizer/upper bound, or precomputed counts keyed
to a truly immutable complete request/model/config, may avoid an extra network
round trip. Neither is implemented or assumed accurate. The same-source
structured table remains the non-AI baseline; count preflight does not establish
semantic correctness or buyer value. There is no hidden retry, live fallback,
remote receipt cache or cross-request reuse introduced here.

## Verification and remaining gates

`test_count_preflight.py` covers a waiting counter with real unrelated SQLite
writes/bootstrap; exact receipt linkage; source/config/counter/session revision
CAS; immediate old-consent invalidation and newer review/order preservation;
duplicate claims/results;
watchdog+late results; retained global stale-count slots; known impossible
capacity; counted quota rejection/savepoint rollback; final SQL write failure;
invalid settings before callback; and actual subprocess crashes at count reserve,
count claim, pre-observation and generation-reservation boundaries. Existing
analysis/budget/fixture suites remain required, plus all README aggregate checks
and separate-worker fixed-source review.

Real count HTTP schema and semantics, provider/model/account/project/transport
identity, verified current count/generation prices, secure credentials,
bounded data/call/token/spend authorization, actual TLS/deadline/usage/failure
behavior, fresh semantic evaluation and buyer baseline/value remain unverified.
Arbitrary trusted Python is not sandboxed; local host code or DB replacement can
bypass an offline component and is not an authorized recovery method. No genuine
network, credential access, money movement, deployment or contest submission
occurs here. Preserve count, analysis and budget history on rollback; do not run
old code to hide unknown outcomes or manufacture a new allowance.
