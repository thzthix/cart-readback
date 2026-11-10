# One-call model-metadata check, not inference

This local run-3 proposal responds to the owner's new request to recheck the
re-saved GitHub Secret. It is based on reviewed commit
`53d04ef010dcc0710ea5671d14310c6c9688bdeb`. **It has not been published,
dispatched or executed, and no real key value has been inspected.**

## Fixed metadata request and narrow result

Use only GET `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite`,
with an empty body (`b""`) and the existing step-only `GEMINI_KEY` supplied only
in `x-goog-api-key`. No prompt, JSON generation payload, inference, list/count
request, POST, fallback or second provider request is made. Google's
[models.get reference](https://ai.google.dev/api/models) specifies a GET returning
Model metadata and an empty request body. The [key guide](https://ai.google.dev/gemini-api/docs/api-key)
describes authentication. These sources do not establish a separate $0 invoice
guarantee for this check, Free eligibility or generation access.

Body SHA-256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Canonical request descriptor is the ASCII method, one space, exact request path,
one newline, then the body SHA-256. Its SHA-256 is
`85f267f4987afd2fccad05c00f08425b509e26487604eed6e1780f27999cd344`.
The independently reviewed source pin binds the fixed method/path/body constants.

The only success receipt is MODEL_METADATA_VALIDATED plus the fixed public model
name. It requires HTTP 200, the existing bounded/strict framing, at most 16 KiB of
valid UTF-8 JSON without duplicate keys or literal NaN/Infinity numeric constants,
and exact required `name` `models/gemini-3.5-flash-lite`. Other bounded metadata
fields are discarded without interpreting their values. It does not
report usage, token counts, returned descriptions or supported methods, and does
not claim successful inference, generation permission, available quota or billing
status. Unsupported metadata emits the existing non-success HTTP_200_UNVALIDATED
receipt. Non-200 responses stop before body admission, retaining only exact
numeric HTTP status and the local phase. No provider message/details are emitted.
The `request-attempt` phase marks the local call boundary, not remote acceptance.

## One new slot, preserved prior history

Current complete read-only repository history contains exactly two runs for
workflow 405198760: run 42617340271, number 1 / attempt 1; and run 42639744339,
number 2 / attempt 1. Both remain untouched and spent. Run 1 stays UNKNOWN with
zero or one POST possible. At its exact 29072098 source, run 2 stopped at
credential/UNKNOWN before the native POST call and attempted no native POST.

The job, inline fetch and probe admit only run 3 / attempt 1. Recheck the exact
branch head and complete workflow history immediately before a released dispatch.
Stop on a later run or material mismatch. Any failure, cancellation, skipping,
timeout, UNKNOWN or offline-mode run consumes this slot. No retry, rerun, new
window after consumption, counter reset or further fence advance is permitted.
The unused local run-3 generation POST proposal was retired without publication
or execution; this fixed metadata GET replaces it, not GET followed by POST.

Verified TLS, disabled debug/key logging, no ambient proxy or alternate key,
verbatim bounded opaque-key handling, fixed safe credential-failure reasons,
owner/repository/actor/revision/source bindings, exclusive claim, at-most
600-second absolute window and no-retry transport remain unchanged. The current
opaque-header defense remains nonempty graphic ASCII with a local 4096-byte cap,
not a Google key-format guarantee. No key value/hash/length/prefix/fragment is
read during preparation. No additional account authority or persistent access
is created. Source publication and dispatch remain held for parent release and
independent review; no current Free-tier or inference-cost assumption is used.

## Preserved historical generation diagnostic

The remaining sections record the older generation path and spent attempts,
including their original request hashes and approval conditions. They do not
activate or describe the current metadata request above.


Issue #64 / draft PR #65 now prepares the shortest actual hosted connectivity
path. Earlier fake-only APIs (`OfflineDiagnostic`, fabricated grants/enrollment
and the separate disabled workflow) are retired from the current branch. Their
commits, reproduced failures and reviews remain preserved history, not evidence
that a provider connection occurred. Application Service, DB, prepared approvals,
semantic assets and PayPal are unchanged.

**No workflow was dispatched or real credential read during this correction.** Do not
run this until the operator has verified the exact request/recipient approval,
required action-time credential-transmission approval, key-to-Free-project
binding, current model/account eligibility, no paid fallback and zero-cost
compute. Workflow inputs and public pricing do not establish those facts.
Unknown means no agent dispatch.

## Spent run 2 and local credential compatibility correction

Run [42639744339 / attempt 1](https://github.com/thzthix/cart-readback/actions/runs/42639744339)
executed commit `29072098ffa6922265aecc08c89135ed52c984f4`. Its final receipt
was UNKNOWN at the credential phase, before the native POST call boundary.
Run 2 is SPENT. Run 1 remains unresolved and spent. No rerun, new dispatch,
window renewal, run 3, credential change or provider request is authorized here.
The run-2/attempt-1 gates below remain unchanged and cannot admit a later run.

The old local alphabet `[A-Za-z0-9_-]` rejected a period. Google's current
[Gemini key guide](https://ai.google.dev/gemini-api/docs/api-key) describes the
migration to authorization keys. The [Cloud authentication guide](https://docs.cloud.google.com/docs/authentication/api-keys)
confirms that authorization keys support the Gemini API, without defining a
key-string alphabet or maximum length. A [participant reply on Google's forum](https://discuss.ai.google.dev/t/account-restricted-to-aq-prefix-keys-requesting-standard-aiza-key-restoration/170966/2)
describes the migration to AQ authentication keys; the reply's staff status has
not been verified. The same thread's later regex explanation is a community reply,
not an API specification.

The local correction treats the credential as opaque, preserving its exact
value without trimming, prefix checks or normalization. It accepts nonempty
ASCII graphic characters (0x21–0x7e), at most 4096 bytes. That cap is a local
bounded-header defense, not a claimed Google format guarantee. Spaces, controls,
CR/LF, DEL and non-ASCII remain rejected. This fixes a reproducible compatibility
defect for public invented dotted credentials. It does not establish the real
key's shape or reconstruct why run 2 failed. No real key was inspected.

Credential-phase failures now add only one fixed reason enum:
CREDENTIAL_LOOKUP_FAILED, CREDENTIAL_REJECTED, CONTEXT_REJECTED,
DEADLINE_EXPIRED, CLAIM_STAT_FAILED, CLAIM_CHANGED,
SOCKET_TIMEOUT_SETUP_FAILED, INTERRUPTED or UNEXPECTED_LOCAL_ERROR.
CONTEXT_REJECTED includes the absolute window check. Other phases keep their
existing receipts. Cleanup failure retains the reason and forces UNKNOWN.
No raw exception, credential value, prefix, length, hash, header or body is
reported. The unchanged request/model/caps and no-retry transport are preserved.
These fields describe only executions of this new source, never the old run.

Offline regressions use public invented dotted and long credentials, actual
temporary claim files and an os._Environ mapping with only public fake backing.
One test exercises the default native HTTPSConnection.connect path, an actual
SSLSocket over an AF_UNIX socketpair, native timeout setup and header encoding.
TLS handshaking and all sends are deliberately stopped; no external connection,
provider response, authentication validity or model execution is tested.

## Historical local run-2 proposal; now spent

This local-only candidate is based on commit
`9314c4d3d300053425dce95716967e762b981723`. Nothing was pushed or dispatched.
Read-only GitHub metadata reports exactly one repository workflow run:
workflow 405198760, run 42617340271, number 1, attempt 1. With history preserved,
the sole next candidate slot is run number 2, attempt 1. Immediately before any
later approved dispatch, recheck those facts; if any other run exists, STOP.
Do not advance the fence again, rerun, delete/reset history or use another route.

The only proposed request change is omitting `candidateCount`. The
[Gemini 3.5 migration guide](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5?hl=en)
says it is unsupported in Gemini 3.x; the
[generic API reference](https://ai.google.dev/api/generate-content?hl=en)
defaults omission to one. All other payload/model/caps remain unchanged.
This does not establish why the old attempt was UNKNOWN. Proposed canonical
request SHA-256: `b62b017f7a20d56124b384ba406bcc2f31b9da13b7ae240bb3fa7f765bf03fca`.

The job, inline fetch and client each admit only run 2 / attempt 1; old run 1
stays spent. Source pins, exact reviewed commit, at most 600-second fresh absolute
window, concurrency, exclusive claim and one-POST/no-retry controls remain.
The existing step-only `GEMINI_KEY` binding is unchanged. Before publication or
execution, obtain the user's explicit new per-action credential-transmission
approval for this exact request to Google, verify the same key's Free-project
binding/current eligibility and zero-cost Actions capacity. No key value, hash,
length or fragment is read during preparation. Public Free pricing is not account
evidence. Unknown eligibility/cost/approval means STOP; no paid or OpenAI fallback.

The historical sections below describe the spent run-1 baseline. They do not
authorize, restore or replay it. Any newly approved run-2 attempt is consumed by
failure, cancellation, skipping, timeout or UNKNOWN, as well as success.

## Spent executed baseline and future-only observability

The one authorized attempt is SPENT: [run 42617340271, attempt 1](https://github.com/thzthix/cart-readback/actions/runs/42617340271)
executed commit `5783fb87199acc6de3f31291ff94dc2c80f626c5`. Source fetch succeeded;
the probe returned UNKNOWN/exit 2 and the fixture job was skipped. The generic
receipt cannot establish whether zero or one POST began, a response arrived, or
cleanup failed after a valid response. This patch cannot reconstruct that past
outcome or claim a successful connection.

Failure receipts now retain only a fixed local phase: preflight, claim, connect,
credential, post-attempt, headers, body, or unavailable for the outer fallback.
A phase marks the local stage being attempted, not successful completion.
In particular, post-attempt is set before the native request call and proves
neither remote delivery nor acceptance. An already received exact integer HTTP
status (100–599, never bool) survives later validation/cleanup failure; it does not
establish a complete body, model or usage. Cleanup faults force UNKNOWN and drop
model/usage while preserving the prior phase/status with cleanup_failed:true.
No exception text, body/header data, credential facts, lengths or hashes are
added to failure output. These fields improve FUTURE diagnostics only.

At the executed/observability baseline, first-run/attempt/window/no-reset guards
and request were unchanged. Run 1 remains spent forever. The local run-2
proposal above grants no provider authority. The operator path below is
historical, not permission to try the spent observability route live.

## Historical compatibility concern and proposed field removal

The [Gemini 3.5 migration guide](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5)
says to remove candidate_count for 3.x, while the generic reference still lists
candidateCount with default 1. The executed canonical body included candidateCount
1. This documentation conflict is NOT proof that 1 was rejected or the cause of
the UNKNOWN outcome. The observability patch deliberately leaves that payload
unchanged. The local run-2 candidate proposes only that field removal, as disclosed above.
It still requires separate explicit approval and never reopens the spent run-1
route.

## Historical operator path; route is spent

1. Review the exact final draft commit and source hashes. In the existing
   registered **Offline application checks** manual workflow, select branch
   `feat/64-disabled-connectivity-diagnostic` and mode `gemini-connectivity`.
   Supply that exact 40-hex reviewed commit and absolute UTC epoch start/expiry,
   with a positive window of at most 600 seconds. This is a future separately
   approved operation, not a dispatch performed or authorized by these docs.
2. One Ubuntu 24.04 job, at most two minutes, checks trusted GitHub context and
   fetches only the standalone probe from the fixed GitHub Contents endpoint at
   that revision. A literal SHA-256 pin is checked before any execution. Only
   this GET step receives the builtin token, with contents:read; no checkout,
   setup/install, cache, upload or semantic-asset materialization.
3. Only the final guarded step receives `GEMINI_KEY` through step environment.
   The probe rechecks context, source hash and window; creates an exclusive local
   claim; then borrows the sole key and performs one fixed Google POST. No key is
   placed in arguments, shell interpolation, source, files, logs or result text.

The existing fixture job/default remains offline and unchanged apart from the
mode selector and moving its existing cancellation group to job scope. It is not
run as part of diagnostic mode. The workflow remains manual-only. Testing the
reviewed draft branch does not require merging or changing another draft PR.

## Historical run-1 bounded trust and first-attempt fence

The trusted context binds repository `thzthix/cart-readback`, numeric repository
1443556432 and owner/actor 95135403, triggering actor thzthix, workflow_dispatch,
the one draft ref and exact application-checks workflow_ref. Both github SHA and
workflow SHA must equal the separately reviewed 40-hex input. Run number and
attempt must both be exactly one. The diagnostic uses one fixed repository-wide
concurrency group without cancellation, no matrix or alternative activation path.

This relies on the reviewed GitHub-hosted workflow/runner and trusted control
plane with no deletion, recreation, rename, rollback or counter reset. Under
that explicitly limited assumption, the existing workflow's first-run counter is
the cross-run burn. It is not universal attestation, a general persistent ledger
or proof of externally verified approval/account facts. Numeric workflow ID is
not an additional enrollment service here.

**Any first workflow run consumes this path**, including offline mode, failure,
cancellation, timeout, skipped diagnostic or unknown result. Never trial-dispatch,
rerun, change key/model/branch, renew the window, replace the workflow or reset
history to obtain another attempt. The local mode-0600 exclusive claim remains
in the same runner temporary directory and is never deleted for retry. It is not
exported/restored and does not make ephemeral hosted storage durable.

## Historical run-1 public request and unchanged response policy

- Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`.
- Public prompt: `Synthetic connectivity diagnostic. Reply READY.`
- Canonical request SHA-256: `1d5aeeb73cc4fa2225e99bd1bdccd5a963251e00e1f7cd9f6561489b980f95f8`.
- One candidate, temperature 0, MINIMAL thinking, requested maxOutputTokens 32.
  Accepted local observations require answer plus thoughts at most 32. This is
  not proof of an externally enforced billing cap. Conservative reference bounds
  remain 1048576 input / 2048 output; they are not an invoice or account allowance.

The standalone standard-library client uses direct fixed-host verified TLS
(minimum TLS 1.2, key logging disabled), no proxy discovery, redirects, automatic
reconnect, retries, tools, streaming, count/cache/file calls or model fallback.
It checks the remaining absolute/monotonic deadline before and after I/O. Accepted
headers are bounded and strictly framed; response body is at most 16 KiB.

Only enum status, exact validated model and bounded integer usage are emitted,
after synchronous cleanup. Optional omitted thought usage is zero only when the
reported total exactly agrees. Optional TEXT-only modality counts must match
aggregates; a bounded valid-base64 thoughtSignature is discarded. Unreviewed
fields do not obtain validated model/usage. A complete bounded, correctly framed
HTTP 200 with unsupported schema emits only HTTP_200_UNVALIDATED/http_status 200,
with no model, usage or text claim; it exits nonzero and is not inference success.
Framing, truncation, timeout and cleanup failures remain UNKNOWN without that
contact receipt. Text, responseId, headers, raw errors, project data
and key are never printed. RESPONSE_VALIDATED means this response satisfied the
local wire schema, not semantic quality, application integration, verified Free
eligibility or actual zero charge. Non-200, late/ambiguous transport and interrupted or failed cleanup are UNKNOWN;
unsupported schema receives only the non-success contact receipt above. No retry.
A missing final receipt is never success and must be treated as UNKNOWN.

The 20-second monotonic admission deadline cannot prove hard OS/DNS/socket or
remote cancellation. The hosted two-minute job timeout is the outer attempt
bound; stopping it cannot undo provider work. Python cannot erase every immutable
string or inherited environment copy. The trusted runner may retain memory,
logs or a killed process outside this best-effort redaction/cleanup guarantee.

## Verification and remaining gates

From repository root, using already available reviewed development tools:

```
python -m unittest discover -s cart_readback/tests -p test_gemini_connectivity_diagnostic.py -v
python -m compileall -q cart_readback/scripts/gemini_connectivity_diagnostic.py cart_readback/tests/test_gemini_connectivity_diagnostic.py
```

Tests use invented hosted context, synthetic keys and fake sockets only. They
ban real socket/default HTTPS construction, exercise real client code and the
actual inline fetch step, and check the source pin and final-step-only key binding.
Earlier fake-framework test counts are historical, not counts for this rewrite.
No provider/account/billing/hosted execution pass is claimed. Full integrated
application aggregate remains NOT_RUN because protected semantic assets were not
materialized. Actual dispatch requires the operator's final external facts and
approval; app integration, semantic evaluation, PayPal and deployment are separate.
