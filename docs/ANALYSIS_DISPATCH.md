# Offline analysis lifecycle — issue #15

Base: `d54f6353fcde39278894b053b58d15eb3d366f28`. This change joins the existing
offline-injected Responses boundary to the service lifecycle for local testing.
The server and CLI still select only the synthetic fixture. No network transport,
credentials, live-enable switch, API call, provider acceptance or paid use exists.

## Reservation, single claim and observation

1. A short SQLite transaction validates the owner/revision, catalog and typed
   conditions. It freezes the complete catalog, conditions and host model metadata
   into a durable `analysis_operations` row with its own UUID and input hash. It
   binds the complete pending checkout hash and reserved session revision. Older
   consent is replaced by a new review generation with no confirmation/snapshot.
2. The pending checkout is represented using existing API state `ANALYSIS_BLOCKED`
   and `analysis_error: MODEL_PENDING`. Results are empty and the snapshot is null.
   No new UI state or successful all-unknown result is fabricated. The synchronous
   POST waits, but concurrent bootstrap and unrelated writes remain available.
3. A second short transaction compares the original reservation to the durable
   row, exact pending checkout, owner/review/revision, current catalog, adapter
   object and metadata. One claim changes RESERVED to DISPATCHED and stores a
   fresh dispatch token before invoking the adapter outside every application
   SQLite transaction. Another claim cannot dispatch the same operation.
4. A short observation transaction checks the same identities and dispatch token.
   A current valid proposal becomes REVIEW_REQUIRED with a new snapshot. Source,
   catalog/price, model/settings, generation or revision changes prevent attachment.
   A late result cannot overwrite a newer review or its confirmation. Stale
   analysis stays blocked with no snapshot, even when bootstrap marks it stale.

The exact observation time is not an atomic provider/config lock: source or model
configuration may change immediately after claim while external work is running.
The final fence rejects that work. Trusted adapter/config mutation is not an HTTP
capability. Adapter arguments are owned copies; in-place adapter mutation cannot
rewrite the reserved source/conditions or public checkout.

The result array is separately schema/span validated after the adapter returns.
For nonfixture injection the service requires the exact `InferenceObservation`
type, binding config/source/revision/conditions and requested/returned models, IDs
and integer usage. Only whitelisted identity/usage fields are persisted in the
accounting observation. Proposal payloads are never stored there, including when
JSON/schema/span validation fails. Valid accounting survives invalid proposals.
The ledger is not public bootstrap data. Provider exception text, headers and raw bodies are never
stored by this lifecycle. Schema and exact quotation still do not prove truth.

## Bounded offline use and unknown outcomes

The default `AnalysisPolicy` admits at most eight nonfixture reservations across
all owners of one database. Trusted local tests may choose an integer limit from
one through 64. Creating a session or replacing/restarting an adapter cannot reset
this database-wide history. Even a reservation found stale before dispatch uses
its slot conservatively. There is no HTTP reset or reconciliation escape.

Only one RESERVED/DISPATCHED nonfixture operation can exist per database, enforced
both by admission and a unique partial index. Fixture proposals have no call quota
and can supersede one another, but still pass the generation fences. Validated
nonfixture observations persist actual supplied token counts, including successful
responses that became stale before attachment. All dispatched failures lacking a
valid observation are UNKNOWN: refusal, incomplete, malformed result, missing
usage/identity, transport error, timeout or unsupported injected adapter. They
retain their slot and block further nonfixture reservations across restart. A
valid observation with invalid local results may record a BLOCKED outcome with
known usage. No failure is represented as zero-token success.

This is a call-count bound and conservative stop policy for injected offline
work, **not a USD bound, token reservation, pricing calculation, service-tier
verification, real input-token count, or permission for paid inference**. Existing
request/response/output limits remain. The model's actual service tier, vendor
usage behavior and charge outcome remain unverified. Unknown accounting cannot be
cleared merely by constructing another adapter. Deleting a database is not an
accounting/recovery mechanism.

## Crash and restart behavior

Service ownership still uses the existing process lock. After actual process
death, startup changes every surviving RESERVED/DISPATCHED analysis to UNKNOWN
and blocks the matching current checkout with MODEL_OUTCOME_UNKNOWN. Startup and
bootstrap never replay the adapter. A reservation may or may not have dispatched;
it is not guessed free. Old operations do not replace a newer review generation.
The real subprocess tests exit after reservation commit, after dispatch commit,
and before observation commit, then open the same database and verify no replay.

The adapter's own overall timeout can leave its daemon transport worker running.
The service records UNKNOWN and never attaches its late result. Python cannot
prove remote cancellation or reclaim an unknown charge. The durable breaker
prevents a newly constructed adapter from opening a second nonfixture attempt.
No genuine call was made to establish these synthetic properties.

## Evidence and remaining gates

Tests cover actual SQLite writes while inference waits; successful injected wire
observations; global concurrency/attempt limits; persistent refusal/error/timeout
breakers; source/model/generation/checkout/wire tampering; duplicate claims;
observation identity/usage mismatches; stale-result accounting; and actual process
crashes. Run the README aggregate checks against the final assembled revision;
component results do not certify a later integrated tree.

Real input counting, bounded provider/data/call/token/spend authorization, service
tier and current pricing, reviewed HTTPS transport, secure credential approval,
provider wire acceptance and fresh semantic/buyer-baseline evidence remain mandatory
live gates. This change does not enable AI or PayPal, release/deploy the server,
change payment authorization, or authorize paid work.

Rollback to the previous application version leaves the new analysis table
unused, but old code must not be used to hide unknown nonfixture accounting. Keep
the database and operation history private. No automatic downgrade, ledger purge,
or delete-and-retry procedure is provided.
