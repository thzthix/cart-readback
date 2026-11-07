# CartReadback

**Check the keyboard you chose before checkout.**

CartReadback compares a selected keyboard with up to two requirements the buyer
already has: language layout and an included cable. It preserves what the source
supports, conflicts with, or does not state.

> **Local fixture server, buyer review UI and offline evaluation tooling.
> Genuine AI and PayPal sandbox are UNCONNECTED.**

Start with the [project brief](PROJECT_BRIEF.md), [API contract](cart_readback/API_CONTRACT.md),
[architecture](cart_readback/ARCHITECTURE_ADR.md) or [contributing guide](CONTRIBUTING.md).
This tree combines the separately reviewed scaffold, server, buyer UI and offline
evaluation imports. The [import ledger](docs/IMPORT_PROVENANCE.md) preserves their
original scope, hashes, real review findings and integration changes. Read the
[current evaluation status](cart_readback/VALIDATION_STATUS.md) before frozen
preparation-era artifacts. Exact-head checks and actual merge state are recorded
in [evaluation/integration PR #8](https://github.com/thzthix/cart-readback/pull/8).

## Why this exists

ISO keyboard shape does not establish a UK language layout. A pictured or
compatible cable does not establish inclusion. First scope: one merchant, six
synthetic keyboard SKUs, one item per order, and at most two typed conditions.
This is not a recommendation engine, price finder, compatibility guarantee or
connection to arbitrary shops.

A clear option-and-included-items table using **identical source material** is the
non-AI baseline. AI earns a place only if its benefit exceeds preparation, input,
reading and correction effort. Customer demand and that benefit are unknown.
The UI presents that same-source table first. Selecting a row exposes its complete
original description without entering conditions or requesting analysis. “Not
stated” differs from explicit “Not included”; ISO geometry does not establish
UK/DE language layout. The [design contract](cart_readback/ui/DESIGN.md) documents
the preserved small editorial buying desk and its evidence limits.

## What is available

- A standard-library Python service bound only to literal `127.0.0.1`, with
  SQLite sessions, consent, audit observations and durable operation identities.
- Source-backed `match`, `conflict` and `unknown` proposals from a deterministic
  test double, not genuine inference. Exact quotations/schema checks do not prove
  semantic correctness. Each unknown/conflict requires separate acknowledgement;
  acknowledgement never turns uncertainty into a match.
- Consent bound to SKU, source, conditions, price and model/prompt identity;
  changed facts invalidate old consent. The server owns integer USD cents and
  quantity one; model/browser values cannot authorize money movement.
- Separate simulated create, fixture approval, server verification and explicit
  final capture. GET never captures. Owner, same-origin, CSRF, body and revision
  guards reject unsupported requests.
- Timeout/restart ambiguity stays `PAYMENT_UNKNOWN`. Reconciliation checks the
  same known order; without a provider ID create recovery remains unknown.
  No replacement payment or automatic capture retry clears uncertainty. A buyer
  cancellation return records intent only; it never voids or replaces an order.

**All catalog data, proposals and payment responses are synthetic fixtures.
No genuine model call, PayPal call or money movement occurs.** Analysis and
payment provider modes are labelled separately. Injected fabricated PayPal wire
responses are not fixture-model evidence or a connected checkout. Real adapter
interfaces are disabled and have no live fallback. This is a local/demo server,
not a production-security endorsement.

## Local fixture quickstart

Python 3.11+ is required. Runtime has no third-party packages, API keys or account
setup or UI build step. A browser is needed for the UI. From the repository root:

```sh
cd cart_readback
python -m cartreadback_app --port 8765 --db .local/cartreadback.sqlite3
```

Open **http://127.0.0.1:8765/**; do not substitute `localhost`: Host/Origin checks
use the exact configured address. Select one SKU and one or two conditions, read
the same-source evidence, separately acknowledge each conflict/unknown, then
confirm the exact snapshot. Synthetic order create, simulated buyer approval,
server recheck and fresh final capture intent remain explicit separate actions.
Existing/pending/unknown orders keep selection locked; reconcile the same order
rather than restarting. Reload restores authoritative state without POST replay.
The API remains at `/api/bootstrap`. For an API-only synthetic checkout, run
`python scripts/smoke_http.py`; it owns a temporary
server/database and carries cookies, CSRF, revision and deliberate action intent.
It does not require a manually running server.

Stop the server with `Ctrl-C`. Keep `.local/` private; it stores sessions and order
history. Do not expose the service publicly or erase an unresolved checkout to
manufacture a fresh success.

## Offline payment recovery boundary

Payment reservation, single dispatch claim and fenced observation now use short
separate transactions; provider calls hold no application SQLite transaction.
The synthetic provider has an independently committed adjacent database so crash
checks cannot roll back its side effects. Restart preserves UNKNOWN and never
replays a monetary request. One service instance owns each database. See the
[dispatch/recovery design and limits](docs/PAYMENT_DISPATCH.md), including the
real subprocess crash matrix and private database/lock lifecycle. This remains
fixture-only; PayPal and real inference are disabled.

## Offline analysis lifecycle

Analysis now reserves, claims and attaches observations in separate short SQLite
transactions; injected adapter work holds no application DB lock. A durable
owner/input/config/generation fence prevents stale results from replacing a newer
review. Nonfixture service analysis is default-denied unless an explicit offline
budget policy and an injected fabricated count seam are configured. Count preflight runs
outside SQLite under a bounded durable claim and exact request/config/revision
comparison before admission. Budget reservation,
single claim, settlement and UNKNOWN recovery now share the analysis SQLite
transaction. Capacity is conservatively retained across failure/restart; this is
not real counting, verified pricing or permission for paid inference. Pending or
failed analysis has no confirmable snapshot. See
[analysis dispatch](docs/ANALYSIS_DISPATCH.md) and the
[atomic offline budget gate](docs/ATOMIC_ANALYSIS_BUDGET.md) and
[count preflight design/economic limits](docs/OFFLINE_COUNT_PREFLIGHT.md).
The default server/CLI still use only the synthetic fixture.

## Offline PayPal wire preparation

An [injected-only PayPal Orders wire adapter](docs/OFFLINE_PAYPAL_BOUNDARY.md)
adds fabricated-envelope checks through the existing durable payment seam.
It has no network implementation, credentials or runtime switch. An injected-only
[buyer-return preparation](docs/OFFLINE_BUYER_RETURN.md) now binds inert callback
URLs to a one-use owner/order/snapshot state. The default server remains
fixture-only; genuine sandbox and payments are
still UNCONNECTED. Missing returned facts remain unknown, never request-backed
verification. This prerequisite does not establish PayPal acceptance or approval.

## HTTPS/OAuth groundwork, still disabled

An isolated [sandbox HTTPS/OAuth core](docs/PAYPAL_HTTPS_GROUNDWORK.md) now has
fake-connection tests for fixed-host verified TLS settings, bounded OAuth/Orders
exchanges, strict no-proxy/no-retry behavior and sanitized uncertainty. No factory
or credential source is selected by default, and the network-marked core cannot
be injected directly under an offline provider label. No genuine provider call
has run. The direct-only policy does not support PythonAnywhere free outbound
proxy routing; it is not a deployment or sandbox-acceptance result.

## Checks

Run backend checks from `cart_readback/`, with no UI/eval directory required:

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s review -p 'test_independent_*.py' -v
python -m compileall -q cartreadback_app tests scripts review
python scripts/smoke_http.py
python scripts/smoke_http.py --fault capture_timeout_after_success
python scripts/smoke_http.py --fault capture_timeout_before_success
python scripts/smoke_http.py --fault create_timeout_after_success
```

The HTTP suite owns four temporary sentinel assets to test transport MIME and
allowlist behavior. Those are not the production UI and do not replace later real
asset/browser integration checks. Optional development lint is pinned to Ruff
0.14.3 in `scripts/requirements-dev.txt`; it is not a runtime dependency. When
available, use `ruff check cartreadback_app tests scripts review` and
`ruff format --check cartreadback_app tests scripts review`.

**UI checks:** Node.js 22+ with global `fetch`, `structuredClone` and
`crypto.randomUUID` is required for check scripts (not for the Python runtime).
Use a current browser with modules, Fetch, AbortController, Web Crypto and
sessionStorage; storage failure blocks operation-key preparation. From
`cart_readback/`:

```sh
python ui/check.py
python ui/context_http_check.py
node --test review/test_independent_ui.mjs
python -m compileall -q cartreadback_app tests scripts review ui/check.py
# With reviewed Ruff 0.14.3 available:
ruff check cartreadback_app tests scripts review ui/check.py
ruff format --check cartreadback_app tests scripts review ui/check.py
```

`python ui/check.py` starts an ephemeral temporary SQLite-backed loopback server
and runs actual HTTP/client tests. Running `http.test.mjs` alone without its
origin skips them and is not a pass. Static/token-contrast, pure-core, fake-DOM
and actual HTTP checks do not establish native browser/rendering/accessibility.
No bundler, package manager, remote fonts, images or analytics is used.

Record observed counts/exits against an exact revision rather than treating this
command list or older local passes as evidence. Actual checks and separate-worker
review are recorded against exact revisions in the component PRs and final
integration PR #8.

## Offline evaluation checks

The imported scorer never generates predictions or calls a model. The 24
synthetic cases / 48 conditions were later exposed by an **app-external,
uncontrolled native-agent pilot**; they are regression material, **not a fresh
hidden holdout**. Their frozen preparation-time "not run" wording is historical.
Read the [current status and limitations](cart_readback/VALIDATION_STATUS.md),
[frozen scorer instructions](cart_readback/eval/README.md) and
[prompt plan](cart_readback/prompts/EVALUATION_PLAN.md) together.

Run from `cart_readback/`:

```sh
python eval/score.py validate
python -m unittest discover -s eval -p 'test_score.py' -v
python -m compileall -q eval prompts
python prompts/verify_artifacts.py > prompts/PREFLIGHT.json.tmp && \
  mv prompts/PREFLIGHT.json.tmp prompts/PREFLIGHT.json
(cd prompts && sha256sum readback-system.txt readback-user-template.txt \
  arm-A-system.txt arm-B-system.txt arm-C-system.txt template.json schema.json \
  EVALUATION_PLAN.md verify_artifacts.py PREFLIGHT.json > SHA256SUMS)
(cd prompts && sha256sum -c SHA256SUMS)
```

The scorer is dependency-free. Prompt preflight uses **development-only**
`jsonschema` 4.26.0; it is not a runtime dependency. The reviewed exact dev-tool
versions, transitive requirements, sources and licenses are declared in
`cart_readback/scripts/requirements-dev.txt`.
Regeneration binds actual imported dependencies; it is not model evaluation.
Exact quotes and canonical-span containment do not establish semantic entailment;
the local root-array schema is not a tested provider wire request. Candidate B
is prepared, not a performance winner. See integration PR #8 for exact-head
results, the versioned tooling/manifest migration and reviewed string-policy/
report corrections. Dataset, gold and frozen prompt bytes remain unchanged;
this is not a new quality experiment.

## Manual application-check workflow

[`Offline application checks`](.github/workflows/application-checks.yml) prepares
one Ubuntu 24.04 job for Python 3.11 and Node 22. It is **manual-only**, with no
push, pull-request or scheduled trigger. This is automation preparation, not a
claim that GitHub application CI has run or a required-check rule is enforced.
GitHub only accepts `workflow_dispatch` for a workflow present on the default
branch; this draft must be reviewed and separately authorized for merge first.

Before any dispatch or addition of automatic triggers, the owner must verify
available included compute and a no-charge billing limit, or give specific cost
authorization. Private-repository standard runners can incur charges after the
account's shared included compute is exhausted. No run, paid upgrade or spending
change is authorized by this workflow. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

For local reproduction, use Python 3.11+ and Node 22+. From the repository root,
install the exact reviewed development tools in a disposable virtual environment
and set the workflow's environment before copying its `run` commands:

```sh
python -m venv /tmp/cartreadback-dev
. /tmp/cartreadback-dev/bin/activate
python -m pip install --no-cache-dir --only-binary=:all: -r cart_readback/scripts/requirements-dev.txt
python -m pip check
export PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
export NODE_OPTIONS='--test-reporter=tap'
export RUNNER_TEMP="$(mktemp -d /tmp/cartreadback-checks.XXXXXX)"
cd cart_readback
# Run the workflow's run commands here, or use the individual checks above.
```

The temporary directory holds only local check logs and a synthetic preflight
receipt; remove that directory after inspecting the results.

The workflow binds official actions to full commits from their repositories:
[checkout v7.0.1](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1),
[setup-python v7.0.0](https://github.com/actions/setup-python/commit/5fda3b95a4ea91299a34e894583c3862153e4b97),
and [setup-node v7.1.0](https://github.com/actions/setup-node/commit/949feb2413d6458794dcd2491c4babbbce0c15c1).
Only repository-content read permission is requested. Checkout credentials are
not persisted; package caches, artifact uploads, secrets and deployments are not
used. One job has a ten-minute timeout and a newer run cancels an older run for
the same ref. Python/Node patch releases and the hosted runner image can change;
the run records actual versions and checkout SHA, not an immutable OS image.

UI checks own a real ephemeral loopback server. The workflow explicitly selects
Node's TAP reporter, rejects skipped or TODO Node tests and requires both UI
groups plus the independent group to report zero skipped. Prompt preflight
writes only to a temporary file, compares the
frozen receipt and checks all existing hashes. It never regenerates gold, corpus
or prompt bytes. A final tracked-source diff detects mutations. These checks
remain offline fixture evidence, not native browser, model or PayPal validation.

## Genuine provider runtime design

[Issue #33 architecture and gates](docs/GENUINE_PROVIDER_RUNTIME.md) explains
why a concrete factory alone cannot enable genuine inference, the unresolved
count-payload contract, and the required identity/accounting/authorization work.
That architecture stage was documentation only. No live key, call or readiness pass was established.

[Issue #35's separate immutable identity primitive](docs/GENUINE_RUNTIME_IDENTITY.md)
now binds the planned provider/request/transport policy and explicitly absent
evidence into one review fingerprint. Its capability result is always blocked;
it adds no executable genuine factory, count projection or service/CLI selection.
Account binding, count equivalence, pricing and authorization remain unresolved.

## Context-capacity analysis service bridge

[Issue #39's host-only service bridge](docs/CONTEXT_ANALYSIS_BRIDGE.md) now joins
analysis and context-capacity reservation, single claim, bounded exchange,
independent accounting and proposal CAS. It uses a distinct adapter without an
input-count preflight. The original counted-plan identity stays blocked.

Default server/CLI and payments remain fixture-only. There is no supported live
installation resolver or activation flag. Tests fabricate trusted host records,
opaque handles and HTTPS exchanges; their public evidence is fabricated-offline,
not provider success. A separately provisioned provider runtime could incur API
charges, so C12 distinguishes current dispatch availability from historical
attempt/accounting and retains uncertainty across strategy changes. Reference
estimates remain unselected reference math, not actual billing. Secure key setup,
external binding/approval, real network/provider behavior and buyer benefit are
still unverified. No genuine inference or payment was performed by this change.

## Gemini host-only one-shot bridge

[Issue #48's Gemini Service and runner](docs/GEMINI_SERVICE.md) compose the actual
Gemini client/HTTPS transport with a distinct durable capacity ledger. This is a
host-only opt-in route, not a default server, HTTP or buyer UI selector. The
ordinary fixture CLI, UI and PayPal paths are unchanged.

The runner has separate offline `prepare` and explicitly approved `run` phases.
Run requires the same existing database/owner, a reviewed nonsecret host record
with project/model/eligibility, external decision, explicit admission mode and
exact data/spend scope, and a pre-opened private credential pipe. It does not discover ambient
keys or create credentials. The key is borrowed only after durable reservation
and claim. A local record identifies externally established facts and approval;
it does not verify them or supply approval by itself.

Issue #50 distinguishes positive-rate `paid` admission from explicit
`externally-verified-free-tier` admission. Free mode requires externally
established Free-tier/no-paid-project-billing facts, zero/zero adopted rates and
exactly zero authorized USD; positive call/token bounds remain mandatory. Public
pricing and local record hashes do not verify account facts or supply consent.
Mode, exact project/model, eligibility/pricing/host-decision records and window
are bound into policy, runtime and immutable allowance identity. Legacy v1
approval/policy records fail closed without migration or allowance renewal.

Every call permanently reserves 1,048,576 input tokens and 2,048 output tokens
including thoughts, plus one call and the mode-specific adopted spend. This is
conservative local accounting, not an actual 1M-token request, quota proof or
invoice. Free mode reserves zero USD while consuming full call/token capacity. Failed, uncertain, stale or restarted operations remain
UNKNOWN with no retry, refund or automatic renewal. Tests use only fabricated
wires and synthetic keys; they do not establish real account eligibility,
pricing, TLS/provider acceptance, paid usage, semantic quality or buyer benefit.
No actual Gemini credential setup or provider call has been performed.

## Evidence and remaining gates

This is an **import of pre-existing local fixture work**. The issue-first GitHub
pass covers import and subsequent review changes, not retroactive review of the
original implementation. The ledger retains original/imported hashes, the server
standalone-static-test correction, UI response-body timeout fix/regression, and
evaluator string-policy/report fixes. Imported independent tests are pre-existing
work; fresh separately performed execution supplies current review evidence.

All four component slices are present in this tree. Genuine model application
integration/fresh semantic evaluation, PayPal sandbox lifecycle/recovery, rendered
wide/narrow/native-keyboard/interrupted browser flows and customer baseline/value
remain unverified. A CUA HTTP attempt returned `net::ERR_CONNECTION_REFUSED`;
a prior `file://` attempt was explicitly denied and was not retried or bypassed.
No rendered screenshot, native keyboard/focus, mobile or accessibility pass is
claimed. Fake-DOM and actual HTTP tests do not replace those checks.

An earlier app-external uncontrolled pilot exposed the synthetic evaluation set.
It is regression material, not a hidden holdout, prompt-performance winner or
real application integration. Structural/scorer success does not prove semantic
truth or buyer benefit.

The owner separately authorized merging these reviewed private project PRs.
No formal APPROVE or independent-account approval is implied. Merge does not
authorize auto-merge, public release, licensing, deployment, costs, real payments
or contest submission. This is **not a working AI + PayPal integration release**.

## Contributing and AI assistance

Use real scoped issues, actual numbered branches and draft PRs. A separate review
worker inspects the fixed artifact and reruns relevant checks; findings/fixes and
unresolved facts are summarized truthfully. AI roles label responsibilities, not
separate humans or GitHub accounts. Same-account worker evidence is not an
independent-account approval. Material AI assistance belongs in PR descriptions,
without AI-authorship/coauthor commit trailers or fabricated contributor history.

## Approved Gemini result viewer

[Issue #52's host-result-viewer addendum](docs/GEMINI_RESULT_VIEWER_V1.md) defines
a separate opt-in, review-only loopback viewer for the original single approved
Gemini analysis, held in the same Service lifetime. It does not enable ordinary
UI-driven inference or checkout. Its local opener and provider action retain
separate authorization; all development checks use fabricated wires only.
