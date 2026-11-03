# Import provenance and current evidence

## Scaffold import — issue #1
- Repository: private `thzthix/cart-readback`.
- Issue: https://github.com/thzthix/cart-readback/issues/1
- Branch: `chore/1-repository-scaffold`.
- Base: existing initial main commit `cea096349990628c461e07743f79f30081c0fc2a`.
- Scope: 14 documentation/config/API-contract paths, no application implementation.
- Source snapshot: pre-existing local workspace `output/paypal-agent-contest`,
  inspected and assembled on 2026-11-02 UTC. Original local work preceded this
  GitHub issue. This import does not retroactively claim issue-first development,
  a reviewed commit history, human collaboration or actual model/payment results.
- New scaffold files: `.gitignore`, this ledger and `docs/TEAM_ROLES.md`. The role
  contract condenses existing team/review-loop guidance without importing archives.
- Material AI help: Alex PM/assembly and existing role workers assisted planning,
  docs, contract design and review. Role names are not separate GitHub accounts.

The final scaffold commit/head and observed assembled-tree checks must be recorded
in the actual draft PR when it is created and verified. A ledger cannot include its own final commit/hash without
self-reference; the table below identifies original local input bytes, not proof
that every adapted output is byte-identical. Rehash actual outputs for review.

| Repository path | Local original input | Original SHA-256 | Import treatment |
| --- | --- | --- | --- |
| `README.md` | `release/scaffold/README.md` | `2153f28fc8ccf3b11406c5632004c9a76ae04784a48bffca53893bdfdc6cbb58` | prepared README, unchanged from final local documentation review |
| `AGENTS.md` | `AGENTS.md` | `af2fdefd58c110f9e70e72b3fdbff5ede2dbc1309c5ac81aaa281cd956039fa5` | adapted to single-product scaffold |
| `CONTRIBUTING.md` | `CONTRIBUTING.md` | `4b2173b34076e86f01a19e853d3811a8b0e61b00138793709c3a059893b8311a` | adapted current commands, stack and review boundaries |
| `pyproject.toml` | `pyproject.toml` | `50d6bc3e142151dbb8461397762a61f5aabbe4aa843ee2c2aa21eeeb5affe46c` | same Ruff settings; header comment updated |
| `PROJECT_BRIEF.md` | `PROJECT_BRIEF.md` | `9635faf6e6edeb7c9c1e7de5c05b5c439f2b3f9d9d06c077c4d907a140a06056` | adapted active scope/status; archive references excluded |
| `.github/ISSUE_TEMPLATE/config.yml` | `.github/ISSUE_TEMPLATE/config.yml` | `500ddc6c63d9a40c5376e0bea1530ad9f600e39c836a1c25cccf33047b41146c` | unchanged |
| `.github/ISSUE_TEMPLATE/feature.yml` | `.github/ISSUE_TEMPLATE/feature.yml` | `e87830c8b4077f663ce463b17d6354d3b66a38e97808e562b6d73bcff4dc9802` | unchanged |
| `.github/ISSUE_TEMPLATE/bug.yml` | `.github/ISSUE_TEMPLATE/bug.yml` | `02ccfd4132fae64cefb046a856c775c7ab8fad26604f6970e845fb655de6147e` | unchanged |
| `.github/ISSUE_TEMPLATE/research.yml` | `.github/ISSUE_TEMPLATE/research.yml` | `4b633b7d10a912946d4d1519ad444d9aed2ca214441c6dc025a419ca456504a2` | unchanged |
| `.github/pull_request_template.md` | `.github/pull_request_template.md` | `02d6465dbb080ea76960a854d4e3325d5340e694ffdde5951626a0dfdf7e8b07` | unchanged |
| `cart_readback/API_CONTRACT.md` | `cart_readback/API_CONTRACT.md` | `ab1c857d9fe2bec2533309bb314421ada4db00a70f2e271c41d1844180e6298f` | C10 repository-context correction only; normative API v1 wire semantics unchanged |

## Assembled-document correction
Fresh separate-worker inspection identified SC1 (S2 documentation): the original
API contract's C10 still said repository creation was blocked. This scaffold
corrects only that contextual sentence to describe actual issue #1 and its branch;
all normative wire/API behavior is unchanged. The original API input hash remains
in the table above. The actual draft PR must record the final-revision independent retest when it is
created and verified; no earlier candidate/manifest may be silently carried forward
as final verification.

## Actual prior README review, limited scope
The prepared README's final local SHA-256 is
`2153f28fc8ccf3b11406c5632004c9a76ae04784a48bffca53893bdfdc6cbb58`.
A separate AI documentation reviewer (`review_scaffold_readme`, Blair role) first
read the README without favorable author summaries, then received limited source/
command inspection scope. Three findings were genuinely corrected and reread:
current-stage navigation placement, an illustrative UNKNOWN example and a complete
Node runtime/global requirement. The final record reported no remaining issue in
that documentation/source-command scope. It ran no app, UI, smoke or evaluation
suite and did not inspect an assembled tree/clean clone. Fresh staged-link and
final-head review remain distinct; no formal GitHub approval is implied.

## Scaffold-era pending imports and evidence boundaries
At the scaffold revision, the existing fixture server, browser UI, evaluation/scorer
and prompt artifacts were not imported. The server import below supersedes only
that server status; UI/evaluation remain pending. Each requires a separate real issue, numbered branch,
draft PR and fixed-revision implementation/review/fix/retest record. Prior local
passes are history, not imported-head results. Historical experiments/research,
credentials/browser state, local SQLite databases, caches and old logs are excluded.

The future runtime uses synthetic catalog data, deterministic proposal test double
and fake payment provider. No genuine inference, PayPal call or money movement
is established by fixtures. A later app-external uncontrolled native-agent pilot
used synthetic evaluation inputs, exposing them for future use; they are regression
material, not fresh hidden holdout. No prompt winner, app adapter, complete human
semantic validation, rendered browser pass or buyer benefit is established.

Actual model/fresh semantic evaluation, PayPal sandbox lifecycle/recovery,
wide/narrow/native-keyboard/interrupted browser flows and real-user baseline value
remain open. Public licensing/provenance, visibility, merge, deployment, costs and
contest submission retain separate authority gates. No AI/coauthor attribution
trailer or fictional approval/authorship history is part of this import.


## Server import — issue #3

- Issue: https://github.com/thzthix/cart-readback/issues/3
- Branch: `feat/3-fixture-server`; draft target: `chore/1-repository-scaffold`.
- Exact base: `249cec13dfc6de2e8cf469c6cba6d40acc8a2d0f`, draft scaffold PR #2.
  Main is not assumed to contain that foundation. No merge/APPROVE is authorized.
- Import of pre-existing local fixture work; this issue-first GitHub pass covers
  the import and subsequent review changes, not retroactive review of the original
  implementation. Source: local `output/paypal-agent-contest/cart_readback/`.
- Exactly 18 new backend/test/script/design paths plus root README and this ledger;
  no UI/eval, historical archives, old test receipts, database, cache or secrets.
- Ryan | AI Backend (`import_fixture_server`) assembled the import, corrected the
  test fixture and ran fresh checks. Imported independent tests are pre-existing
  work, not newly authored evidence or a fresh review. Separate-worker review and
  actual final head/checks are recorded in the draft PR after publication.
- The root README is newly adapted for the API-only stage. Scaffold API contract
  bytes are retained, including the reviewed C10 context correction; no normative
  API change. ADR/domain source is imported unchanged as pre-existing design:
  historical CR identifiers and repository-creation context are not new GitHub
  execution/approval claims.

### Source and imported hashes (SHA-256)

The paths below are relative to the repository; source paths are the same paths
under the local product root, without their `cart_readback/` prefix. Source hashes
identify original input. Imported hashes bind exact bytes, not semantic truth or
real-provider evidence. This ledger cannot contain its own final hash/commit;
record the complete final manifest and commit in the draft PR.

| Repository path | Original source SHA-256 | Imported SHA-256 | Treatment |
| --- | --- | --- | --- |
| `cart_readback/cartreadback_app/__init__.py` | `c8431576235cb80924cf030c5d9098ea76ed3b1e7198a1d03ba0affe53a5ecd0` | `c8431576235cb80924cf030c5d9098ea76ed3b1e7198a1d03ba0affe53a5ecd0` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/__main__.py` | `63b0d0414f0c4c18901ce2d958ac3f8784b4d9448ef93423d3815f375020cd9a` | `63b0d0414f0c4c18901ce2d958ac3f8784b4d9448ef93423d3815f375020cd9a` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/catalog.py` | `c4ed51bf5e08df48d6f2802aa313a12550ae400f8390f921d38a86e8a29a7e51` | `c4ed51bf5e08df48d6f2802aa313a12550ae400f8390f921d38a86e8a29a7e51` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/http.py` | `243cce53416d76d8c126c31755c56fd32f68453b52b315ba8f52d6bd8469a3a7` | `243cce53416d76d8c126c31755c56fd32f68453b52b315ba8f52d6bd8469a3a7` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/inference.py` | `145c4655be4fe54c21a6800048ffd61f27447ec523b46d9b1f59bd4b008d654f` | `145c4655be4fe54c21a6800048ffd61f27447ec523b46d9b1f59bd4b008d654f` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/payments.py` | `c64815ad92b40c7a7aa361eefccaa209c56a614e5f0181921aaf5b88f7879dd8` | `c64815ad92b40c7a7aa361eefccaa209c56a614e5f0181921aaf5b88f7879dd8` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/service.py` | `bbae51bceb1c58d611700e927e160cda61aad8698930727c55f2efa29147c4fb` | `bbae51bceb1c58d611700e927e160cda61aad8698930727c55f2efa29147c4fb` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/storage.py` | `6e3c7a8477f8b14ab252df26c79b096c590961f776fa23c89fdba5bc1c5201a3` | `6e3c7a8477f8b14ab252df26c79b096c590961f776fa23c89fdba5bc1c5201a3` | unchanged pre-existing local source |
| `cart_readback/cartreadback_app/validation.py` | `e343efd1b6806336f0588398fe9ee8ca5a0ea436303810ee05ba0480660bf6f2` | `e343efd1b6806336f0588398fe9ee8ca5a0ea436303810ee05ba0480660bf6f2` | unchanged pre-existing local source |
| `cart_readback/tests/test_domain.py` | `312d2de9c0eda09fc91292584c8a7be6738ab6fde1bbd9b4cc2eb70afba7759d` | `312d2de9c0eda09fc91292584c8a7be6738ab6fde1bbd9b4cc2eb70afba7759d` | unchanged pre-existing local source |
| `cart_readback/tests/test_http.py` | `01f53337c21f6829c453590e21c2cd23a0351bccea85e168fec3dfb1388bac39` | `6ada83a865bbdea285fe7667288703b2ccaef88233eda393e6d614b2f8a01e58` | HTTP-owned sentinel fixture correction below |
| `cart_readback/scripts/requirements-dev.txt` | `e10ffea431a662cfe968cd39fa389fec39e65e1f46a41b77f195fcc061b7710f` | `e10ffea431a662cfe968cd39fa389fec39e65e1f46a41b77f195fcc061b7710f` | unchanged pre-existing local source |
| `cart_readback/scripts/smoke_http.py` | `7c7d04f3b2a00870dd197adef7a0d619ff962bf4bf95d126ee69ac1d3aa338e4` | `7c7d04f3b2a00870dd197adef7a0d619ff962bf4bf95d126ee69ac1d3aa338e4` | unchanged pre-existing local source |
| `cart_readback/ARCHITECTURE_ADR.md` | `b28c32fa5b513c9c4897fa6e10906da5dc11f16398156e78c368f29d64186b5c` | `b28c32fa5b513c9c4897fa6e10906da5dc11f16398156e78c368f29d64186b5c` | unchanged pre-existing local source |
| `cart_readback/DOMAIN_MODEL.md` | `93db09c00a5915744a2a9514de2662428390ba6dbdc238a29f9e9ef227acb226` | `93db09c00a5915744a2a9514de2662428390ba6dbdc238a29f9e9ef227acb226` | unchanged pre-existing local source |
| `cart_readback/review/test_independent_boundaries.py` | `04cfda04939c8db7cee295039554f2e0b60ab13ac2fa8288880cc00e2f278c89` | `04cfda04939c8db7cee295039554f2e0b60ab13ac2fa8288880cc00e2f278c89` | unchanged pre-existing local source |
| `cart_readback/review/test_independent_http.py` | `f65e8977da580209f7e1d8edd74ff2a5788b71338dcb88a905f72f3cf84f53a4` | `f65e8977da580209f7e1d8edd74ff2a5788b71338dcb88a905f72f3cf84f53a4` | unchanged pre-existing local source |
| `cart_readback/review/test_independent_workflow.py` | `ec6661d6384d5bc4bac1e1ba180f3d6f51e75a624ba6e302c7813261571168ba` | `ec6661d6384d5bc4bac1e1ba180f3d6f51e75a624ba6e302c7813261571168ba` | unchanged pre-existing local source |


### Actual subsequent change and fresh-check limits

After issue #3 existed, the unchanged backend-only assembly ran 40 tests: 39
passed and static MIME failed at `tests/test_http.py:372` (expected 200, got 404).
The test had read absent production UI. The correction is confined to that test:
create four plainly labeled temporary sentinels (`index.html`, `app.mjs`,
`core.mjs`, `styles.css`), assert exact sentinel bytes and MIME, prove an existing
non-allowlisted file stays inaccessible, and add missing-allowed-file 404 with
restoration in `finally`. No production routing or prior boundary assertion was changed, and no test
was skipped. Ruff 0.14.3 then reformatted only that test file (layout only). Production UI integration remains a separate later gate.

Fresh backend-only author execution after this fix observed 41 tests passing,
29 imported independent tests passing, compile success and all four smoke modes
exiting 0. Normal checkout completed; capture-timeout-after-success reconciled to
COMPLETED; capture-timeout-before-success remained PAYMENT_UNKNOWN despite an
APPROVED observation; create-timeout-after-success remained PAYMENT_UNKNOWN with
no provider ID. These are synthetic local results, not PayPal/model calls or
independent-worker approval. Final exact revision, reruns, optional lint
availability and separate-worker findings belong in the actual draft PR.

Browser UI/evaluation remain not imported. Real inference and PayPal sandbox are
UNCONNECTED. Public deployment/security, semantic truth, customer benefit and
real integration are not established; existing release/authorization gates stay
in force. No AI/coauthor trailer, fictional identity or retroactive history claim
is part of this import.


## Buyer UI import — issue #5

- Issue: https://github.com/thzthix/cart-readback/issues/5
- Branch: `feat/5-buyer-review-ui`; draft target: `feat/3-fixture-server`.
- Exact server base: `d2781cf7f603d83b552c9cd84371544357589bdd`, draft PR #4,
  itself stacked on unmerged scaffold PR #2. Main is not an integrated build.
- Import of pre-existing local fixture work; this issue-first GitHub pass covers
  the import and subsequent review changes, not retroactive review of the original
  implementation. Source: local `output/paypal-agent-contest/cart_readback/`.
- Exactly ten new UI/design/test/check paths plus root README and this ledger.
  No server/API, evaluation, archives, images, dependencies or provider changes.
- Chloe | AI Design/Frontend (`import_buyer_interface`) assembled this import and
  ran fresh checks. The imported independent UI suite is pre-existing work, not
  newly written review or evidence of a second human/account's approval.

### UI source and imported hashes (SHA-256)

Source paths are the same paths under the local source root. Imported hashes bind
bytes, not semantic correctness, browser rendering or real-provider behavior.
This ledger cannot contain its own final hash/commit; the draft PR records the
complete frozen manifest, actual head and separately performed review/retests.

| Repository path | Original source SHA-256 | Imported SHA-256 | Treatment |
| --- | --- | --- | --- |
| `cart_readback/ui/DESIGN.md` | `160c710d8bfc3d712917e647742d9e4ddcd0f9cd4b3968e2b4b2fca8c4c1176f` | `2920a3493c7e017f6a642dfefead36d9813e703f92ed949f465bd9cd2a4a3eaa` | current import-context/archive-link correction; historical checks explicitly labelled |
| `cart_readback/ui/index.html` | `39c9186ef002ce06e45372dfa8caf7dcb10b5925ae5db5e70c5f252cd6dd5d32` | `39c9186ef002ce06e45372dfa8caf7dcb10b5925ae5db5e70c5f252cd6dd5d32` | unchanged pre-existing local source |
| `cart_readback/ui/styles.css` | `887cb132214e83c7d680d5dc7a100fcbff5206b0e0df61349114088101f19ba9` | `887cb132214e83c7d680d5dc7a100fcbff5206b0e0df61349114088101f19ba9` | unchanged pre-existing local source |
| `cart_readback/ui/core.mjs` | `bed52c44271fa2d557c405c159237d4e97b2eeb31e3b2f074bdd8de222bb2842` | `bed52c44271fa2d557c405c159237d4e97b2eeb31e3b2f074bdd8de222bb2842` | unchanged pre-existing local source |
| `cart_readback/ui/app.mjs` | `a2b29e403e4950bb8c60033fec55e9903efbee5d547e8c4e2fabd5db4d859e7a` | `6da3a1dc6017758d8178883b1309f36c662ec06778aeec092723d1256934ebea` | UI1 body-read deadline recovery correction |
| `cart_readback/ui/core.test.mjs` | `051f648761cdd718c7303752152ef4b2ad7e00ef93287b3a8ebb409643fa22e9` | `051f648761cdd718c7303752152ef4b2ad7e00ef93287b3a8ebb409643fa22e9` | unchanged pre-existing local source |
| `cart_readback/ui/app.test.mjs` | `dc5fc1a3bc88c4ed3c3fbbf76a108752d6e548a669f4e929d5c16f232ff1aff0` | `90aa17b32d04303a635a7bc8a5e6209231f7c21b6d3e615b4b64274ad39c25c8` | UI1 native Fetch partial-body timeout regression |
| `cart_readback/ui/http.test.mjs` | `86315dd7ef76914102bfcf8a4bbd58cc41ab15bb524f985344c2e20336981d79` | `86315dd7ef76914102bfcf8a4bbd58cc41ab15bb524f985344c2e20336981d79` | unchanged pre-existing local source |
| `cart_readback/ui/check.py` | `bfc5ed361d73aca592a91f09863f2abc55deca1380fe650e195d798b73026cd2` | `bfc5ed361d73aca592a91f09863f2abc55deca1380fe650e195d798b73026cd2` | unchanged pre-existing local source |
| `cart_readback/review/test_independent_ui.mjs` | `2871e5956de2aaf30636828bd24152fa7f56d1afc5b1ff5bb6890da04ba502db` | `2871e5956de2aaf30636828bd24152fa7f56d1afc5b1ff5bb6890da04ba502db` | unchanged pre-existing local source |

### Actual import adaptations and fresh evidence limits

Seven UI/test/check inputs remain byte-identical to their local originals.
`app.mjs` and `app.test.mjs` have the subsequent UI1 fix/regression below. DESIGN.md
now identifies the real import issue/branch/base, distinguishes historical local
checks from fresh import-head evidence, and renders excluded archival research
references as plain context rather than broken repository links. Root README is
adapted from the verified server base for actual UI quickstart/checks and status.
The UI preserves the same-source non-AI comparison table and complete original
description before analysis, explicit per-condition UNKNOWN/conflict review,
codepoint quotations and separate deliberate fixture checkout actions. No new
design, screenshots, users, runtime AI or PayPal integration is fabricated.

Fresh final author execution observed 22 Node core/minimal-fake-DOM tests and three
actual loopback HTTP/client cases via `python ui/check.py` (25 total, zero skips),
seven imported independent Node checks, Python 41 domain/HTTP +29 independent
tests, compile, four smoke modes, and existing Ruff 0.14.3 lint/format-check
including `ui/check.py` (16 files formatted) all exiting 0. These are synthetic
local checks, not native rendering/accessibility, semantic or real-provider proof.
Final exact-artifact reruns and separate-worker findings belong in the draft PR.

Separate read-only reviewer `review_buyer_interface_import` found UI1 (S2): the
15-second AbortController deadline ended when response headers arrived, before
JSON body completion. A flushed 200 response with a stalled body could leave a
mutation busy forever and disable reload. Chloe changed only the client wrapper
to await parsing inside the deadline, for bootstrap and mutations. The new
regression uses native Node Fetch against a loopback partial-body server (not
rendering): after native-Fetch warmup it accelerates only the app deadline,
requires abort, one dispatch/no replay, an honest uncertainty pause, enabled
reload and same-order recovery. In a disposable copy of original app.mjs it
failed specifically because the signal was not aborted; the fixed case passes.
No server/API semantics or operation/consent checks were weakened. The reviewer
independently retests the new frozen revision; its separate create-specific
partial-body probe is local review evidence, not shipped or invented browser QA.

A fresh supported CUA HTTP attempt for this staged UI returned
`net::ERR_CONNECTION_REFUSED` for `http://127.0.0.1:8765/`. The prior explicitly
denied `file://` route was not retried; no alternate origin, proxy, host binding
or browser-policy workaround was used. Native wide/narrow rendering, keyboard/
focus, browser Back/Forward and interrupted real-browser flows remain not run.
Static/contrast, fake-DOM and real HTTP tests are not substitutes for those gates.

Evaluation tooling remains absent; the earlier server-only pending-UI statements
above describe their original revision and are superseded by this section only.
Genuine inference and PayPal sandbox remain UNCONNECTED. Same-source buyer value,
production security, model semantics and real payment/recovery remain unverified.
No merge, formal APPROVE, deployment, public release, license, account or spend
authority follows from this fixture import.
