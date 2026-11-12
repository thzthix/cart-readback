# One-shot sandbox create acceptance probe (#101)

This separate POSIX host tool tests at most one OAuth and one Orders create,
not Service integration, buyer approval, capture or a working checkout. It uses
only the reviewed main transport from
`43150d6846b50a94a9350c3df33294b0b87feb47`. It never selects the offline adapter
or changes its guard. There is no Gemini call, live-money endpoint or fallback.

`cart_readback/scripts/sandbox_create_acceptance.py` has explicit `prepare` and
`run` phases. Default behavior does not execute either phase implicitly.
Prepare accepts the approved existing app client ID and merchant ID, not a secret.
Use an existing private owner-only directory (0700) as the permanent attempt
namespace. Never replace it, delete its files, or choose another directory to
retry an uncertain operation. This tool cannot stop a host owner doing that;
its one-attempt guarantee applies to the retained namespace, not a remote account.

Prepare freezes one synthetic KB-UK-C2C item, USD79.00, quantity one, no additional
charges, a UUIDv4 request ID, public app/merchant bindings and a 15-minute expiry.
The private 0600 plan is created exclusively and fsynced. It prints only a plan
hash and expiry, never account IDs. The exact hash identifies the approved plan.
A host approval must cover this existing sandbox app, merchant, synthetic data,
OAuth and single create scope. A local plan/hash does not provide authorization.

Run requires the same directory and exact plan hash plus an inherited read-only
FIFO descriptor >=3 containing bounded JSON `client_id`/`client_secret` values.
The secure launcher must provide the existing approved credentials privately,
close its writer after the JSON, and give the child sole read ownership. Do not
put secrets in command arguments, ambient environment, logs, files or chat.
The separately reviewed [hosted provisioning shim](HOSTED_SANDBOX_CREATE_ONCE.md)
is a narrow exception: GitHub injects three explicitly selected secrets into
that shim step only; it immediately removes them from the environment before
creating the launcher process and supplies credentials through the private pipe.
This is not ambient credential discovery. No credential
source or secure-store integration is automatically discovered by this tool.
The runtime's directory and credential pipe must belong to the current UID;
files and pipe must not grant group/other access. No credential persistence is
implemented. Python memory is not securely zeroized.

Before forking or credential borrowing, run writes/fsyncs an exclusive consumed
marker and its directory. Every subsequent attempt refuses that namespace.
Crash, fork failure, timeout, malformed response and missing result remain
UNKNOWN; no reset, create retry, alternate order or capture is provided. Private
ledger corruption fails closed. Storage durability still relies on a functioning
local filesystem honoring fsync. Same-UID hostile processes are outside the trust
boundary. A partial prepare file blocks rather than being repaired automatically.

Only the forked child imports exact hash-verified main modules from in-memory
source bytes, never cached bytecode. It constructs the explicitly network-capable
SandboxHttpsTransport with DirectSandboxConnectionFactory. The unchanged core
rejects configured proxies/trust overrides before borrowing credentials, fixes
verified TLS to the sandbox API host, and does no retry/redirect. Its strict
Content-Length-only response framing may reject genuine PayPal responses.

The child computes its exchange budget after constructing transport, rejects
one second or less remaining, and subtracts a one-second conservative margin
from the remaining plan window (maximum 20 seconds). It rechecks expiry before
and after credential borrowing. The parent waits at most 25 seconds, capped by
the remaining plan window, for a receipt then kills and
reaps its own child if still running. This is local process cleanup, not proof
of remote cancellation or that no order was created. OS process/fork/fsync/signal
operations have platform limits; no hard real-time wall-clock guarantee is made.

Raw provider bodies/headers, approval links and payer data are never printed or
persisted. A receipt contains only an allowlisted provider ID/status, HTTP status
and booleans for normalized evidence availability. It is always
PARTIAL_PROVIDER_OBSERVATION or UNKNOWN, never payment success. PAYER_ACTION_REQUIRED
is not buyer approval. Returned field availability is not equality verification
or permission to capture. Preserve a returned order ID for separately authorized
future reconciliation; this tool itself cannot perform GET or capture.

Run requires independent fixed-artifact review and separately authorized secure
host provisioning. It has not contacted PayPal. Tests use fabricated credentials,
fake exchanges and an owned fork; no real provider, browser or hosted compute.
CLI error output is generic BLOCKED_OR_UNKNOWN: inspect the private consumed marker
to distinguish a pre-dispatch refusal from an already-consumed uncertain attempt.
