# Public fixture UI render smoke (#90)

## Scope and verification limits

This separate manual-only workflow is a **render-only public synthetic fixture**.
It does not open the authenticated Gemini Service viewer, reuse an analysis
record/database, invoke a provider, or test checkout/PayPal. It establishes no
customer benefit, model correctness, billing fact, or genuine inference.
The existing app5 workflow and production files are unchanged.

Source preparation and injected tests are not an actual browser run. Only an
authorized hosted run can produce browser-rendered screenshots. A successful
receipt means the automated assertions passed; a person or separately assigned
reviewer must still inspect the four PNGs before reporting visual findings.
No native human keyboard, screen-reader, full accessibility or real-device
validation is supplied by this smoke.

## Separate release and run gates

1. Independent review fixes these four new files and exact immutable head.
2. Coordinator obtains applicable publication/merge authority. Keep this issue
   separate from app5 source capture and other workflows.
3. The workflow must be present on the **default branch** for manual dispatch
   registration. It deliberately runs only for `refs/heads/main`. Preparing a
   draft branch is not registration, dispatch, or a completed run.
4. Before a future dispatch, the operator separately confirms the user's
   authority for this exact run and that standard private-repository Actions
   compute is available within the included **$0** allowance. Do not use paid
   upgrade/larger runners or assume an input checkbox proves billing eligibility.
   If included capacity cannot be verified, do not dispatch.
5. Supply the exact independently reviewed merged workflow SHA. Repository,
   owner, fixed actor ID `95135403`, repository ID `1443556432`, main ref,
   SHA equality and first-attempt guards establish provenance,
   **not authorization or proof of $0 cost**. Only attempt 1 is accepted; a
   failed run does not authorize a new dispatch or an API/provider retry.
6. Inspect actual job setup/image version, sanitized receipt and all PNGs.
   Report missing/failing stages honestly. No install, security relaxation,
   alternate protocol, tunnel or external browser fallback is supported.

## Exact source and credential boundaries

The workflow downloads exactly six allowlisted files from GitHub's contents API:
production `viewer.html`, `viewer.mjs`, `viewer-core.mjs`, `core.mjs` pinned to
`4f74a95c5103fddf8b7d881cd69401ad4cb86076`, plus the two QA Python files from
immutable `github.sha`. All SHA256 digests are checked **before executing the
helpers**. The helper repeats the four UI checks before starting a server.
There is no full checkout, Git credential persistence, package installation,
cache, protected prompt/evaluation/gold/model-output retrieval, database or
real application Service import. Helper pins live in the workflow; there is
no circular workflow-self hash. Updating a helper requires updating its pin
and obtaining another fixed-artifact review.

The builtin GitHub token is scoped to `contents: read` and supplied only to the
fetch step. No repository/provider Secret is referenced. The offline test and
harness processes start under `env -i` with explicit minimal environment values
and fresh HOME. Driver/browser get a constructed whitelist and disposable
HOME/profile, not inherited GitHub runtime credentials, tokens or proxy values.
The artifact action uses GitHub's builtin runtime authentication separately:
this is **not credential-free everywhere**. Chrome flags cannot prove absence
of every browser background request. The narrower claim is no app/provider
endpoint or credential path in this fixture, not universal network isolation.

## Lifecycle and checks

A standard `ubuntu-24.04` hosted VM owns server, driver and browser in one job.
The helper expects `/usr/bin/google-chrome` and
`/usr/local/share/chromedriver-linux64/chromedriver`. Missing binaries,
unrecognized versions or mismatched major versions fail closed. The rolling
runner inventory is documentary availability, not a guarantee about a future
job. Receipt records actual browser/driver versions and runner image version.
No `--no-sandbox`, `--disable-web-security`, TLS bypass, wildcard driver
allowed-IPs, arbitrary target URL, caller-provided fixture, UA spoof or known
mobile-device profile is accepted.

The server binds an ephemeral IPv4 loopback port. It serves exactly `/health`,
`/viewer`, three module paths and `/gemini-viewer/api/bootstrap`. The bootstrap
is explicitly invented public data. It intentionally has no redemption,
capability, cookie/session authority, analysis or payment route. Unsupported
methods, queries, paths, host and body-bearing GETs are rejected. A pinned
inline-script/style hash CSP is used, without `unsafe-inline`. An exact 200
owned marker precedes navigation. HTTP bodies/socket waits, readiness waits,
WebDriver operations, request count and job duration are bounded. Port-reserve
races or incompatible runners fail; there is no retry on a different host.

Four fresh sessions cover review and blocked-UNKNOWN states, each at 1200 and
320 CSS pixels. ChromeDriver `mobileEmulation.deviceMetrics` explicitly sets
`touch=false`, `mobile=false`, `pixelRatio=1` and height 2400. This is a
**non-touch emulated viewport**, not a physical phone. `innerWidth`,
`innerHeight`, DPR, document horizontal overflow and PNG IHDR dimensions must
match; outer window width is not accepted as viewport evidence. DOM assertions
check source/result headings, finite coordinates and horizontal viewport
containment, positive layout geometry (columns versus stack),
public-source label, UNKNOWN outcome, blocked zero-results/accounting UNKNOWN,
and absence of action controls. Screenshot artifacts are viewport captures,
not a claim that every document pixel or all accessibility states were covered.

Each ChromeDriver starts in its own OS session/process group. Session deletion,
driver/group terminate/wait/kill, server shutdown/close and profile cleanup have
separate `finally` paths. Forced termination, a lingering owned group or uncertain
cleanup raises failure and cannot produce a passed receipt or success marker.
Group signaling does not prove absence of descendants that detach themselves. A failed delete cannot skip process or
server cleanup. Graceful cleanup is tested; hard OS/job cancellation cannot
be guaranteed to run Python finalizers. The hosted job's ephemeral VM lifecycle
is an additional boundary, not an application cleanup assertion.

Only four fixed PNG filenames and `receipt.json` may be uploaded, retained for
three days. No profile, cookies, session ID, raw WebDriver log/error, private
launch URL or provider body is an artifact. A partial failure receipt remains
failed and must not be described as complete visual validation. Even successful
synthetic pixels do not establish authenticated viewer or provider success.

## Offline verification

From a scratch directory with the four exact source files staged as `ui/`:

```sh
PYTHONPATH=/path/to/candidate/cart_readback/ui python3 -m unittest -v test_fixture_browser_smoke
python3 -m py_compile /path/to/candidate/cart_readback/ui/fixture_browser_smoke.py /path/to/candidate/cart_readback/ui/test_fixture_browser_smoke.py
```

Tests inject fake WebDriver/process seams; the HTTP test starts only a tiny
ordinary loopback fixture server. They never launch Chrome. Public solid-color
PNG bytes are unit-test fixtures, not screenshots. Negative controls cover
source mutation/missing/symlink, wrong readiness, malformed JSON/session/PNG,
viewport/overflow/action/state mismatches, and setup/navigation/render/delete
failures with cleanup. A separate review caught v1 falsely passing after forced
driver termination; v2 reproduces and rejects that invariant using injected
process-group signals. No real browser leak was observed or claimed. The source check explicitly skips if four files are not
staged; a skip is not a verified source manifest. The hosted offline runner
requires successful tests, a positive test count and zero skips, failing closed
on empty discovery or skipped coverage. The final local suite observed 20/20
passing with zero skips; that count is evidence, not a hardcoded runner gate. Use only an already available
Ruff executable with the repository config; no installation is required here.

## Primary sources (checked 2026-11-10)

- [Standard hosted job VM and rolling images](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
- [Official Ubuntu 24.04 inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
- [ChromeDriver setup](https://developer.chrome.com/docs/chromedriver/get-started)
- [ChromeDriver mobile emulation](https://developer.chrome.com/docs/chromedriver/mobile-emulation)
- [ChromeDriver security](https://developer.chrome.com/docs/chromedriver/security-considerations)
- [Stable WebDriver recommendation](https://www.w3.org/TR/2018/REC-webdriver1-20180605/)
- [CI same-job server pattern](https://playwright.dev/docs/test-webserver) (no Playwright dependency)
- [Pinned official upload-artifact commit](https://github.com/actions/upload-artifact/commit/330a01c490aca151604b8cf639adc76d48f6c5d4)

## Private diagnostic candidate: finite failure stages

This local-only observability proposal does not authorize publication or another
hosted run. The prior failed hosted render's cause remains unknown; new source
cannot reconstruct an unavailable old receipt or prove browser compatibility.

Once the receipt directory exists, `diagnostics.version=1` records only fixed
stage/scenario/status/category enums. `primary_failure` is the first failed
non-cleanup stage; later cleanup failures cannot overwrite it. `cleanup` records
separate outcomes for session, owned process group, profile, server shutdown,
server close/join and temporary-directory cleanup. A cleanup-only failure leaves
`primary_failure` null but has a failed cleanup entry and overall failed status.
`last_stage` is merely the last entered stage, often cleanup, not the root cause.

Stages distinguish setup, server setup/readiness, driver start/readiness,
session creation/configuration, navigation, render readiness, measurement,
PNG retrieval/validation and PNG write. Categories are a closed type mapping:
`check_failed` (unknown checks), fixed internal `check_<code>` values such as
`check_version`, `check_session`, `check_webdriver`, `check_png`, and `timeout`, `io_error`, `protocol_error`, `invalid_data`,
`unexpected_exception`, `unexpected_base_exception`, or `cancelled`. They do
not include exception text/args/type names, arbitrary W3C error strings, paths,
URLs, session IDs or browser logs. No detailed provider or Chrome error is
inferred from a broad category.

All failures still propagate from `run()` after separately attempted cleanup;
primary and cleanup facts survive in the receipt even if Python's propagating
exception is replaced by a later cleanup exception. The CLI emits a fixed failure marker plus a bounded diagnostic summary
and exits nonzero for ordinary errors, unexpected BaseException,
KeyboardInterrupt and SystemExit; no raw traceback/message is emitted by it.
Forced/uncertain process cleanup still prevents a successful receipt. A partial
run may retain previously verified public PNGs while remaining failed overall.

Preflight failures before `run()` or failure creating/writing the receipt itself
cannot promise a durable diagnostic receipt. Hard OS cancellation and detached
processes retain the earlier limitations. Stage reporting is not a guarantee of
cleanup completion or a workaround for the original rendering failure.

Local regression coverage retains all original 20 tests, with a precise
session-ID/private-sentinel assertion replacing the overbroad prohibition of
the word `session` (now a safe stage label). Additional injected tests cover
primary plus multiple cleanup failures, one PNG before a later scenario fails,
write/setup failures, hostile exception strings and safe cancellation exits.
Only the two helper hashes change in the workflow; source pins, fetch/run
guards, browser flags, HTTP routes/timeouts and render assertions are unchanged.

Failed runs also emit one `PUBLIC_FIXTURE_FAILURE_SUMMARY` JSON line to job
stdout so artifact availability is not required to read the safe diagnosis.
Only allowlisted primary stage/category/scenario, failed cleanup-stage enums,
a 0–4 saved-PNG count and `receipt_write` status are included. Missing primary
failure is `unavailable`, not an invented cause. Receipt-write failure emits
`receipt_write: failed` from the in-memory diagnostic state and remains nonzero.
No raw receipt, version payload, exception, URL or session identifier is printed.


Receipt publication is staged outside the fixed artifact upload paths: complete
serialization/write/close precedes atomic replacement of `receipt.json`. A
write or replacement failure triggers bounded invalidation of the final and
staging paths, safe stdout `receipt_write: failed`, and nonzero completion.
Failure to invalidate is separately `receipt_invalidation: failed`, without raw
filesystem errors. Atomic operations can fail after taking effect, and deleting
or overwriting can also fail; no absolute filesystem guarantee is asserted.

Consequently a successful check receipt has `checks_status: passed`,
`status: pending_job_conclusion`, and `job_conclusion_required: true`, never a
standalone overall `passed`. Even a residual file after ambiguous replacement
cannot certify the run. Read the receipt together with the matching workflow
SHA, artifact/run metadata and actual successful job conclusion. Failed checks
or cleanup remain failed, with `checks_status: not_confirmed`. Individual earlier
PNG checks can still have passed in a partial run.

Historical observation correction: the original failed hosted run reported one
uploaded file and its compressed size. The ZIP content was not readable, so its
filename and the number of saved PNGs were not verified. Actual pixels observed
remain zero; saved PNG count is unknown, not proven zero. New injected unit-test
PNG counts are separate synthetic test observations, not evidence about that run.

## Issue #94: bounded operation and HTTP diagnostics

The latest approved render failure was localized to `session/check_http` in
`review-wide`, before navigation, with saved PNG count zero in its safe summary.
That observation alone did not distinguish session creation from timeout
configuration, or non-200 response from an oversized response. This change
only adds discriminating metadata; it neither fixes browser startup nor proves
the cause. No additional hosted experiment is authorized by these source files.

Known check failures during session setup now carry a closed `operation` label:
`session_create`, `session_timeouts`, or `version`. Other/unrecognized exceptions
remain `unavailable` rather than being relabeled by their message. HTTP check
failures carry `http_kind: non_200` or `oversize`, with `http_status` only when it
is a plain integer from 100 through 599. Boolean, string, out-of-range and hostile
values become `unavailable`. A non-200 response takes precedence if its body is
also oversized; the oversized non-200 body is not parsed.

For a bounded non-200 JSON body, only `value.error` is matched against an exact
closed list of standard WebDriver errors. Examples are `session_not_created`,
`invalid_argument`, `timeout`, and `unknown_error`; unrecognized labels become
`unavailable`. No message, stacktrace, URL, session ID, data object, response body
or arbitrary type name enters receipt or stdout. This classification is not a
substring-based causal inference. An allowed error label still does not prove
why Chrome failed or justify changing sandbox/security flags.

The four safe metadata fields are validated again when recorded and printed.
Only exact owned `SmokeFailure` instances expose their sanitized fields;
unrecognized subclasses do not have their accessors inspected. Source files,
request limits/routes, Chrome arguments, assertions, atomic pending receipts,
cleanup invariants and manual run guards are unchanged. The workflow diff is
only the two QA helper hash pins. Offline tests capture fake failure-summary
stdout inside tests, while preserving the normal unittest results; an offline
negative control must not look like a live hosted render failure.

## Issue #96: preserve transport-timeout operation

Run 42919263062 on 2fa2cb46ce5701e97e7ceaf01f2f559552ce267d
passed 39 offline tests, then reported session/timeout in review-wide,
saved PNG count zero and no reported cleanup failure. The prior operation
wrapper handled owned check failures only. Injected TimeoutError at either
session creation or timeout configuration produced identical operation-less
diagnostics; the actual run cannot retrospectively distinguish them.

A known TimeoutError inside the operation context is now replaced with an owned
OperationTimeout carrying only the closed operation label. Diagnostics retain
the existing timeout category. No external exception text, args or attributes
are inspected. Other exceptions and cancellation retain their previous handling.
Primary failures remain separate from cleanup failures.

Fake transport tests cover both session operations, hostile timeout objects and
unrelated errors/cancellation. They simulate a delayed transport's timeout
exception, not real elapsed-time or browser behavior. All 39 previous tests are
retained. The three-second HTTP timeout, browser flags, readiness, routes,
source pins, cleanup and manual execution guards are unchanged. Only the two
helper hash pins change in the workflow. This repairs diagnostics, not the
unexplained browser failure, and adds no authority to launch or retry a run.
