# Context-capacity accounting, issue #36

Status: **unselected host primitive; genuine inference remains UNCONNECTED**.
Source base: `2a19773ba965a5da52f4ab393f6d24cb6a1c05e2`, after #35/#37.
Only [one module](../cart_readback/cartreadback_app/context_capacity.py),
[its tests](../cart_readback/tests/test_context_capacity.py) and this note change.
No service, CLI, current adapter, runtime identity, prompt or schema changes.

## Decision and strongest objection

A separate context-capacity strategy does not require an exact input count for
this narrow one-shot text-only profile. It reserves the full documented context
C=1,050,000 as input and M=2048 as output, deliberately over-reserving C+M. It does
not claim C+M fits the model context. A valid observation must have I+O <= C.
This is a conservative architectural inference from documented bounds, not a
vendor invoice guarantee. Count-payload equivalence remains unresolved. Nothing
constructs an `OfflineInputCount` or connects #35's blocked counted plan.

The first proposed separate POSIX-owned ledger was rejected during implementation
planning: it would reintroduce a cross-database atomicity gap with analysis.
`TransactionContextCapacityLedger` instead uses an existing caller-owned SQLite
transaction, with separate `context_capacity_*` tables. A future host can reserve
its analysis operation and this capacity atomically. This issue does not wire that
integration or change the existing synthetic budget's 1,000,000 cap/identity.

## Reference policy, not adopted billing

The immutable evidence revision is `2026-11-03-luna-standard-context-v1`, with
review record SHA256
`ab42b7b87825982e33c564c080270221c029ed21488d4348883f971b3d42e82d`.
The [model reference](https://developers.openai.com/api/docs/models/gpt-6-luna),
[context definition](https://developers.openai.com/api/docs/guides/conversation-state),
[pricing](https://developers.openai.com/api/docs/pricing) and
[output accounting](https://developers.openai.com/api/docs/guides/token-counting)
were checked on 2026-11-03. The model alias is not an immutable vendor snapshot.

Use maximum long-context Standard uncached rates for both reservations and
observations: input 200,000 and output 750,000 micro-USD per million. Each component
is rounded upward independently with integer arithmetic:

- Global reference: 210,000 + 1,536 = **211,536 micro-USD** per operation.
- Reference with 10% regional uplift: 231,000 + 1,690 = **232,690 micro-USD**.

Neither reference profile selects or proves actual account/project pricing.
The literal billing scope remains `unselected`, with explicit missing gates in
identity metadata. Unsupported/custom pricing is not accepted. Host provenance,
data-category and runtime SHA references identify nonsecret reviewed records;
they do not verify external accounts, credential binding, applicable rates or
permission to transmit/spend. Never pass credentials or their hashes as references.
No browser/API deserializer or `verified`/live-enable flag exists.

Policy and host authorization validity windows are at most one day, with exact
bounded call/input/output/micro-USD limits. The ledger persists the whole identity;
changing a rate profile, evidence revision, expiry, scope reference, runtime or
allowance cannot replace it. Renewed authorization/migration needs a separate
reviewed design. Deleting/copying a DB is not renewal or recovery.

## Request and accounting boundary

Reservation validates exact shipped instructions, user-template framing and
structured schema. It verifies the full source-object hash (including source ID), text hash/revision,
typed conditions and the
owner/generation/runtime fence. Request bytes are hashed without rewriting.
Settings stay Standard (`default`), reasoning `none`, one text user message,
empty tools, explicit cache mode with no breakpoints, store/background/stream
false and output 2048. History, images, files, compaction, added fields, cache
breakpoints and altered settings fail closed. Byte bounds are resource limits,
not token counts. There is no network/retry/credential interface.

`parse_accounting` validates the bounded outer response independently from
proposal text, semantic acceptance or refusal. The response status must be one
of the documented exact enum values. Only terminal completed/failed/cancelled/
incomplete states are eligible for KNOWN accounting. Valid usage in queued or
in_progress responses is retained with UNKNOWN, not treated as final usage.
Missing/unsupported/malformed states remain UNKNOWN. Pending usage is explicitly
labelled `provisional-model-usage`; recognized terminal usage is labelled
`terminal-model-usage`. Neither is a vendor charge. See the
[response-state reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
and [terminal-state definition](https://developers.openai.com/api/docs/guides/background#polling-background-responses).
This status check establishes accounting finality under the contract, never
semantic success or cancellation of an earlier uncertain operation. It requires
exact model/tier and strict nonnegative integer input/output/total, I <= C,
O <= M, total=I+O <= C. Counts include invisible output rather than visible-text
length. Input `cached_tokens` and output `reasoning_tokens` must be zero integers.
Optional cache-write count and documented TTL detail categories must also be
compatible zero integers; missing required/unknown categories fail closed. See
[cache rules](https://developers.openai.com/api/docs/guides/prompt-caching).
Explicit provider-level contradictions also force UNKNOWN while retaining valid
base-model accounting as an estimate only: nonempty/malformed `tool_usage`, a
`background` value other than exact false, nonempty/malformed echoed `tools`, or
a malformed supplied output wrapper or item type other than message/reasoning.
Absent output, an empty output array or a message with invalid/missing proposal
text can still have independently valid accounting. An omitted or empty
object `tool_usage` is accepted; null is not assumed to mean zero. Even zero-valued
tool categories are unsupported. The optional tool-usage object and background
boolean are documented in the response reference above. No tool rates are added.
Invalid/missing proposal text still does not prevent independent accounting.
This detects these explicit contradictions, not every hidden billable category
or vendor violation. `no-explicit-profile-conflict` is an observation label, not
external account, billing or service verification.

This parser profile is offline-tested, not evidence of an accepted real envelope.

Observation takes the exact claim plus host-recorded request/runtime identity,
provider request ID and current host fence. Model output cannot supply those
bindings. The future reviewed transport must establish them; self-asserted
arguments are not cryptographic provider proof. IDs are bounded and stored only
as hashes. Reused provider request/response IDs fail closed. Raw request/proposal
text, headers and credentials are never persisted in these tables.

## Transactions and recovery contract

The caller must own the process/storage lock and use short write transactions
(such as `BEGIN IMMEDIATE`), holding current application state under that same
lock. Initialization requires an active transaction. The primitive never commits,
rolls back, manages a connection, performs I/O outside SQLite/assets, or invokes
external callbacks. The owner must:

1. Initialize the identity and run `recover_context_capacity` during exclusive
   startup, then commit before accepting work. RESERVED/CLAIMED becomes UNKNOWN.
2. Reserve full C, M and R together with the analysis operation, then commit.
3. Claim once against exact reserved bytes/fence/current time, then commit before
   any separately authorized external work. Claims expire after at most 20 seconds
   and no later than authorization expiry. Duplicate claims cannot dispatch again.
4. Record accounting and application outcome together in a new short transaction.
   Never accept a semantic proposal based on accounting alone.

Stale/expired/tampered pre-send claims return `None` after setting UNKNOWN. Matching
invalid accounting returns `UNKNOWN` rather than throwing after the update.
**Commit these outcomes.** Raising an outer exception and rolling back would undo
the fault record. Wrong claim/exchange identity rejects without changing another
operation. SQLite errors must not be turned into success; uncertain commit state
requires recovery, not dispatch/replay. Persisted last-seen time fences backwards
host clocks; the clock itself remains a trusted host dependency.

KNOWN may permit another independently admitted operation, but every reservation
is permanently consumed, including zero observed usage, rejection, pre-send error
and failure. UNKNOWN blocks admission forever in this version. Late, stale or
recovered valid accounting can be recorded once, but UNKNOWN remains terminal;
it cannot make a proposal current, retry a call, refund or renew capacity. The
single stored observation may remain provisional; this is not final reconciliation,
and a later terminal response cannot replace that append or clear UNKNOWN. A
missing observation requires `mark_unknown` or owner-startup recovery. Unique
fence, pending-operation and provider-ID constraints supplement transaction/CAS
checks. Transaction rollback before a committed reservation means no admitted
operation, and must imply no external attempt.

## Evidence limits and remaining gates

Tests use fabricated envelopes and local SQLite, including real subprocess exit
at reservation/claim commit boundaries, cross-connection races, owner rollback,
strict bounds, cache details, stale/late/duplicate observations, expiry and no
refunds. Aggregate exact-tree results belong to the review/PR receipt, not to an
old test count in this document. Genuine calls, hosted CI, native UI and semantic
model evaluation are not performed by these tests.

This is substantive local accounting, not complete genuine-service admission.
A later reviewed integration must bind real billing/credential scope and bounded
live approval, preserve and reconcile all existing UNKNOWN history, atomically
couple application transitions, supply trusted time/current state, and select a
reviewed transport. It cannot treat a new namespace as fresh spending authority.
The current service/default modes and old synthetic tables remain untouched.

No account-wide or exact invoice cap is promised. Taxes, contract/rate changes,
other apps and provider violations/delayed spend-limit enforcement are outside
this ledger. Real prices and access must be freshly verified before adoption;
secure provisioning and real controlled observations remain separate gates.
