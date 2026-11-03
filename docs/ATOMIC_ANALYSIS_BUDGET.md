# Atomic offline analysis budget gate, issue #27

Base: `742d5718df6632313f4499ead381e3ab2a2d4850`. This connects the reviewed
budget operations to the existing analysis lifecycle **only through explicit
trusted offline injection**. The default server and CLI remain synthetic
fixture-only. There is no real counter, current verified price, credential
lookup, network factory, live switch, API call, spending or deployment here.
Known cost fields are calculations with fabricated rates, not observed charges.

## Default off and host-owned identity

`Service(..., analysis_budget=None)` is the default. It denies nonfixture analysis
before creating a reservation or calling the adapter. Tests may explicitly
inject `OfflineAnalysisBudget(policy, count)` with the exact supported
`OfflineResponsesAdapter`. A metadata flag alone cannot relabel a Responses or
unknown adapter as fixture. Existing `FixtureInferenceAdapter` test doubles,
including trusted fixture subclasses, keep their synthetic lifecycle and never
invoke the budget counter. Arbitrary injected Python code is not sandboxed;
this host-owned seam is not a security or spending-authorization boundary.

The policy must match the adapter's host configuration SHA-256, model, explicitly
requested default tier, output limit and offline execution mode. The immutable
policy also carries price/count revisions, scope identity and all bounded
call/input/output/micro-USD limits. Its SHA-256 participates in the review's model
metadata and freshness checks. Changing or removing that policy makes an old
review stale and prevents old confirmation; a different persisted policy cannot
reset the allowance. There is no HTTP/browser/environment parameter for these
settings, and no default rate or count is guessed.

The model config version is advanced for the exact-request accounting fence.
Model/source/conditions/schema/prompt/settings still participate in the existing
identity. Current adapter metadata does not establish a concrete network
factory, actual account/project or transport identity. Those remain mandatory
separate live-integration gates, not something a supplied hash proves.

## One database, one owner and one transaction per phase

The service uses the application's existing SQLite file and process lease.
`TransactionBudgetLedger` shares the caller's already-open transaction, without
committing, rolling back, acquiring another lease or independently recovering.
The standalone `OfflineBudgetLedger` retains its own private-file/lock behavior
through the same operation implementations. The service does **not** coordinate
two independently committed database files.

1. **Reserve.** The existing short analysis transaction freezes product, source,
   typed conditions, host metadata, exact policy document and request SHA-256.
   It locally builds the complete wire request, obtains a fabricated bound count,
   and reserves worst-case capacity under exactly the same operation ID used by
   `analysis_operations`. Budget, pending checkout, review and session revision
   commit together. A later SQL failure rolls all of them back before any call.
2. **Claim.** A second transaction applies the existing owner/generation/revision/
   source/config fences, rebuilds the request and compares exact bytes by SHA-256.
   It claims the budget once and stores that same claim token in the analysis
   dispatch row. Both DISPATCHED states commit together before adapter work.
   No queue, retry, replacement operation or monetary capability is added.
3. **Dispatch.** Adapter work remains outside every application SQLite
   transaction. The adapter checks its newly built exact request against the
   reserved hash **before invoking transport** and records the hash of bytes
   actually passed to that seam. A changed payload cannot be sent merely because
   its source fields look equivalent.
4. **Observe.** Existing typed observation checks now also bind the actual request
   hash. One transaction settles reserved usage, persists private accounting and
   attaches a current validated result, or blocks the checkout. Model/default-tier
   and usage must fit the original reservation. A matching malformed/excess
   observation commits budget UNKNOWN and analysis UNKNOWN with no snapshot,
   rather than rolling back the unknown transition when reporting an error.
5. **Recover.** Under the existing service lease, startup changes pending budget
   and analysis rows to UNKNOWN in the same transaction. It never replays a POST,
   erases history or assumes a reservation was free. Recovery also runs when no
   budget is injected and the service has returned to its default fixture mode.

A stale result can still supply valid accounting: it settles against the exact
**reserved** policy, even if the service's current policy/adapter has changed,
but cannot attach a proposal or create consent. A stale reservation detected
before dispatch retains its capacity as UNKNOWN and blocks later nonfixture
admission. Late or duplicate observations cannot alter terminal ledger state.

## Counting, prices and accounting are deliberately synthetic

The count callback receives exact bounded request bytes and must return an
`OfflineInputCount` bound to the same bytes/model/counter revision. Missing,
boolean, over-limit or mismatched counts fail before reservation. The callback
runs **inside the local reservation transaction** and must be pure, bounded local
test code: no I/O, secrets, credentials or provider count/API request. A future
real count operation must be separately authorized and moved outside the
transaction with an appropriate immutable preflight/freshness design. Supplying
a fabricated count does not establish real token accuracy.

Integer arithmetic rounds each positive input/output component upward to a
micro-USD, assumes full uncached input pricing and reserves the entire output
limit. All reserved calls, tokens and synthetic cost remain in aggregate sums
after known lower actual usage, failure, stale state or restart. There is no
refund/reset/release/renewal path. All owner sessions share this allowance.
The actual returned usage exceeding a reservation is UNKNOWN, not proof that a
real provider could not already have charged more. This is not a vendor-enforced
billing cap, verified pricing or permission for paid inference.

Price/count revisions and scope labels are explicitly supplied **fabricated test
identity**. Recorded cost is labelled synthetic and not a real charge. Credentials,
request/source/proposal text and provider exception bodies do not enter budget
rows. The existing private analysis input document still holds its frozen source
and nonsecret policy; neither that document nor the budget ledger is public
bootstrap data. Bootstrap model metadata includes only the policy hash.

## Migration and conservative limits

Existing fixture sessions/databases retain their behavior. New budget tables are
created alongside the existing schema without deleting or backfilling history.
If any older nonfixture analysis lacks a matching budget operation, new budget
adoption is denied. A known historical token observation is not a priced past
reservation and must not be guessed free. An old standalone budget file is not
silently imported into or discarded by this service. Any future migration needs
its own reviewed accounting/authorization decision.

The new shared seam does not add cross-process access: the service's existing
one-owner DB lease remains required. It cannot protect against malicious trusted
host code, direct SQL tampering, deletion/copy/replacement of databases or a real
factory hidden behind an offline label. Never use those actions to bypass
UNKNOWN or manufacture fresh budget capacity.

## Verification and remaining gates

Focused tests are `test_analysis_budget.py`, `test_analysis_dispatch.py`,
`test_inference_budget.py` and `test_responses_adapter.py`. Integration tests
cover default-off admission and forged fixture labels; atomic reservation,
claim and observation rollback; exact request drift before and after claim;
over-reserved usage; global retained call/token/synthetic-spend limits; stale
accounting/policy consent; legacy-history rejection; and caller-owned rollback.
Actual subprocess crash tests verify both ledgers after reservation commit,
dispatch commit and pre-observation interruption, with no transport replay.
Run all README aggregate checks and independent review on the final fixed tree.

Real count/price/account/transport identity, bounded data/call/token/spend
approval, secure credential provisioning, provider request/schema/TLS/usage and
failure/restart behavior, fresh semantic quality and buyer benefit remain
unverified. No genuine provider, PayPal, spending, deployment or contest action
is enabled or performed. The strongest remaining objection is the trusted
fabricated count/rate seam, not the presence of a SQLite ledger.

Rollback must preserve private budget and analysis history. Old code must not be
used to bypass these new admission/UNKNOWN rules. No automatic downgrade or
old-ledger deletion workflow is provided.
