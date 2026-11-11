# Opt-in Gemini host analysis

Issues #48/#50 provide a **host-only, one-shot analysis path**, using the shipped Gemini
client and fixed Google HTTPS connection. The ordinary fixture CLI, HTTP API and
buyer UI remain unchanged. This path must not be passed to `LocalServer`: the
current buyer UI accepts only its separately documented provider identities.
PayPal is unconnected; Gemini analysis permits only the exact fixture payment
adapter, including subsequent replacement assignments. The runner performs only
analysis, never confirmation, order creation, approval or capture.

Implementation and tests do **not** establish a working Google account, usable
key, eligibility, model quality, actual price, real response or invoice. All test
credentials and wire responses are fabricated. No real key, TLS connection,
provider call, deployment or PayPal experiment was used to develop this slice.

Issue #50's explicit free/paid contract below supersedes only the original C13
positive-only admission requirement. In that original slice, prompt preflight
bound that API contract's original bytes and prompt/corpus/gold/scorer artifacts
were unchanged; the later production prompt identity is described below.
The HTTP/API selection remains disabled.

## Current use and historical implementation scope

The preceding test claims describe the original Issues #48/#50 slice, not all
subsequent observations. See the dated [current status](../README.md#current-integration-status--november-10-2026).
The private Actions host uses an already owner-configured repository Secret
inside its reviewed launcher; the application runner itself still accepts only
the inherited private pipe and does not discover environment keys. Do not paste
the Secret into chat or a command. The current v3 prompt identity and optional
bounded span hints are described in [GEMINI_CLIENT](GEMINI_CLIENT.md); prepare/run
must bind the exact changed request and runtime, never reuse an old record.

The commands below are host-interface examples, not a self-contained setup:
`host-plan`, independently approved record, existing private DB/owner and an
opened/inherited credential descriptor must already be supplied. No developer
signup or credential creation is required or performed by these commands.
The manual launcher proposed in draft PR63 is not included on this main revision;
`docs/GEMINI_MANUAL_LAUNCHER.md` is not an available main-branch runbook.
Do not substitute that draft for the reviewed current host path.

## Approval boundary

A trusted host must independently establish and review:

- One explicit `gemini-2.5-flash-lite` or `gemini-3.5-flash-lite` selection and
  exact expected returned version. There is no fallback. 2.5 requires evidence
  that this project remains eligible; merely possessing an old key is not proof.
- Google project, tier, credential version and host revision, with nonsecret
  binding/eligibility record references. Record hashes identify records; this
  program does not authenticate their authors or verify their factual contents.
- An explicit admission mode, project billing tier and adopted integer micro-USD
  per million tokens for uncached input and all output, including thoughts.
  `paid` requires tier `paid`, two strictly positive rates and strictly positive
  authorized spend. `externally-verified-free-tier` requires tier `free`, exact
  integer zero/zero rates and exact integer `max_micro_usd=0`. Mixed rates, bools,
  negative values and mode/tier/allowance mismatches fail closed. No paid fallback
  exists. Do not copy OpenAI rates or infer free eligibility from an old key.
- A `host_decision_record_sha256` identifying the externally reviewed decision
  for this exact project/model/version, eligibility/pricing records and window.
  In free mode that record must establish current Free-tier eligibility, no paid
  project billing/fallback, Standard free input and thought-inclusive output,
  and sufficient model/context/call/token quota. The permission to disclose the
  exact data and execute within those bounds must also exist outside this code.
  A record hash is not an authenticated Google fact, consent or no-charge guarantee.
  In paid mode the decision must instead cover the adopted paid rates and spend.
  Public Google pricing alone does not establish account-specific eligibility.
  API keys inherit project billing; a paid spending cap can overshoot due to
  reporting delays and is not a strict zero-cost mechanism.
- The full 1,048,576-token model input ceiling used in this conservative slice.
  The client cap is not evidence that the particular account supports it. A
  lower externally established ceiling requires another reviewed admission
  mechanism; this runner does not infer a tighter bound from local text bytes.
- The complete selected synthetic catalog record, its current revision/price,
  exact ordered typed conditions, owner hash, runtime/configuration, database,
  and approved disclosure/spending window.

Both the pricing policy and authorization last at most one day, have finite
call/input/output/spend allowances and do not renew. The runtime requires local
records to agree exactly. A JSON `approved: true` field is not accepted as proof
or as an installation shortcut. The approved-record file is a **trusted local
host decision**, not independently verified user consent, a Google API grant, a
cryptographic attestation or an externally enforced Google billing ceiling.
Obtaining that decision and permission to disclose data/incur charges remains an
external prerequisite. Do not manufacture a record from these examples to infer
permission.

## Two-stage runner

Run from `cart_readback/`. No extra package is needed. Prepare and run must use
the same host, code/runtime revision and private database file. Do not put real
keys in command arguments, environment variables, repository files, JSON records,
logs or chat. An ambient `GEMINI_API_KEY` is ignored and supplies no authority.

### 1. Prepare, offline

The host supplies a nonsecret `host-plan.json` object with exactly these fields:

- `binding`: `project`, `credential_version`, `host_revision`.
- `config`: `model`, `expected_model_version`, `response_language` (`en` or `ko`).
- `policy`: `valid_from`, `expires_at` (integer UTC epoch seconds), `model`,
  `expected_model_version`, `max_input_tokens` (1048576),
  `input_rate_micro_usd_per_million`, `output_rate_micro_usd_per_million`,
  `project`, `tier` (exact `free` or `paid`), `eligibility_record_sha256`,
  `pricing_record_sha256`, `admission_mode`, `host_decision_record_sha256`.
- `binding_record_sha256` and `pricing_adoption_record_sha256`: lowercase
  64-hex references to the independently established host records. The latter
  must equal `policy.pricing_record_sha256`.
- `installation_revision`: a bounded ASCII nonsecret host installation revision.
- `timeout_seconds`: positive, at most 20 seconds.
- `limits`: `valid_from`, `expires_at`, `max_calls` (1–64),
  `max_total_input_tokens`, `max_total_output_tokens`, `max_micro_usd`,
  `admission_mode` (must equal the policy mode). Call/input/output limits stay
  strictly positive in both modes; only free-mode spend is exactly zero. The
  authorization window must fit wholly inside the policy window. For one call,
  allowances must cover 1048576 input and 2048 output tokens and the upward-rounded
  full reservation at the adopted rates.

String identifiers use ASCII letters, digits, underscores and hyphens (1–128
characters). Each rate is an integer; units are micro-USD per million tokens,
not floating-point dollars. Host references must contain no secret material or
hashes of keys. This module does not look up a plan or infer any missing value.

Example typed selection file `conditions.json`:

```json
{"conditions":[{"kind":"layout","value":"UK_QWERTY"},{"kind":"included_cable","value":"USB-C to USB-C"}]}
```

After those nonsecret host inputs are independently established:

```sh
python scripts/run_gemini_analysis.py prepare \
  --db /private/cartreadback/analysis.sqlite3 \
  --owner-file /private/cartreadback/owner \
  --host-plan /private/cartreadback/host-plan.json \
  --sku KB-UK-C2C \
  --conditions /private/cartreadback/conditions.json \
  --output /private/cartreadback/approval-request.json
```

Prepare may initialize the private fixture database and a random owner session.
An existing owner file must refer to an existing session; it is not silently
replaced. The owner token is written only to an exclusively created mode-0600
file, not to stdout or the approval request. Keep the directory, DB, sidecars and
owner file private. Request output also uses exclusive creation, never overwrite.
The host should set its normal private-directory permissions/umask before use.

Prepare does not construct a connection, read a credential, consume allowance,
create an approval or select a runnable Service. It emits the exact nonsecret
request and prints its SHA-256. The request includes the database's persistent
identity, a hash binding its resolved path/device/inode, owner hash, catalog,
ordered condition IDs, current session revision, exact generation-request hash
and execution identity. The latter binds the Python/OpenSSL runtime and reviewed
provider mechanics, prompt/configuration, credential binding and the complete
policy hash, including admission mode, project/model/version, both external
eligibility/pricing references, host decision, rates, context and time window.
Provenance and the DB-bound allowance bind that same policy. Code changes
between prepare and run require a newly reviewed request, never silent rebinding.

### 2. Review externally, then run explicitly

An authorized host reviews the exact request, independently verifies the facts
and grants the bounded action. It supplies a separate private approved record:

```json
{
  "schema": "gemini-approved-host-record-v2",
  "approval_reference": "EXTERNALLY_ESTABLISHED_RECORD_ID",
  "request_sha256": "EXACT_64_HEX_DIGEST_PRINTED_BY_PREPARE",
  "request": "THE_COMPLETE_UNCHANGED_REQUEST_OBJECT_NOT_A_STRING"
}
```

The last value is the complete request **object**; the quoted placeholder above
is intentionally not a runnable record. The runner validates the complete exact
shape and digest. There is no command that creates this approval automatically,
no key creation and no account enrollment.

The approved host secret-store launcher must pass an **already opened private
FIFO/pipe descriptor** to the child, containing only the existing key's ASCII
bytes (no newline), and close the writer after supplying them. The descriptor
must be explicitly inherited across process execution. The launcher should not
place the key in its shell history, environment or temporary files. Its identity,
pipe confidentiality and accurate binding are host responsibilities, not proven
by the descriptor number. Only the number appears in the runner invocation:

```sh
python scripts/run_gemini_analysis.py run \
  --db /private/cartreadback/analysis.sqlite3 \
  --owner-file /private/cartreadback/owner \
  --approved-record /private/cartreadback/approved-record.json \
  --credential-fd 3
```

This command is a future authorized operation, **not** a command executed in the
implementation tests. No actual secret-store handle was installed in this work.
The descriptor route is ephemeral; it does not authorize saving credentials or
creating persistent access.

The borrower checks exact credential binding, permits one borrow only, reads at
most 4096 opaque graphic-ASCII key bytes with nonblocking I/O and the operation
deadline, and
requires EOF. This is a local defensive cap, not a Google key-format contract.
Whitespace/control bytes are rejected; the accepted value is not trimmed or
rewritten. A stalled writer cannot block indefinitely. Regular files, sockets
and terminals are rejected. No read or descriptor mode change occurs until after
the durable claim and per-step guard. Buffers are cleared best-effort; Python
cannot promise erasure of every immutable temporary string.

Run opens the existing DB read-only to verify owner, file identity, persistent
identity, catalog and revision before constructing its existing-store wrapper.
All subsequent connections use SQLite `mode=rw`, never `rwc`: deleting or
replacing a database cannot create a fresh run-phase store. Copying the prepared
DB to another path or replacing its inode also fails. Do not delete/recreate,
restore old backups or manipulate SQLite history to renew an allowance. A fully
privileged host rollback of the original file is not cryptographically prevented.
The supported host is trusted and must preserve its database/history.

Issue #50 versions the private policy identity as `gemini-capacity-v2` and both
request/approval schemas as `gemini-host-approval-request-v2` /
`gemini-approved-host-record-v2`. Explicit mode, tier and external-decision fields
are mandatory, including for paid hosts. Old v1 approvals/policy documents fail
closed; they are not inferred to be paid or free and are not automatically
migrated. Existing database identities and operation rows are never replaced.
A new record, mode, evidence or window cannot renew an old allowance or clear
UNKNOWN. Retain the original database/history; unsupported legacy recovery is
blocked pending separately reviewed handling, not permission to create a fresh
database, restore an older backup or replace approval/history to bypass it.

The runner selects only the shipped provider connection. Its output is the
Service's safe public envelope; private project, credential, approval, ledger,
runtime identity and owner token are not included. It does not print provider
payloads or exceptions containing secret material. A blocked command reports a
sanitized failure and does not retry. If the watchdog returns while cleanup is
still active, the runner waits for actual worker exit before releasing the
Service lease. Forcefully stopping it is not proof of remote cancellation.

## Lifecycle and public evidence

Each operation permanently consumes a full 1048576 input-token reservation and
2048 output tokens, including thinking, plus one call. Paid spend is upward-rounded
at the adopted positive rates; explicit free mode reserves exactly zero USD.
Zero spend never removes the finite call/token limits. The full context is
**conservative local accounting**, not a 1M-token request, quota proof or invoice.
Only the bounded prepared source/conditions request is sent.
A smaller known usage result never credits capacity back. This intentionally
restrictive first slice does not call a count endpoint or invent a local token
estimate. 3.5 MINIMAL thinking is not zero thinking; thought usage is included.

Reservation, the matching analysis operation and pending checkout commit in one
transaction. One durable claim commits before any socket or credential borrower.
Every connection, connect, borrow, POST and read step rechecks the exact claim,
request, owner, catalog, conditions, runtime, credential binding and deadline;
provider I/O holds no database transaction. The Service owns activity before the
worker starts until synchronous transport cleanup and observation actually exit.

A crash, timeout, stale/late response or uncertain dispatch preserves UNKNOWN on
the original operation. Restart never replays a POST. No model fallback,
replacement operation, owner change, reconstructed runtime, policy change or
switch to fixture/OpenAI may bypass unresolved history. Orphaned ledger/analysis
rows fail closed. The immutable DB-bound allowance is not replaced by a new
runtime instance or renewed host record.

Accounting is independent of proposal acceptance. A refusal or invalid proposal
can retain independently valid bounded usage but cannot create a confirmable
snapshot. Wrong model, contradictory usage, duplicate identity or unsupported
provider activity cannot produce a successful known-contract result. Matching
late accounting may be appended to the original operation; UNKNOWN and invalid
consent are never cleared. Raw responses, thought signatures and keys are not
persisted as accounting.

Public mode is `genuine-gemini-capacity`, strategy `gemini-capacity-v1`, provider
`google-gemini-generate-content`. Configured capability is not an observed call.
Only the fixed provider runtime may label retained accounting a
`provider-observation`; fabricated transport bindings always remain
`fabricated-offline` and never report network capability. Payments remain
separately labelled `fixture`. Do not describe a provider-capable analysis as
“No money moves”: inference may incur charges after explicit external approval.
Exact quotes and schema checks do not establish semantic truth or buyer benefit.

## Offline verification

From `cart_readback/`, runner-specific tests are:

```sh
python -m unittest discover -s tests -p test_gemini_runner.py -v
```

These use only fabricated host records and synthetic pipe bytes, with real socket
creation prohibited. They cover offline prepare, no ambient credential discovery,
strict approval shape, modified records, foreign owner, stale catalog, wrong or
missing/copied/replaced DB, runtime/credential changes, lazy single borrowing,
pipe deadlines, oversize rejection and rejection of regular files. The separate
Gemini Service/client/HTTP/ledger suites exercise fabricated wire responses,
reservation/claim fencing, accounting, cleanup and crash recovery. Full integrated
fixture regressions remain required for the final changed tree.


## Free-tier references and remaining gate

Google publishes free Standard rates for the allowed Flash-Lite models. Those
public pages do not verify the actual key/project/tier, exact returned version,
quota/context support or owner approval, all of which remain UNKNOWN here.
No account/billing setting was inspected or changed. Relevant official sources:

- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/billing
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/terms

`test_gemini_zero_spend.py` uses only synthetic records and responses. It reruns
the Service lifecycle regressions in free mode, including subprocess crashes,
and exercises the real runner/Service with a synthetic pipe and replaced wire.
Zero reservation/accounting coexists with permanently consumed call/input/output
capacity. This is local admission evidence, not actual free-tier execution.

