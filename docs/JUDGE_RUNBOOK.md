# Reviewer runbook: local fixture demonstration

**Current status: genuine AI and PayPal sandbox are UNCONNECTED.**
This is a runnable synthetic demonstration, not a contest-ready AI + PayPal
integration or proof of buyer benefit. All catalog, proposal and payment results
in the quickstart below are fixtures. No provider accounts or keys are needed.

## Start from the repository root

Use a writable checkout, Python 3.11+ available as `python`, and a current browser
with JavaScript modules, Fetch, AbortController, Web Crypto and sessionStorage.
The runtime uses the Python standard library: no package install, UI build,
Node.js, API key or account setup is needed for this demonstration.

```sh
cd cart_readback
python -m cartreadback_app --port 8765 --db .local/cartreadback.sqlite3
```

Keep the terminal running. Open **http://127.0.0.1:8765/** on the same computer.
Do not substitute `localhost`: Host/Origin checks use the exact address.
Do not expose this local service publicly. If port 8765 is occupied, stop the
known previous demonstration normally; do not terminate an unidentified process.
If startup fails, resolve the reported error before treating the page as current.

## Walk through the synthetic checkout

1. Read the same-source comparison table and a selected keyboard's full source
   description. Scope is six synthetic SKUs, one item/order, USD, and at most two
   typed requirements: language layout and included cable.
2. Select a SKU and one or two requirements, then request analysis. Read each
   `match`, `conflict` or `unknown` and its source evidence. This proposal comes
   from a deterministic test double, not Gemini or another genuine model.
3. Separately acknowledge every conflict/unknown and confirm the exact reviewed
   snapshot. An acknowledgement does not make an unknown fact true. Before order
   creation, editing the selection or requirements clears old consent.
4. Explicitly create the synthetic order, perform simulated buyer approval,
   then request the server recheck. These are separate actions.
5. Provide fresh final capture intent. A successful fixture checkout reaches
   `COMPLETED`. This is simulated capture, not a PayPal transaction or receipt.
   Loading a page or returning to it never captures.

These are expected behaviors for review, not observations from a browser run
performed while writing this document. Exact quotes and valid schemas do not
establish semantic correctness. Compare the flow with the same-source table:
extra input, reading and correction can outweigh any proposed AI benefit.

## Stop, restart and recover safely

Stop with `Ctrl-C`. Restart using the same command, database and browser session;
reload retrieves authoritative state without replaying a POST. Run only one
service instance per database. Keep the entire `.local/` directory private,
including the adjacent fixture-provider database and service-lock path.
Never unlink a live lock file, delete unresolved history, switch owners/databases
to hide an outcome, or downgrade an unresolved database.

Existing, pending and unknown orders keep selection locked. A timeout/crash may
leave `PAYMENT_UNKNOWN`; it is not evidence of success or failure. Reconcile the
same known order rather than creating a replacement or retrying capture.
A lost create response without a provider ID can remain unknown. After creation,
v1 has no cancel/restart/new-order escape flow. Cancellation intent does not void
an order. See [payment recovery](PAYMENT_DISPATCH.md) for the lifecycle limits.

## Optional offline checks

From `cart_readback/`, an API-only smoke needs Python but no browser or manually
running server. Each command owns a temporary loopback server/database:

```sh
python scripts/smoke_http.py
python scripts/smoke_http.py --fault capture_timeout_after_success
python scripts/smoke_http.py --fault capture_timeout_before_success
python scripts/smoke_http.py --fault create_timeout_after_success
```

The script asserts a final synthetic `COMPLETED` for the first two commands and
`PAYMENT_UNKNOWN` for the last two, retaining the same local order during
reconciliation. These are source-defined expectations, not newly executed results.

For broader checks, follow the exact commands and limitations in
[README checks](../README.md#checks) and
[the manual application-check workflow](../README.md#manual-application-check-workflow).
Backend tests use Python; UI check scripts additionally require Node.js 22+
with global Fetch, structuredClone and crypto.randomUUID. Optional development
lint uses Ruff 0.14.3; prompt preflight requires jsonschema 4.26.0 and the reviewed
development requirements. These are not runtime dependencies. Do not install
missing tools or dispatch hosted Actions just to present an unchecked pass.
The aggregate includes all five UI runners and their separate log guards;
individual tests, skipped HTTP tests or old results do not certify the full tree.
Record the exact commit, actual versions, commands, exits, counts and skipped/
not-run stages. Offline HTTP/fake-DOM checks do not establish rendered browser,
keyboard, accessibility or mobile behavior.

## What would count as genuine evidence?

The existing [Gemini host runner](GEMINI_SERVICE.md) and
[read-only result viewer](GEMINI_RESULT_VIEWER_V1.md) are separate opt-in host
paths, not activation controls in this fixture UI. A fabricated exchange, local
approval record, runtime label or successful viewer test proves no genuine call.
No actual Gemini credential setup, provider call or free-quota proof is established.

Before a future genuine demonstration, retain redacted evidence tied to its exact
revision and original operation:
- Externally verified project/model eligibility, billing/free-tier facts, explicit
  data/spend authorization, and properly provisioned credentials outside the repo.
- An actual provider response and retained usage/accounting, with separately
  evaluated semantics. A dispatch claim alone does not prove network delivery;
  usage alone does not prove a valid proposal or buyer benefit.
- Actual PayPal **sandbox** create, buyer approval, server verification, explicit
  capture and same-order recovery evidence, with complete required returned facts.
  Fixture payments remain fixtures even if analysis later becomes genuine.

This runbook supplies no credential-install shortcut or invented live command.
Do not stage simulated footage as genuine integration, clear UNKNOWN to repeat
a demo, publish secrets, or treat sandbox observations as live-money evidence.

## Gates before judging access or submission

The current private repository has no open-source license. It is not ready for
public judging access or submission. Under the
[official contest rules](https://paypalaihackathon.devpost.com/rules), the eventual
entry needs genuine AI and central PayPal sandbox integration, a public
open-source repository, English content or translation, and a hosted demo **or**
complete runnable instructions. Judging access must remain available through
December 15, 2026 at 16:00 UTC. A video under three minutes is a recommendation,
not a hard rule asserted here.

This fixture runbook alone does not satisfy the integration requirement.
Genuine integration/recovery, fresh semantic evaluation, rendered/native-keyboard
flows and buyer value remain unverified. Public visibility, license selection,
deployment, costs, legal acceptance and submission are separate decisions.
Do not infer authority for any of them from a documentation PR or a merge.

## Verification note

Commands were checked against README, the fixture entry point and smoke source
at main `e48c2b5d0a7ebe32cad56aed80e5fbd68c89215f`.
No application, browser, provider or aggregate checks were executed for this
documentation change. See the linked PR's fixed-head review for later evidence.
