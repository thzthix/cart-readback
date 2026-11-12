# One-use hosted sandbox create wrapper (#105)

The brand-new `.github/workflows/paypal-sandbox-create-once.yml` is manual-only.
Do not dispatch until the exact workflow revision is independently reviewed,
existing app/merchant and USD79 synthetic one-create scope are authorized,
secure provisioning is complete, and the public repository/standard runner
no-charge compute conditions remain verified.
This file does not establish those conditions or authorize a run.

GitHub maintains `run_number` for each workflow and increments `run_attempt` on
reruns. Both must equal 1, with exact repository, repository ID, main ref and
workflow path checks. Every later dispatch or rerun is rejected before secret
provisioning. A first failure, cancellation or nonsecret preflight failure spends
the only slot forever. Never rename, delete/recreate, reuse or replace this workflow
to obtain another slot. The fixed concurrency group never cancels an older run.
This is GitHub workflow-identity consumption, not a remote PayPal idempotency
promise or protection against a maintainer changing workflows/permissions.

Two sparse checkouts are used: immutable application revision
`75d5b7e3bafdecc1cfb322cfd6c19d49a0abd30a`, and the wrapper/test files from the
workflow's exact GitHub SHA. No protected evaluation/prompt artifacts are needed.
The official checkout action is pinned to its previously reviewed commit.
Permissions are contents-read only. No package installation or auto-trigger exists.

Python 3.11 or later is required before importing application code.
Offline tests must run positively with zero skips. Nonsecret preflight checks
workflow identity, configured proxies/trust overrides, system proxy discovery,
exact launcher/core hashes and an anonymous read-only pipe. Source verification
loads only the launcher, not provider application modules. Proxy/discovery errors
fail closed. No proxy or trust configuration is cleared or bypassed.

Only the dedicated provisioning step receives these selected GitHub Secrets:
PAYPAL_SANDBOX_CLIENT_ID, PAYPAL_SANDBOX_CLIENT_SECRET and
PAYPAL_SANDBOX_MERCHANT_ID. The trusted standard-library shim rechecks all nonsecret gates before reading
credential values, then pops all three and prepares one private per-run plan and passes bounded credential
JSON through an anonymous pipe to an isolated Python launcher process. Credentials
are absent from launcher argv/environment and never written to files or logs.
The shim's initial process environment and Python memory are not claimed securely
zeroized or inaccessible to trusted runner administrators. No credentials are
created, automatically discovered or deleted by this workflow.

The private local plan/consumed marker is only per-run, on ephemeral runner disk.
It is not shared durable storage between workflow runs. Cross-run refusal comes
from GitHub's sequence gate. The underlying launcher retains its consume-before-
dispatch guard and no-retry semantics. No capture, buyer approval, GET, Gemini,
live-money endpoint or Service integration is added.

Only strictly schema-checked sanitized evidence JSON is printed once to the job
log. A local `safe-evidence/evidence.json` copy supports verification; nothing
is uploaded as an artifact, so no artifact-storage allocation is introduced.
The JSON contains the
fixed source revision, validated numeric GitHub run ID and 40-hex workflow
revision, workflow-slot consumption, a boolean local consumed-marker
observation and the launcher's revalidated sanitized receipt. No plan, ledger,
raw logs, merchant/app IDs, provider body, payer data or approval URL is printed.
A missing receipt is not evidence that no request occurred; the slot remains
spent. UNKNOWN remains unknown. PARTIAL_PROVIDER_OBSERVATION is not payment
success or a working checkout. The provider order ID is the only remote ID
allowed in the receipt. Workflow success means the wrapper completed, not that
PayPal accepted an order. Private files are not automatically deleted to hide an
uncertain result; they expire with the hosted runner.

Local checks use only fabricated credentials and fake subprocess/provider seams.
No GitHub dispatch, actual Secret lookup, OAuth, Orders or paid compute occurred
while preparing this wrapper.
