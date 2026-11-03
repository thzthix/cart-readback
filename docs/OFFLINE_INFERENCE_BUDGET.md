# Offline inference budget prerequisite, issue #23

Current follow-up: [issue #27](ATOMIC_ANALYSIS_BUDGET.md) reuses these operations
inside the application SQLite transaction for explicit offline injection only.
The standalone behavior and original not-wired scope below describe #23; they
are not a claim that the subsequent optional integration is absent. The default
fixture runtime and genuine-inference gates remain unchanged.

Base: `99e77f89cb9c7407ac1438596fdf400e358de26f`. This adds a standalone,
POSIX-only durable budget component and fences requested/returned tier in the
existing offline Responses adapter. It does **not** wire the budget ledger into
`Service`, the CLI, HTTP handlers or the HTTPS transport. The default application
remains synthetic fixture-only; its existing nonfixture attempt/UNKNOWN gate is
still not a spending cap. Genuine inference remains blocked. No credential, real
input count, real price, provider call, payment, account or deployment is used.

## Reservation contract and conservative arithmetic

`OfflineBudgetPolicy` requires explicit model, `default` tier, synthetic price
revision, count implementation revision, nonsecret project/account scope label,
and host-owned dispatch-configuration SHA-256. It also requires positive integer
input/output rates in micro-USD per million tokens, a per-call input/output bound,
and aggregate call/input/output/micro-USD limits. There is no price or counter
default, free-rate fallback, environment lookup or live mode. All shipped example
rates/counts are fabricated tests, not current vendor rates or accurate counting.
A future caller must establish that the dispatch-config hash covers the entire
model/prompt/schema/transport/route/account/project identity. A caller-supplied
hash alone does not establish that fact.

`reserve` takes exact bounded request bytes and an explicitly injected
`OfflineInputCount` binding those same bytes, model and counter revision. It
checks requested model/tier/output limit against policy, and commits a random
operation identity with the complete worst-case capacity before returning.
`claim` requires unchanged exact request bytes, commits one unique dispatch token
and only then returns a `BudgetClaim`. A changed payload or duplicate claim fails.
No dispatch callback, socket, count endpoint or network implementation exists in
this component. Possessing a claim does not authorize a genuine call.

Cost arithmetic uses integers only. It rounds **each** input and output component
upward to a micro-USD, prices all input at the full uncached rate and reserves the
entire requested output limit. It does not assume cache savings, discounts,
prompt-cache behavior, or a cheaper returned tier. Successful known settlement
records actual bounded usage and computed synthetic cost, but never refunds any
reserved call, input, output or money capacity. Repeated zero-output results do
not expand the original allowance. Capacity is intentionally conservative, not a
billing-reconciliation implementation or a promise of zero overcharge.

## Durable ownership, uncertainty and identity

The component owns a **dedicated** private SQLite file, not the application's
existing SQLite file. It acquires an adjacent exclusive POSIX advisory lock before
schema initialization, identity checking or startup recovery. Supported callers
must retain that file/lock pair and use one owner. Each operation is a short
`BEGIN IMMEDIATE` transaction. Methods are serialized within one owner; a second
owner is rejected. The lock file is never unlinked. `close` prevents further use
of that instance. The caller must close it when done.

Policy is persisted once with version/currency and compared byte-for-byte on
reopen. Changing model, pricing/count/config/scope identity or even increasing
limits rejects the old ledger instead of resetting history. Settled reservations
remain in all aggregate sums after close/restart. New sessions, adapters and
objects cannot reset that file's history. Deleting/copying/replacing databases or
using another file is **not** accounting recovery; this trusted local component
cannot prevent a host from doing so.

One RESERVED or DISPATCHED operation blocks admission. Startup conservatively
changes either to UNKNOWN before any new reservation. A call may never have left
the process; it is not guessed free. There is no release, retry, reset, delete,
reconciliation or replacement-operation escape. UNKNOWN blocks all later work.

`settle` requires exact operation/request/policy/claim-token identity. A wrong
claim cannot change another operation. A matching claim with missing/mismatched
model/tier, boolean/negative/excess counts or inconsistent totals commits UNKNOWN
before raising. `mark_unknown` handles a timeout, failure or otherwise missing
outcome. Unknown rows retain their original reservation and store no invented
zero usage/cost. A late/double settlement cannot replace terminal state.
Only bounded identity and count/cost accounting is stored, never request text,
source/proposal payloads, credentials or provider errors. Count implementation,
price data, SQLite contents and host code are trusted inputs, not adversarial
security boundaries.

## Requested and returned tier fence in the existing seam

`InferenceConfig` accepts only explicitly requested `service_tier: default`.
That value participates in immutable metadata/config hashing and is included in
the wire request. A missing or different returned `service_tier` fails with
MODEL_BUDGET_EXCEEDED and permanently blocks that adapter instance. A valid
observation includes both requested and returned tier. The existing service's
`checked_observation` binds both to reserved host metadata and retains them only
in private accounting; its existing durable UNKNOWN policy handles failures.
No `auto`, priority, flex, fast, ultrafast or silent fallback is permitted.

This checks a supplied fabricated envelope, not actual provider availability or
pricing. The [Responses create reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
reviewed 2026-11-03 states that omitted tier uses auto and returned processing
tier can differ from the request. Rejecting a difference is our conservative
policy, not evidence that the provider will always return default.
The [input-count reference](https://developers.openai.com/api/reference/resources/responses/subresources/input_tokens/methods/count)
describes a separate count endpoint; this component neither invokes it nor
assumes its response is a spending authorization or guarantee against drift.

## Verification and remaining gates

Run `python -m unittest discover -s tests -p 'test_inference_budget.py' -v` and
`python -m unittest discover -s tests -p 'test_responses_adapter.py' -v` from
`cart_readback/`, then the complete README aggregate checks on the final tree.
Tests use temporary SQLite files, fabricated count/price/request/envelope data,
concurrency, reopened ledgers and malformed identity/usage. Separate-worker
review must challenge admission, exact identity and UNKNOWN persistence.

Before genuine inference, a separately reviewed application integration must
atomically join budget reservation/claim/settlement with the existing durable
analysis operations and generation fences, so no dispatch can bypass the gate
and crashes cannot split the ledgers into a false known state. It must prove the
exact approved request was counted, fence the complete dispatch/account identity,
obtain current authorized model/tier pricing and bounded data/call/token/spend
approval, provision credentials securely, test real provider schema/usage/TLS and
unknown outcomes, and evaluate fresh semantic quality/buyer benefit. All remain
unmet here. Do not inject a real factory behind an offline label.

Rollback leaves standalone budget files intact and private. Never erase UNKNOWN
history to manufacture a new allowance. Old adapter observations lack the newly
required tier fields and cannot be treated as new valid tier-bound observations.
