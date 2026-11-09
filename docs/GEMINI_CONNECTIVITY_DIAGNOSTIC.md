# Disabled hosted Gemini connectivity diagnostic

Issue #64 adds a functional **fabricated-offline diagnostic core**, not a live
connection or application integration. The workflow is physically disabled with
one constant-false job. It has no input, Secret binding, checkout, installation,
upload, provider command or activation flag. Do not dispatch it: even a skipped
scaffold run could consume the first-run counter of a later enrollment.

The production script always prints `NOT_RUN` with
`PRODUCTION_ACTIVATION_UNSUPPORTED`, exits 2, and does not read arguments,
environment values, metadata, credentials, files or application assets.
The default path imports no application code. A separate unselected wire lazily
imports the reviewed HTTPS transport and deadline primitive, never an application
Service, runner, database, client constructor or protected semantic assets.
Existing fixture/server/payment behavior and PR #63 are unchanged.

## Fixed public synthetic request

The canonical ASCII JSON bytes are produced only by this module's fixed literal,
with sorted keys and compact separators. The prompt is:

`Synthetic connectivity diagnostic. Reply READY.`

- Fixed endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`.
- Fixed requested and expected observed model: `gemini-3.5-flash-lite`.
- SHA-256: `1d5aeeb73cc4fa2225e99bd1bdccd5a963251e00e1f7cd9f6561489b980f95f8`.
- One candidate, temperature 0, MINIMAL thinking and a requested maxOutputTokens
  cap of 32. Accepted local observations require answer plus thoughts at most 32.
  This does not prove a real model's externally enforced billing cap. No tools,
  streaming, count request, caching, files, SDK or fallback.
- The synthetic grant still requires the conservative one-call allowance of
  1,048,576 input and 2,048 output tokens, zero micro-USD and explicit
  `externally-verified-free-tier` mode. These are local limits, not account facts,
  a quota guarantee, actual usage or an invoice.

The fixture transport receives only this endpoint, these bytes and a 20-second
timeout parameter. No key is accepted by this core. The fixture must perform no
network I/O. Returning late is UNKNOWN; this core cannot forcibly cancel a
blocking injected function or prove a remote request was cancelled.

## Unselected reusable HTTPS wire

`UnselectedHTTPSWire` reuses the existing `GeminiHTTPTransport`; it does not
implement another TLS stack. Construction retains explicit host claim-guard and
credential-borrow callbacks without imports or I/O. A one-shot lock burns before
lazy imports. Exchange accepts only the exact fixed endpoint, bytes and timeout.
The reused transport rechecks the guard before each I/O stage, borrows once,
uses verified TLS with minimum TLS 1.2 and no key logging, disables automatic
reconnect, and follows no redirect or ambient proxy. Private response bytes feed
the validator, never user-facing output. All failures, including BaseException
subclasses, are sanitized after synchronous transport cleanup, without retry.

The existing wire's response hard limit is 131,072 bytes. The wrapper rejects
returned bodies over 16,384 bytes, which is also the parser limit; it does not
claim the network stops reading at 16 KiB. Guard/borrow callbacks are trusted
host plumbing, not verified authority. No permanent diagnostic claim or secure
credential resolver is supplied. New wire objects cannot renew actual authority.
The class labels itself `unselected-provider-runtime`, never provider evidence.
The fabricated executor rejects this class. Neither CLI nor workflow constructs
it, even if metadata or environment values are supplied.

Tests exercise real reviewed HTTPS logic with fake connections and synthetic
keys only, while banning actual sockets/default HTTPS construction. They cover
guard denial before effects, TLS/framing, redirects, bounded bodies, single
borrow, cleanup, sanitized factory/borrow/read/close and missing-module failures.
Fresh lazy import/send is checked with Python file opens forbidden. Only the ten
reviewed runtime Python dependencies were materialized for these focused checks;
no semantic assets were read or copied.

## Offline consistency contract

`OfflineDiagnostic.run` accepts minimized synthetic projections and a fabricated
transport. Fixtures deliberately invent all IDs, grant references and timestamps.
`fabricated-offline` is an evidence label, not an authenticated capability. Python
objects can be forged. This code does not authenticate metadata, establish owner
consent or verify hashes against an external authority.

The enrollment projection has exactly numeric `repository_id`, `workflow_id` and
`actor_id`; fixed workflow `path`; `refs/heads/main`; reviewed 40-hex `head_sha`;
and integer `valid_from` / `expires_at`. Its absolute window must be positive,
at most 86,400 seconds, and current. No actual enrollment is committed or minted
from newly discovered metadata.

The snapshot projection has exactly `evidence_kind`, `http_status`, `next_page`,
`truncated`, `current` and `history`. Only fabricated-offline, integer 200, no next
page and exact false truncation are accepted. The current normalized run binds
the exact enrollment identity plus positive `id`, integer `run_number == 1`,
integer `run_attempt == 1`, `workflow_dispatch`, `in_progress`, null conclusion
and in-window integer `created_at`. History must contain exactly that same typed
current record with integer `total_count == 1`. Missing, partial, inconsistent,
paginated, unexpected or malformed evidence fails closed. Any extra run fails,
including failed, cancelled, queued, successful and unknown outcomes.

The fabricated grant requires the exact request digest, endpoint/model/version,
finite window inside enrollment, exact limits/mode, and nonsecret 64-hex reference
fields for exact-request owner approval, credential-transmission approval,
Free-project facts and zero-cost compute facts. It is explicitly a
`fabricated-connectivity-grant-v1` test object, never an application
`gemini-approved-host-record-v2`. No command generates either real approval.

Each diagnostic object consumes its sole in-memory attempt before validation.
Concurrent/repeated use cannot call its transport again. This memory guard is
**not** a cross-process permanent ledger: new objects are allowed only as new
synthetic test cases, never as live retries. HTTP errors, exceptions, cancellation,
timeout/late response, clock regression, expiry, wrong model, malformed or
contradictory/missing usage, unsupported fields and incomplete candidates produce
terminal UNKNOWN. No retry, fallback, renewal or credit is implemented.

Safe fabricated results contain only status/evidence enums and, when accepted,
the exact validated model plus bounded integer input/output/total usage. Output
tokens include thoughts. Response text, headers, raw bodies, exception text,
project data and grant references are never returned or logged. Text shape is
checked but its meaning is not evaluated. `FABRICATED_ACCEPTED` is not provider
acceptance, semantic quality, actual zero charge or a successful application run.
The ordinary optional responseId is bounded, validated and discarded. Additional
usage detail fields or thought signatures remain explicit schema blockers, not
silently ignored or evidence of a usable production integration.

## Unsupported production gates

Activation is a separate reviewed implementation and permission decision, not
an edit to a workflow input or a copied example grant. All the following remain
unsupported or UNKNOWN:

1. A fixed verified GitHub HTTPS metadata adapter with ephemeral builtin token
   and only `actions:read`, exact current-run and complete history reads, strict
   API/authentication/error handling, and no tokens in URLs/logs. The present
   parser cannot turn injected JSON into authenticated evidence.
2. A pre-enrolled immutable numeric repository/workflow/actor identity, fixed
   path/ref/reviewed revision and one absolute nonrenewable window at most one
   day. Authenticated run number one **and** attempt one are mandatory. Fixed
   global concurrency with no cancellation only supplements this fence.
3. Permanent retirement after any first run, expiry, uncertainty or workflow
   deletion/recreation/rename. Run-history retention/deletion makes history alone
   insufficient. Never enroll a newly discovered replacement ID or reset/rotate
   the window to recover another attempt. This is a bounded one-time enrollment,
   not a general persistent accounting service.
4. Real owner approval of these exact diagnostic bytes and recipient, plus the
   required action-time approval for Secret-to-Google transmission. A dispatch
   click, generic preapproval, workflow input or fabricated hash supplies neither.
5. Actual project/model Free eligibility, no paid fallback and current zero-cost
   GitHub compute conditions. Public price pages do not verify either account.
   Unknown means blocked; hosted private-repository compute is not assumed free.
6. A production activation adapter joining the unselected HTTPS primitive to
   externally preserved permanent burn evidence, current verified account facts,
   approved credential transmission and secure one-shot borrowing. The existing
   wire alone does not establish these facts. No activation adapter or Secret
   binding exists in this change.

This separate connectivity diagnostic never prepares, restores, approves or runs
an application analysis. Application execution still requires its original
same-host DB path/device/inode/owner/runtime binding, exact prepared-request
external review and permanent capacity/UNKNOWN history. It cannot export a DB
artifact, restore a cache, manufacture an approved record or renew app authority.

## Verification and remaining evidence

From repository root, the isolated checks need Python standard library only:

```sh
python -m unittest discover -s cart_readback/tests -p test_gemini_connectivity_diagnostic.py -v
python -m compileall -q cart_readback/scripts/gemini_connectivity_diagnostic.py cart_readback/tests/test_gemini_connectivity_diagnostic.py
python cart_readback/scripts/gemini_connectivity_diagnostic.py
# Last command must print NOT_RUN and exit 2, never imply a successful call.
```

Tests forbid real socket creation and use invented metadata and response bytes.
Workflow YAML/static guards are separate checks. Full repository fixture
integration remains required by CONTRIBUTING.md; these focused tests do not
replace it. Full semantic assets were not materialized for this change.
Hosted workflow, real metadata authentication/enrollment, key validity, account
eligibility, costs, Gemini call, application integration, semantic evaluation,
PayPal, browser, deployment and submission all remain NOT_RUN or UNKNOWN.

Rollback removes these four additions only. Never erase an actual workflow run,
database, approval or burn history as rollback/retry preparation.
