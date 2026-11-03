# Offline Responses wire boundary — issue #11

This is a locally tested wire boundary, **not live application integration**.
`OfflineResponsesAdapter` is never selected by the server or CLI. The default
fixture and frozen v1 prompt artifacts remain. Issue #15 now adds the service
reservation/claim/attachment lifecycle for explicitly injected offline tests; see
[analysis lifecycle](ANALYSIS_DISPATCH.md). The server/CLI do not select it. No network transport, credential lookup, live runner, account access,
API call, provider acceptance, inference-quality or paid-runtime result is supplied.

## Scope and use

The adapter accepts one exact source object (`source_id`, positive integer
`revision`, SHA-256 of exact UTF-8 `text`, text) and one/two typed conditions with
stable unique IDs and unique kinds. It copies/validates these before transport.
The immutable configuration binds explanation language `en`/`ko`, requested and
allowed returned model `gpt-6-luna`, and bounded deadlines. This reviewed requested
ID is not a claim that the account has access or that a dated snapshot exists.
There is no automatic upgrade, provider fallback, prompt repair or retry.

`build_request` returns exact intended UTF-8 request bytes without dispatching.
`observe` returns validated results and host-recorded configuration/input digests,
source revision, requested/returned model IDs, response/request IDs and usage.
`propose` returns the same validated result array for the existing adapter seam.
Neither method alone attaches results to application state. The service now uses
its durable current-input/config/generation fence before attachment in explicitly
injected offline tests.

Only explicitly injected transports are usable. Tests use **fabricated envelopes**
from authored synthetic inputs, not recorded or asserted vendor behavior. There
is no secret environment access, SDK dependency or production HTTPS implementation.
Separate release schema verification uses the already-reviewed dev-only
`jsonschema` 4.26.0 from the existing prompt preflight. The runtime and backend
unit tests are standard-library-only; no new dependency is introduced.

## Versioned prompt and schema

`cart_readback/prompts/v2-wire/` is a separate release. Each A/B/C system file has
the same mechanical envelope edit: ask for one object with sole key `results`
containing the ordered array. Only B is used by this boundary. This is not a new
A/B/C execution or evidence that B wins. The user template is similarly explicit.
All source evidence/Unicode/no-tools/no-payment rules remain intact. The wire
schema is a weaker shape projection: object root, required fields, no extra
properties, no local conditional composition or string regex/length assertions.

Exact shipped asset hashes are in `v2-wire/manifest.json`; its hash is pinned in
`inference_config.py`. The adapter verifies all asset bytes and the unchanged local
schema before dispatch. Metadata binds these hashes, adapter/parser/validator/wire
versions, model/language/settings and a canonical config digest. Metadata reads
return copies. No placeholder hash or model-echoed config identity is accepted.

After strict wire parsing, the adapter unwraps once and uses the unchanged local
`validate_proposal`, plus exact input order. With the validated source and condition
bounds this enforces every local result-schema constraint. A separate release check cross-checks the
weaker wire projection and full local schema using the existing dev validator.
No reordering, normalization, quote matching, span repair or first-occurrence guess
is performed. Offsets remain decoded Python Unicode code points. A syntactically
valid false cable match with a verbatim no-cable quote can still pass: this is a
known semantic limitation, covered by an authored counterexample test.

## Transport, parser and failure contract

The fixed intended endpoint is `https://api.openai.com/v1/responses`. The request
uses instructions, one user input, strict `text.format` JSON schema, reasoning
`none`, no tools/history, `store:false`, `background:false`, `stream:false`, and
2,048 maximum output tokens. Temperature/top-p/seed are omitted, not deterministic.
No price, baseline/gold, customer, cookie, order or payment authority is sent.
Catalog text remains inert serialized data even if it contains template markers.
The generation payload requests `prompt_cache_options:{"mode":"explicit"}` and
omits all `prompt_cache_breakpoint` fields. The [official cache guide](https://developers.openai.com/api/docs/guides/prompt-caching)
describes explicit mode without breakpoints as making no cache writes. This is an
intended request policy, not tested provider acceptance or a zero-retention claim.

A future real transport must implement TLS verification, fixed-host routing,
no redirects, no hidden retries, connect/read timeouts using the passed absolute
monotonic deadline, safe request-ID extraction, and response resource closure.
`WireResponse.close` permits resource cleanup even on an early status failure;
body iterators are also closed when possible.

One overall caller deadline covers preparation, transport, body reading, parsing
and validation. The waiting caller returns a timeout even if an injected body
blocks. Python cannot forcibly terminate a blocked thread: that worker may remain
in flight. The adapter instance is permanently blocked after timeout and cannot
redispatch/overlap a second call. This is **per-instance**, not global concurrency
or durable cancellation/accounting. It is not proof that a remote request stopped
or was free. A production transport and durable run ledger are separate gates.

Request: 64 KiB. Envelope: 128 KiB / depth 32. Extracted wire: 64 KiB / depth 8.
The separate provider parser rejects malformed UTF-8, duplicate keys, nonfinite
numbers including exponent overflow, trailing prose/fences, lone surrogates and
C0 controls. Escaped LF/TAB are allowed for exact multiline quotes; explanations
and IDs still reject them through field validation. Inbound HTTP limits are not
changed. Provider status must be completed, with no error/incomplete details, the
expected model, one completed assistant message and one nonblank output text.
Tool/action outputs, refusals and multiple text messages are blocked, never run.

Error mapping (sanitized messages, no provider error/header echo):

| Failure | Adapter code |
| --- | --- |
| Unsupported config/assets, transport exception, non-200 status | MODEL_UNAVAILABLE |
| Overall/connect/read timeout | MODEL_TIMEOUT |
| Refusal content | MODEL_REFUSED |
| Incomplete status/details/message or missing/blank text | MODEL_INCOMPLETE |
| Unexpected model/action/shape/order/span or strict JSON failure | INVALID_PROPOSAL |
| Oversized request, missing/invalid usage/request/response identity | MODEL_BUDGET_EXCEEDED |

For an otherwise validated completed proposal, missing/invalid usage or response
identity permanently blocks the instance. A missing request ID blocks before body
processing. Earlier HTTP/refusal/incomplete/proposal failures preserve their
primary diagnostic and do not pass through usage validation. Their attempted-call slots and unknown-usage stop policy are now durable in the
offline service lifecycle. Real charge accounting remains an unimplemented live
gate.
No synthetic all-unknown success is fabricated. The service catches and sanitizes these adapter codes when explicitly injected
for offline tests. No failure creates a snapshot or authorizes payment.

## Mandatory live-enable gates

Before a separately authorized genuine run:

1. Review the offline analysis reserve/claim/CAS attachment fences, pending state
   and restart behavior against the actual future transport. Offline tests now
   cover these local properties; they do not prove vendor cancellation.
2. Obtain bounded provider/data/call/token/spend authorization and a securely
   approved credential reference. Never infer permission from a key's existence.
3. Implement and review real input token counting (not characters/4), input cap,
   durable call/spend reservation, attempted-call records including refusals and
   unknown timeout charges, and stop/reconciliation behavior. The offline service
   now supplies durable attempted-call slots, valid observation usage and an
   unknown-usage breaker, but not real token/spend accounting. `max_output_tokens` is not an input or dollar cap.
4. Implement/review the real transport and approved cache/data controls. Confirm
   official schema acceptance and actual returned model/usage behavior on a bounded
   synthetic smoke run. `store:false` is not a zero-data-retention guarantee.
5. Run fresh separately labeled semantic evaluation and same-source buyer baseline
   comparison. Keep mixed real-AI/synthetic-catalog/simulated-payment labels clear.

Issue #10 is separately owned dispatch infrastructure, not automatic satisfaction
of analysis/live-enable gates. No price, quality, latency, runtime, payment or
customer-benefit claim follows from this offline PR. Rollback of the adapter and the later service lifecycle must preserve unknown
accounting history; see the lifecycle document.

## Verification

From `cart_readback/`, run `python -m unittest discover -s tests -p
 test_responses_adapter.py -v` (without the line break). Use the root README's
existing aggregate checks against the final assembled revision. Preserve v1 prompt
checksums, data/gold and original preflight bytes. Compare a temporary fresh prompt
preflight with the frozen receipt instead of rewriting unrelated files. The PR
records actual commands/exits/counts, frozen hashes and separate-worker findings.
