# Finite input-only Gemini corpus execution

Issue #58 adds a distinct host-only route. It uses the existing genuine Gemini
request builder, fixed-origin HTTPS transport, strict result parser and
conservative accounting. No model, credential, account, billing or provider
interaction was performed during implementation. Fabricated tests are not
provider observations. Public Free pricing is neither this project's eligibility
nor proof of zero charges.

## Input and disclosure

`gemini-input-corpus-v1` is a strict UTF-8 JSON object containing only `schema`
and an ordered `cases` array, with 1–64 cases and a 4 MiB raw-byte limit. Each case
contains exactly `case_id`, `source` and `conditions`. Source retains the existing
`source_id`, positive `revision`, exact SHA256 and text contract. Revision is
bounded by 2^53−1. Each case has 1–2 existing typed requirements, carrying explicit
`condition_id`, `kind`, and `value`. IDs are nonempty, at most 160 Unicode code
points, and cannot contain control characters or surrogates. Case IDs are unique
across the corpus. Condition IDs are unique only within a case. Repeated source
and condition IDs across cases are allowed. No Unicode normalization occurs.

No product, SKU, price, gold, label, model result, replacement prompt or arbitrary
model setting is accepted. The runner does not create catalog products, mutate a
session revision, confirm a review or perform a payment. Supplied source text is
untrusted data, never an instruction to the host. Quoted evidence and valid
schemas do not establish semantic truth.

Offline prepare binds exact raw-file SHA256, canonical ordered request mapping,
full concrete input sources and requirements, model/version/language, unchanged
prompt identity, all application Python source bytes and both host runner files,
Python/TLS runtime, transport/installation identity, existing physical DB and
owner, and a snapshot of legacy history. Mapping preserves each ordinal, opaque
case ID, ordered condition IDs, source revision/hash, conditions hash and exact
generation-request hash. Changing raw whitespace alone stales the disclosure.
Only owned immutable bytes and JSON strings are retained internally.

Prepare creates no approval or active corpus identity. It may initialize empty
admission schemas and the same database's identity, never a replacement DB or
owner. Existing single-case approvals cannot be used as corpus approvals.

## Explicit finite authority and historical migration

A reviewed `gemini-corpus-approved-host-record-v1` contains `approval_reference`,
the complete prepared `request`, and its `request_sha256`. It references facts and
approval established outside this program; writing such a file proves neither.
The existing host-plan structure is reused, but corpus admission permits only
`externally-verified-free-tier`, zero/zero adopted rates and exactly integer zero
`max_micro_usd`. Positive finite call and token limits remain mandatory.

Activation and its cross-path exclusion commit together in the **same existing
SQLite database**. The original singleton and every prior row remain unchanged.
Shared history checks pair analysis with budget/context/Gemini operations in both
directions and check sessions, reviews and preflights. Unresolved, orphan,
unsupported or nonzero-spend history blocks activation. Previous permanent known
reservations count against the new **total**, not an extra allowance. The whole
ordered corpus must fit those remaining conservative limits before the first
reservation. Each new call permanently reserves 1,048,576 input tokens, 2,048
output tokens including thoughts, one call, and zero adopted USD. These are local
upper bounds, not actual prompt sizes, provider quota or billing receipts.

The activated corpus identity cannot be replaced, renewed or expanded. Different
owner, file, mapping, policy, source, runtime, model, window or limits fail closed.
No clear/reset/replace method is provided. Legacy nonfixture admission is blocked
after corpus activation. Fixture behavior and read-only/reconciliation interfaces
are preserved, but any fixture/session/catalog/history mutation intentionally
stales corpus continuation. Own corpus progress does not mutate the legacy
baseline. Expired history remains inspectable without renewing authority.

## Dispatch, credentials, recovery and freezing

The same Store process lease excludes another supported Service/runner. SQLite
transactions serialize activation, reserve, claim, observation and result state.
Exact request membership is checked at the ledger boundary and every guard, not
as independent source/condition/owner allowlists. Each ordered request is reserved
and committed, claimed once and committed, then exchanged synchronously. No
secret read or network call precedes committed claim. No retry, fallback,
parallel provider call, allowance refund or uncertainty clearing is supported.

Run takes one explicitly inherited POSIX FIFO descriptor per still-eligible
zero-based ordinal. Pipes must be readable, privately owned with no group/world
access, and distinct by `(st_dev, st_ino)`, including dup aliases. Metadata is
checked before reservation and again before one-shot borrow. Each handle binds
the exact ordinal, grant and credential version. There is no secret cache or
reuse of a single-case credential handle. Read size, nonblocking reads, EOF and
monotonic deadline remain bounded. All owned descriptors, including unused ones,
close on completion or rejection. Supplying unrelated descriptors is invalid.
The multi-pipe provisioner and actual data/credential approvals are external
prerequisites, not implemented by this runner. The new runner is POSIX-only.

Cleanup remains synchronous under the lease. Original monotonic deadline is
rechecked after exchange/cleanup and before accepting results. Accounting is
independent of prose. A known refusal/schema failure becomes a frozen case
failure and can continue; uncertain usage or a failed guarded attempt is UNKNOWN
and stops before the next request. Crash recovery permanently fences reserved or
claimed work UNKNOWN. Recovery/finalization needs no new credential and can occur
after approval expiry; it never authorizes another request. Resume supplies only
pipes for the remaining undispatched suffix after a wholly known prefix.

Observation and immutable case-result attachment share one transaction. Pairing,
request identity, result hash and structural result contract are checked before
freezing. Complete or stopped runs commit canonical case-keyed predictions,
failures, NOT_RUN suffix, mapping, reservations, accounting and integrity metadata
as authoritative bytes plus SHA256 in SQLite. No gold/scorer is loaded or accepted.
Scoring must happen separately after freezing. Late observations cannot alter a
frozen artifact. These hashes detect accidental changes, not malicious trusted
host/database rewriting or a cryptographic provider attestation.

Export writes a complete private temporary file, fsyncs it, atomically links it to
a new destination without clobbering, then fsyncs the directory. A crash can leave
an orphan temporary file but cannot expose a partial new destination. An existing
partial or complete artifact is preserved. Export failure never resumes execution.
Credential-free read-only re-export uses the stored frozen bytes and verifies
their hash; use a fresh destination if the old path already exists.

## Commands and limits

Run commands from `cart_readback/`. Prepare is offline, but it requires an existing
application DB and existing owner file, not a new identity invented for each case:

```
python scripts/run_gemini_corpus.py prepare --db SAME_DB --owner-file SAME_OWNER \
  --corpus INPUT_ONLY_JSON --host-plan REVIEWED_PLAN --output NEW_DISCLOSURE
```

After external eligibility, disclosure, zero-charge, finite-limit and credential
authorization, the host can select `run` with the distinct reviewed record and
explicit inherited pipes. This documentation is not permission to run it:

```
python scripts/run_gemini_corpus.py run --db SAME_DB --owner-file SAME_OWNER \
  --corpus EXACT_INPUT_ONLY_JSON --approved-record REVIEWED_CORPUS_RECORD \
  --credential-fd 0:INHERITED_FD --credential-fd 1:OTHER_INHERITED_FD \
  --output NEW_FROZEN_RESULTS
python scripts/run_gemini_corpus.py export --db SAME_DB --output NEW_EXPORT
```

There is no default network mode, credential lookup, gold argument, public
endpoint, ordinary UI activation, account setup or provisioner. The physical DB,
owner, old ledgers and history must not be rotated to evade a block. One finite
corpus lifetime per DB is deliberate; extending it requires a separately reviewed
migration, not edited approval files.

## Verification boundary

Implementation used a source-only copy and invented development cases and an
invented mechanics-only prompt bundle patched in tests. No holdout inputs, gold,
old evaluation records or shipped semantic prompt contents were inspected.
The genuine client/HTTP and capacity mechanics were exercised with fabricated
connections only. Procedural separation is not a secure data sandbox.

Focused corpus tests include raw/mapping drift, opaque IDs, free/finite bounds,
legacy consumption and UNKNOWN/orphans, simultaneous admission, dup pipe aliases,
scope/privacy/early cleanup, real child-process crashes after fake dispatch and
observation, synchronous cleanup deadlines, freeze tampering, and crash-safe
re-export. Existing aggregate evaluation/prompt/UI checks require a separately
permitted verification role and are not certified by this source-only test pass.
No actual account eligibility, provider acceptance, real charge, semantic quality,
minimum-runtime/platform compatibility or buyer benefit is established.
