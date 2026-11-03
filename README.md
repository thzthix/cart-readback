# CartReadback

**Check the keyboard you chose before checkout.**

CartReadback compares a selected keyboard with up to two requirements the buyer
already has: language layout and an included cable. It preserves what the source
supports, conflicts with, or does not state.

> **Local fixture server and buyer review UI. Evaluation tooling is not imported
> on this branch. Genuine AI and PayPal sandbox are UNCONNECTED.**

Start with the [project brief](PROJECT_BRIEF.md), [API contract](cart_readback/API_CONTRACT.md),
[architecture](cart_readback/ARCHITECTURE_ADR.md) or [contributing guide](CONTRIBUTING.md).
The scaffold's stage-specific prose describes its earlier documentation-only
revision; this README and the [import ledger](docs/IMPORT_PROVENANCE.md) record the
current stacked UI import. Scaffold PR #2 and server PR #4 are still unmerged;
this UI draft targets `feat/3-fixture-server` at
`d2781cf7f603d83b552c9cd84371544357589bdd`, not main.

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
  No replacement payment or automatic capture retry clears uncertainty. There is
  no cancel/restart flow after order creation.

**All catalog data, proposals and payment responses are synthetic fixtures.
No genuine model call, PayPal call or money movement occurs.** Real adapter
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
command list or older local passes as evidence. This import's actual checks and
separate-worker review are recorded in its draft PR.

## Evidence and remaining gates

This is an **import of pre-existing local fixture work**. Its real issue-first
GitHub pass covers import and subsequent review changes, not retroactive review
of the original implementation. The ledger records source/import hashes, the server
standalone-static-test correction and the UI design-context adaptations. Imported independent tests are pre-existing
work; fresh separate-worker execution, not their presence, supplies current
review evidence.

Buyer UI is now imported under issue #5; evaluation/scorer tools remain pending
a separate issue/branch/draft-PR import. Real-model application integration/fresh
semantic evaluation, PayPal
sandbox lifecycle/recovery, rendered wide/narrow/native-keyboard/interrupted
browser flows and customer baseline/value checks remain unverified. A fresh CUA
HTTP attempt for this stage returned `net::ERR_CONNECTION_REFUSED`; a prior
`file://` attempt was explicitly denied and was not retried or bypassed. No
rendered screenshot, native keyboard/focus, mobile or accessibility pass is claimed.
An earlier
app-external uncontrolled pilot exposed synthetic regression material; it is not
a hidden holdout, prompt-performance winner or real application integration.

The UI draft stacks on server PR #4, itself based on scaffold PR #2, not merged
main. No independently
merge-ready claim, formal APPROVE, merge/auto-merge, deployment, public visibility,
license grant, cost, live payment or contest submission follows from these checks.
This is **not a working AI + PayPal integration release**.

## Contributing and AI assistance

Use real scoped issues, actual numbered branches and draft PRs. A separate review
worker inspects the fixed artifact and reruns relevant checks; findings/fixes and
unresolved facts are summarized truthfully. AI roles label responsibilities, not
separate humans or GitHub accounts. Same-account worker evidence is not an
independent-account approval. Material AI assistance belongs in PR descriptions,
without AI-authorship/coauthor commit trailers or fabricated contributor history.
