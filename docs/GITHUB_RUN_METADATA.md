# Unselected authenticated GitHub run metadata

Issue #66 adds a real fixed-host HTTPS reader, exercised only with synthetic
credentials and fake sockets. Nothing selects it: no workflow, dispatch, CLI,
Service, database, provider prepare/run, or existing diagnostic is changed.
There is no dependency on draft #65. The three added paths are
`cart_readback/cartreadback_app/github_run_metadata.py`, its same-named test
module under `cart_readback/tests/`, and this document.

## Contract and smallest read boundary

A separately trusted host supplies a `RunEnrollment` and an explicit ephemeral
credential handle to `GitHubRunMetadataReader`. Construction performs no I/O.
The handle is a trusted, nonblocking callable returning a token. It must not
discover, refresh, persist, log, or print credentials. The reader calls it once
per request, only after TLS succeeds, and drops its own token/header references
after sending. Python/HTTP libraries may retain transient copies; this is not
secure memory erasure. No credential source, setup, scope grant or storage is
provided. Ordinary environment tokens are ignored.

Enrollment has no defaults for numeric repository/workflow/actor IDs, reviewed
SHA or absolute window. It requires positive exact integers (not booleans), a
single `.github/workflows/<name>.yml` or `.yaml` path, a 40-character lowercase
commit SHA, exactly `refs/heads/main`, and an absolute `[not_before, expires_at)`
interval no longer than 86,400 seconds. It is frozen, has no renewal operation,
and is not auto-populated from API results. The host must preserve its original
externally established enrollment rather than re-enrolling a replacement ID or
extending a spent window. Creating a dataclass or matching JSON/hash does not
establish enrollment provenance, owner consent, or permission for any action.

One call to `read(explicit_run_id)` consumes that reader, including after failure
or interruption. Success requires three sequential authenticated GET requests:

1. `/repos/thzthix/cart-readback/actions/runs/{run_id}`
2. `/repos/thzthix/cart-readback/actions/workflows/{enrolled_workflow_id}`
3. `/repos/thzthix/cart-readback/actions/workflows/{enrolled_workflow_id}/runs?per_page=100&page=1`

Only `api.github.com:443` is supported. URLs are constructed from constant paths
and validated numeric IDs, never response URLs or credential values. The API
version is explicitly `2026-03-10`, as shown in current official documentation.
The token travels only in `Authorization: Bearer ...`. The component neither
creates tokens nor proves their granted scope; a future provisioner must provide
only the necessary read access. GitHub documents Actions repository read
permission for these resources. No user/profile, environment, secret, billing,
job log, artifact, approval, dispatch or write endpoint is queried.

The current run must have run number 1, attempt 1, `workflow_dispatch`,
`in_progress` with a present null conclusion, no pull requests, enrolled SHA,
`head_branch=main`, and exactly `<enrolled workflow path>@main`. Repository and
head repository must both match the enrolled numeric ID and fixed full name,
with `fork=false`. Both actor and triggering actor must match the enrolled
numeric actor ID. API run/workflow URLs must match the fixed resources. Workflow
metadata must match the enrolled numeric ID/path and be active. This narrow
documented path form is deliberately fail-closed on unverified API variations;
it has not been checked against a live response.

Created/started/updated UTC timestamps must satisfy
`not_before <= created <= started <= updated <= current time`; every I/O phase
and final return rechecks the absolute window. The complete unfiltered history
must have exact integer `total_count=1`, a one-entry list, and the same validated
run identity/status/timestamps. Any other run, outcome, missing entry,
inconsistent projection, pagination `Link` header (even empty), or redirect
location refuses the observation. No filter hides older or contrary records.
An unstable current/history snapshot fails closed instead of retrying.

## Transport, time and cleanup

The production path builds `SSLContext(PROTOCOL_TLS_CLIENT)`, loads the trusted
host's default CA store, requires certificate/hostname verification and TLS 1.2
or newer, and advertises HTTP/1.1 only. It avoids `create_default_context` because
that helper can create an ambient `SSLKEYLOGFILE`; key logging is disabled before
connection. It does not inspect proxy variables, use CONNECT, redirect, retry,
reconnect, refresh a token, or try another address.

All three requests share a 20-second monotonic deadline and the absolute window.
DNS wait/connect/TLS each use at most 3 seconds and socket reads at most 5 seconds,
capped by the remaining shared budget. Raw status/header/body reads refresh the
remaining timeout before each bounded read, including chunk framing. The reader
accepts HTTP/1.1 200, at most 64 headers/16 KiB total, bounded ASCII field lines,
one uncompressed JSON body framed by either Content-Length or strict chunking,
and at most 256 KiB per response. Duplicate headers, ambiguous framing, chunk
extensions/trailers, unsupported encoding, invalid UTF-8/JSON, duplicate JSON
keys, nonfinite JSON constants and nesting beyond 12 levels fail closed.
Ignored upstream fields are bounded and parsed but never projected or logged.

Platform DNS cannot be force-cancelled by Python. A resolver-only daemon waits
behind one process-wide in-flight slot; a timed-out/interrupted caller never
continues TCP/TLS or credential use. The daemon can only resolve the constant
host, sees no token/socket/TLS context and cannot make an HTTP request. If it is
stuck, later resolutions fail closed instead of accumulating workers. It may
outlive the caller until the operating system resolver returns. This is not
hard cancellation of OS DNS work. Host Python, CA loading, scheduler, clocks,
credential callback and cleanup must behave normally; arbitrary blocked trusted
host code is not made interruptible by a socket timeout.

Responses and connections close on success, ordinary failure or interruption.
Cleanup attempts both resources even if one close fails. Ordinary failures expose
only `GitHub run metadata unavailable; no retry.` No API error body, token,
response URL or raw exception is logged/returned. Process cancellation propagates
after cleanup. Closing a connection is not proof of remote cancellation.

## Explicitly unresolved integration gates

`GitHubRunMetadata` is an immutable narrow queried-run projection. It is not
fabricated diagnostic evidence, a serialized admission record, an approval,
permanent eligibility proof, or attestation that the caller is executing inside
that run. No existing fabricated-only diagnostic consumes it. A future reviewed
integration must keep authenticated observations separate from fabricated tests,
bind the trusted executing job/host and the exact reviewed workflow bytes, and
revalidate at its actual side-effect boundary. Private test seams, monkeypatches
and a compromised host can fabricate observations and must never count as live
origin evidence. This implementation is not a security boundary against its
trusted Python process, administrator, clock or CA store.

GitHub history is deletable and can be retained for a finite period. A one-entry
response, even with run number/attempt 1 and a fixed workflow ID/window, cannot
prove permanent non-use or retirement. An externally provisioned durable
retirement/one-shot authority is still missing; another reader instance does not
create it. There is no owner-grant verifier, compute allowance proof, current
provider Free/account/project/key binding, billing check, or application dispatch
gate here. Do not infer any of these from API authentication, hashes, JSON,
historical observations or tests. Private Environment reviewers/features are not
assumed. Activation, secure provisioning and any live request remain separate
reviewed and authorized work.

## Offline verification

From repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cart_readback python -m unittest discover -s cart_readback/tests -p test_github_run_metadata.py -v
ruff check cart_readback/cartreadback_app/github_run_metadata.py cart_readback/tests/test_github_run_metadata.py
ruff format --check cart_readback/cartreadback_app/github_run_metadata.py cart_readback/tests/test_github_run_metadata.py
python -m py_compile cart_readback/cartreadback_app/github_run_metadata.py cart_readback/tests/test_github_run_metadata.py
```

Tests feed raw HTTP through the actual response parser, privately replace the
connection constructor, and separately check the production fixed-host TCP/TLS
constructor using mocks. Real socket/DNS entry points are blocked in reader
tests. Resolver tests patch DNS and synchronize their temporary worker cleanup.
Same-process repeats verify the patch/HTTP/TLS/socket/environment globals are
restored. These are offline regression checks, not live TLS/API acceptance or
proof of any account, permission, provider or buyer outcome. The full application
aggregate is not run for this standalone component under the current read
boundary; focused checks do not certify the integrated application tree.

## Primary sources

- [GitHub workflow-run REST API](https://docs.github.com/en/rest/actions/workflow-runs): current run, unfiltered workflow history, pagination, attempts and read permissions.
- [GitHub workflow REST API](https://docs.github.com/en/rest/actions/workflows#get-a-workflow): workflow ID/path and state.
- [GitHub Actions contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts): run number, attempt, SHA and ref distinctions; context is not supplied by this module.
- [Managing workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs): runs can be deleted; observed history is not a permanent retirement ledger.
- [Python 3.11 HTTP client](https://docs.python.org/3.11/library/http.client.html), [TLS](https://docs.python.org/3.11/library/ssl.html), and [socket timeouts](https://docs.python.org/3.11/library/socket.html#notes-on-socket-timeouts): transport mechanics and platform/time limitations.
