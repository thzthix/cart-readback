# Reviewer runbook: local fixture demonstration

**This quickstart is fixture-only; real PayPal sandbox remains unverified.**
Separate opt-in Gemini application evidence now exists; see the
[November 10 integration record](https://github.com/thzthix/cart-readback/blob/2fa2cb46ce5701e97e7ceaf01f2f559552ce267d/README.md#current-integration-status--november-10-2026).
That record describes the historical fourth sample. The subsequent
[fifth sample](https://github.com/thzthix/cart-readback/actions/runs/42824418362)
completed on November 10 at 13:26 UTC, attempt 1, workflow head
`9d2f3818646ca2dee3b5c05f3e8897c8ed89a0f9`, using unchanged production source
`8ba9e9623db4ee094d3245615417b7511b8d0e33`.
Its safe job receipt reports `APP_ANALYSIS_VALIDATED`, known accounting,
provider-observation, observed usage, `gemini-3.5-flash-lite`, and
`conflict` / `unknown`; payment remained fixture. The fourth sample's
`match` / `match` and fifth sample's `conflict` / `unknown` are two
separate validated synthetic application cases, not a general accuracy study.
Neither makes this quickstart a genuine AI + PayPal checkout or establishes
buyer benefit. All catalog, proposal and payment results
in the quickstart below are fixtures. No provider accounts or keys are needed.

## Start from the repository root

Use a writable checkout, Python 3.11+ available as `python`, and a current browser
with JavaScript modules, Fetch, AbortController, Web Crypto and sessionStorage.
The runtime uses the Python standard library: no package install, UI build,
Node.js, API key or account setup is needed for this demonstration.
Check `python --version` first. If it is missing or older than 3.11, choose an
already installed Python 3.11+ interpreter, verify its version, and substitute
that command for every `python` below (and in linked checks). Do not assume the
system `python3` is recent enough. Stop if no suitable interpreter is available.

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
[the manual application-check workflow](../README.md#historical-offline-application-check-workflow-setup).
Backend tests use Python; UI check scripts additionally require Node.js 22+
with global Fetch, structuredClone and crypto.randomUUID. Optional development
lint uses Ruff 0.14.3; prompt preflight requires jsonschema 4.26.0 and the reviewed
development requirements. The linked aggregate recipe also requires Bash, Git,
awk, tee, cmp and sha256sum. Verify these tools before running it; sha256sum is
not assumed to be available on macOS. Missing prerequisites are a blocker, not
permission to install tools automatically. These are not runtime dependencies. Do not install
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
The historical integration record and fifth-run receipt above distinguish actual
provider observations from fixtures. Together they record two schema/span-validated
application cases, not general semantic quality or a verified zero-charge invoice. This runbook does not
provision or activate that host path.

For any genuine demonstration, retain redacted evidence tied to its exact
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
complete runnable instructions. Free, unrestricted judging access must remain
available through
December 15, 2026 at 16:00 UTC.

Submission deadline: **November 12, 2026 at 20:00 UTC** (November 13 at 05:00 KST).
Before submitting, verify each required deliverable against the official rules:
- A working application with central PayPal sandbox integration and an AI tool.
- Public repository URL, detectable open-source license, necessary source/assets,
  and complete run instructions or a working hosted demo.
- English description, testing instructions and video, or English translations.
- Public YouTube video URL entered in the submission form, showing the app running
  on its intended device. Under three minutes is recommended; judges need not
  watch beyond three minutes. Use only materials with the required permissions.
- Free, unrestricted working-build access through the judging deadline above.

These unchecked deliverables are a preparation checklist, not evidence of
registration, publication, eligibility, rule acceptance or submission.

This fixture runbook alone does not satisfy the integration requirement.
End-to-end AI plus PayPal integration/recovery, fresh semantic evaluation,
rendered/native-keyboard flows and buyer value remain unverified. Public visibility, license selection,
deployment, costs, legal acceptance and submission are separate decisions.
Do not infer authority for any of them from a documentation PR or a merge.

## Verification note

Commands were checked against README, the fixture entry point and smoke source
at main `e48c2b5d0a7ebe32cad56aed80e5fbd68c89215f`.
No application, browser, provider or aggregate checks were executed for this
documentation change. See [PR #61](https://github.com/thzthix/cart-readback/pull/61)
for the current review state and any later fixed-head evidence; this note does
not assert that review of the latest revision is complete.

### November 11 documentation refresh

Official submission requirements were re-read on November 11, 2026. The status
correction first referenced main `2fa2cb46ce5701e97e7ceaf01f2f559552ce267d`.
The later branch reconciliation incorporated that main revision while preserving
all its application files unchanged. No fresh application, provider, browser or
aggregate pass is claimed. The fixture entry point, smoke command options and final
state expectations were rechecked against that revision. The historical
application-workflow heading link was corrected. Static review is still distinct
from running the application; fresh separate-worker review is required.

## Recording plan: 2 minutes 50 seconds, not yet recorded

This is an English rehearsal script for the current fixture build, not a
submission-ready end-to-end integration demo. No footage, native-browser pass or
recorded duration is established here. Record only after the displayed steps
actually work in an authorized browser. Keep a visible "FIXTURE: synthetic
analysis and payment" label throughout fixture footage. Do not replace missing
screen recordings with a mockup and describe it as working software.

Timing includes pauses and screen actions. Rehearse aloud and shorten if needed;
the timestamps are targets, not a measured recording. Do not run a paid/model
request or retry a spent operation for recording.

### 0:00–0:20 | Buyer problem

Show the actual comparison table and selected item's full original description.

Narration: "CartReadback helps someone check the keyboard they already chose.
A keyboard's physical shape does not establish its language layout, and a pictured
cable may not be included. We compare the selected item with up to two
requirements before checkout."

### 0:20–0:45 | Honest baseline

Show the same-source table before requesting analysis. Select one item and enter
requirements that are visibly supported or not stated in its displayed source.
Do not invent a SKU-specific result or claim an unobserved outcome.

Narration: "The original description and comparison table are available first.
They use the same source material as the readback. If this table solves the
problem with less effort, the AI layer has not earned its place. Customer benefit
has not yet been measured."

### 0:45–1:20 | Review and uncertainty

Request fixture analysis. Show the observed result, original source and exact
quotation if present. If a conflict or unknown occurs, show its separate,
initially unchecked acknowledgement. Do not force an unknown into a match.

Narration: "This local flow uses a deterministic test double. Results distinguish
support, conflict and missing information. The buyer reviews the evidence and
acknowledges each conflict or unknown separately. Acknowledging uncertainty
does not change the facts. Exact quotation checks alone do not establish that
a model's interpretation is correct."

### 1:20–1:55 | Buyer authority

Confirm the reviewed snapshot, create the synthetic order, simulate approval,
request server verification, then give fresh final capture intent. Show only the
state actually returned; stop on a failed step rather than editing in success.

Narration: "The buyer confirms this exact review. Order creation, simulated
approval, server verification and final capture intent are separate steps.
The server owns the amount and currency. The model cannot authorize payment.
Every payment shown here is simulated; no PayPal sandbox transaction is shown."

### 1:55–2:20 | Recovery, visibly separate

Only if separately executed successfully, show the terminal command
`python scripts/smoke_http.py --fault capture_timeout_before_success`
and its actual synthetic state output. Label this "Separate API fixture test",
not a continuation of the previous browser order. If it has not run, use the
design explanation only, clearly labelled "Expected behavior, not executed".

Narration: "The recovery design keeps an uncertain outcome unknown and checks
the same order. It does not create a replacement payment to manufacture success.
This separate synthetic timeout scenario is a test of that boundary, not proof
of PayPal's behavior."

### 2:20–2:50 | Genuine evidence and remaining work

Show the dated integration record linked above, clearly labelled historical
provider evidence, separate from this fixture session. Do not show credentials,
private databases, raw provider bodies or account identifiers.

Narration: "Separately, two synthetic cases received real Gemini responses and
passed schema and exact-evidence validation: one returned two matches, the other
conflict and unknown. Earlier failed outcomes remain recorded. This does not prove general accuracy, buyer benefit,
or a connected PayPal checkout. Genuine PayPal sandbox integration, end-to-end
verification and unrestricted judging access remain open."

### Final recording gate

Recheck the dated integration record and fifth-run receipt before recording;
do not silently expand these two cases to later experiments. A compliant final submission needs
actual central PayPal sandbox integration and a working build, as stated above.
After that is implemented and verified, rewrite and rerecord the relevant section
against its real evidence. A fixture label does not cure a missing required
integration. Public repository licensing, public video publication and submission
remain separate decisions; this script authorizes none of them.
