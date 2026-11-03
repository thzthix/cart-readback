# Offline payment dispatch boundary

This prerequisite separates payment calls from application SQLite transactions.
It does **not** enable PayPal or genuine model inference. The old provider was an
intentional shared-transaction fixture, not an observed live-payment exposure.
API v1, buyer intent, revision/error envelopes and frontend bytes are unchanged.
C09's conceptual create/get/capture actions map internally to pure `prepare`
plus one-shot `dispatch` for create/capture, and read-only `get` for lookup.

## One operation, one dispatch right

1. In a short transaction, validate current owned review and persisted immutable
   consent. Allocate the local order and server operation UUID. Persist the exact
   adapter-prepared canonical request body, SHA-256, method/path, expected-facts
   hash, provider/merchant/adapter binding, revision and timestamp. The pure
   `prepare` seam cannot perform I/O. The operation becomes `RESERVED`.
2. Commit the reservation. A compare-and-set claim changes only that operation
   from `RESERVED` to `DISPATCHED`, with a random dispatch token and timestamp.
   Compare the original reservation identity, not a newly rehashed replacement.
   Claiming is not a lease and never grants another attempt after timeout.
3. Call the captured adapter with the exact persisted request, outside every
   application SQLite transaction. `operation_id` is the distinct provider UUID;
   the browser's idempotency key never becomes that identity. No automatic
   monetary retry is implemented.
4. Open another short transaction. Fence the observation by owned local order,
   active operation/kind, dispatch token, request bytes/hash, expected facts and
   provider configuration. Store bounded normalized facts and a safe error class,
   never a raw exception/provider body. A matching late completion can resolve
   the same unknown operation. A late failure cannot downgrade completed success.

The fixture's create body is its complete normalized authoritative expectation;
its capture body is exactly `{}`. These are actual **fixture** request bytes, not
a claimed PayPal wire mapping. A future adapter must prepare its own exact body
and separately pass provider normalization, host, timeout and authorization gates.
Its immutable configuration/version binding must cover all dispatch-relevant
configuration. No provider URL or body comes from the browser.

## Capture freshness and reconciliation

Capture first reads the owned authorization, then GETs the same provider order
without a DB transaction. Before reserving, it repeats owner/revision, current
catalog/source/model, persisted consent, expected-payload and adapter binding
checks. A source/configuration/consent change during that GET sends no capture.
Authorization linearizes at reservation. No cross-system atomic lock is claimed:
a source or remote order can change afterward; v1 assumes one app/provider writer
and does not PATCH orders.

Reconciliation is GET-only for the same known order and active operation. It
cannot claim dispatch, replay a POST or replace a checkout. An approved/pending
lookup cannot disprove a possible capture. An unavailable/incomplete/mismatched
lookup keeps uncertainty. Known create IDs survive an incomplete representation
and can be checked again. Create response loss before the ID is persisted stays
`CREATE_OUTCOME_UNKNOWN`; no request-ID search or invented provider ID is used.
Delayed old CREATE reconciliation cannot overwrite a newer CAPTURE operation
or regress a successful create/approval/verification with an older lookup.
A no-ID reconcile plan rechecks current success and provider-ID presence before
recording unknown, so stale absence cannot overwrite a newly known order.

## Process and database lifecycle

One cooperating service owns each canonical database path. An OS advisory lock
rejects a second instance **before recovery** can mistake live work for a crash.
There is no lock timeout, automatic takeover or redispatch. Process death releases
the OS lock; restart changes stranded `RESERVED`, `DISPATCHED` and legacy `PENDING`
work to `UNKNOWN`. Even a reservation never sent is conservatively stranded.
Call `Service.close()` when discarding an embedded service; it refuses while a
request is active. Closing a server process releases its OS resources normally.

Keep the app DB, its adjacent `<app filename>.fixture.sqlite3` fake-provider DB
and `<app filename>.service-lock` path private. Never unlink a live lock file.
The provider database commits independently, so application rollback cannot undo
a synthetic provider side effect. Legacy shared fixture rows are copied by
provider ID without overwriting already-migrated provider observations. Old
operations gain additive columns and cannot acquire a fresh dispatch right.
Do not downgrade a running/unresolved database to an older application version.
A rollback requires stopping all service work and restoring a coherent private
backup, not deleting payment history to start again.

The Linux lock path is exercised in these checks. The Windows standard-library
locking branch is implemented but has not run here. This is a same-host/local-
filesystem, cooperating-process guard, not multi-host support, protection from
manual DB/lock-file tampering, hard-linked alternate DB paths or a production
security guarantee. Analysis still calls its fixture adapter inside its own
transaction; real inference needs a separate reviewed I/O/freshness change.

## Reproducible offline evidence

From `cart_readback/`, `python -m unittest discover -s tests -v` includes
`tests/test_dispatch.py`. Existing domain/HTTP/independent regressions remain.
Internal fixture connection/restart helpers were adapted to the separate provider
store and explicit service ownership; their behavioral assertions remain.

The crash test uses **real subprocess `os._exit`**, two independently committed
SQLite databases and append-only fake dispatch-attempt receipts. A regression
proves repeated calls with the same UUID count as two attempts, even when the
fake provider deduplicates the resulting order. For create and capture it
interrupts before reservation commit, after reservation commit, after claim
commit/before transport, after fake request acceptance/before effect, after
provider effect/before response, after response/before observation, after result
write/before commit, and after success commit/before browser response. It verifies
unknown/no-replay or original stored success, including same-order capture
recovery. Fake request acceptance is an offline transport simulation, not a real
partial TCP-send or HTTP-provider experiment.

Other probes cover exact request bytes/UUID identity, sole claim, unlocked
create/get/approve/capture calls, bootstrap and safe writes during barriers,
11 freshness mutations, operation/token/hash/route/owner fences, delayed create
reconcile, reconcile while capture waits, terminal-success monotonicity,
legacy migration and same-/cross-process instance exclusion. Native browser,
genuine PayPal/OAuth/settlement/retention, real inference and customer value remain
unverified. Passing offline tests do not authorize those stages.
