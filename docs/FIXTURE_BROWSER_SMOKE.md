# Public fixture UI render smoke (#90)

## Prepared, not executed

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
