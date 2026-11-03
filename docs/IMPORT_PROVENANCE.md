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


## Evaluation import — issue #6

- Issue: https://github.com/thzthix/cart-readback/issues/6; branch
  `test/6-evaluation-harness`, draft target `feat/3-fixture-server` (PR #4).
- Exact server base: `d2781cf7f603d83b552c9cd84371544357589bdd`;
  scaffold PR #2 remains an unmerged foundation. Main is unchanged.
- Theo | AI evaluation engineering (`import_evaluation_harness`) imports Blair's
  pre-existing synthetic scorer/corpus and existing prompt preparation. This is
  issue-first import/change review, not retroactive review of their original work.
- Exactly 21 evaluation/prompt/status paths plus branch-local root README and this
  ledger. No server/API/UI implementation, `eval/runs`, old harness receipts,
  research archives, credentials or model/payment API calls are included.
- [Current status](../cart_readback/VALIDATION_STATUS.md) takes precedence over
  preparation-era "not run" wording. A later app-external uncontrolled native-agent
  pilot exposed this synthetic set; it is regression material, not fresh holdout.
  No historical numeric leaderboard or causal prompt winner is republished.
- Parallel UI work owns its own stage. Alex must deliberately integrate the short
  shared README/ledger changes rather than overwrite a colleague's branch.

### Explicit versioned tooling changes

The initial Ruff format check failed on three original evaluator Python files.
After separate-worker compatibility review, Ruff 0.14.3 formatted only
`build_holdout.py`, `score.py` and `test_score.py`; that phase had source-identical
ASTs and manifest 1.0.1. Original bytes and exact phase hashes remain in the local
review archive, not the shipped runtime tree.

The same separate worker then reproduced two distinct P2 defects. Scorer/wrapper
explanation checks accepted empty/control/surrogate strings rejected by the app;
the scorer and external wrapper now reject them, including trailing LF. A foreign
JSON-escaped surrogate case ID crashed report printing; ASCII-safe JSON reporting
now preserves the error and fixed denominator. Three new regression tests cover
these fixes. No runtime/API or frozen prompt schema changed.

Current manifest **1.0.2** binds the final tool/schema bytes, with a separate
`validation_revision` identifying the behavior fixes and formatting-phase hash.
Dataset remains `cartreadback-semantic-holdout-1.0.0`. Original corpus, labels,
metric definitions and prompt/template/schema/plan bytes are unchanged; defective
string eligibility is deliberately corrected, not claimed formatting-only.
`tooling_revision` retains original tool hashes and original manifest SHA-256
`aebd3463ffcc6a08eb4c7a71dfcdc8e451269c4b11992ae67873c7c5180e40a3`;
`validation_revision` also retains the original external-wrapper schema hash.
Other original manifest fields retain preparation-era meaning. The untouched
original corpus/manifest validated before migration; current scorer checks bind
this import. No hash check was bypassed and no new model run occurred.

Prompt preflight changes only the counterexample attribution from "Human-authored"
to "Author-constructed synthetic". `PREFLIGHT.json` was regenerated using existing
dev-only jsonschema 4.26.0 against imported API/brief/backend hashes, followed by
`SHA256SUMS`. The frozen scorer README remains byte-identical, including references
to historical harness receipts intentionally excluded from this repository.

### Evaluation source/import hashes (SHA-256)

Source paths are the same relative paths under the local product workspace.
Hashes identify exact inputs/imported bytes, not semantic truth. The complete
final tree manifest and exact commit are recorded in the draft PR; this ledger
cannot contain its own final hash. `VALIDATION_STATUS.md` and this new ledger
section are newly written import documentation; root README is adapted locally.

| Repository path | Original source SHA-256 | Imported SHA-256 | Treatment |
| --- | --- | --- | --- |
| `cart_readback/eval/README.md` | `44467555d9882bf7194eceddd4ad87a7909a9a13d2b209ebe0bb78beb9782d22` | `44467555d9882bf7194eceddd4ad87a7909a9a13d2b209ebe0bb78beb9782d22` | unchanged pre-existing local artifact |
| `cart_readback/eval/build_holdout.py` | `ef68f4d924ca6e19783aa17082fccf2f93c17f0518cd54a90d0c54ca4409b54e` | `7b36cd4380df3a50bc0456b637207fb7ad673db124aa432433f1a5eac0340cf8` | Ruff-only formatting; phase AST unchanged |
| `cart_readback/eval/score.py` | `6da02ae69587aabae69262d39af77209aa15b6ce676e800ae24229a61776e714` | `014b7cdf8c31f32fda5aae53ec8c77b55d0bc380fffd79ab474326515ce50ae3` | format phase then separate reviewed validation/report fixes |
| `cart_readback/eval/test_score.py` | `a1f7ed08ac7e5c6c04f6c6a1cffafbc6b741890e3992a6648b7a789ec1e560c7` | `f7fdcaef7d330ff6514ff1a89e80d1c36170aa14413f154e7058de37a88ce3e2` | format phase then separate reviewed validation/report fixes |
| `cart_readback/eval/holdout-inputs.jsonl` | `5f4075c4789880d5822c976f3fb5ac4fdd5c0bfb51b65f7f51bf383095b2c52f` | `5f4075c4789880d5822c976f3fb5ac4fdd5c0bfb51b65f7f51bf383095b2c52f` | unchanged pre-existing local artifact |
| `cart_readback/eval/holdout-gold.jsonl` | `b5b9b3f0306b457fa4ec7ef6a8213f0f57e371e6a791f69fae1297a3147c272c` | `b5b9b3f0306b457fa4ec7ef6a8213f0f57e371e6a791f69fae1297a3147c272c` | unchanged pre-existing local artifact |
| `cart_readback/eval/manifest.json` | `aebd3463ffcc6a08eb4c7a71dfcdc8e451269c4b11992ae67873c7c5180e40a3` | `cfe11a32e16c949bed7c9c2ecd200421de847ae0d952b0dde07ef49304bb61c8` | explicit tooling manifest 1.0.2; corpus version unchanged |
| `cart_readback/eval/predictions.schema.json` | `ada06b395a4e7304e2dad879404973372d78a6e56c763e0bf9e0cde344c44151` | `069d96646ffa37a99bcc36be768df03bce38bdb074990b473f8da2becf2c673d` | external-wrapper explanation policy fix |
| `cart_readback/eval/provenance.example.json` | `8c5129009a903b56d85965238dfbed0f8ef16bd7804e021900542848ec54712c` | `8c5129009a903b56d85965238dfbed0f8ef16bd7804e021900542848ec54712c` | unchanged pre-existing local artifact |
| `cart_readback/prompts/readback-system.txt` | `57a8d66fa78747b661af2d9720ef5ee1ca15f566e2db69200eee6dc808e78239` | `57a8d66fa78747b661af2d9720ef5ee1ca15f566e2db69200eee6dc808e78239` | unchanged pre-existing local artifact |
| `cart_readback/prompts/readback-user-template.txt` | `1b5254db8297debc989a7b0c0f606a6eb64052710a8166e9bedbcfe88d8ddca9` | `1b5254db8297debc989a7b0c0f606a6eb64052710a8166e9bedbcfe88d8ddca9` | unchanged pre-existing local artifact |
| `cart_readback/prompts/arm-A-system.txt` | `0f34a13efd73c0e762daa5038252f9a19d760a78ee51b63b3766d519de9e0fde` | `0f34a13efd73c0e762daa5038252f9a19d760a78ee51b63b3766d519de9e0fde` | unchanged pre-existing local artifact |
| `cart_readback/prompts/arm-B-system.txt` | `57a8d66fa78747b661af2d9720ef5ee1ca15f566e2db69200eee6dc808e78239` | `57a8d66fa78747b661af2d9720ef5ee1ca15f566e2db69200eee6dc808e78239` | unchanged pre-existing local artifact |
| `cart_readback/prompts/arm-C-system.txt` | `f5af0fb84218c837be868e88f564be904425a93fe40e4362c13994157de76409` | `f5af0fb84218c837be868e88f564be904425a93fe40e4362c13994157de76409` | unchanged pre-existing local artifact |
| `cart_readback/prompts/template.json` | `224dfd9f0a6a5fbf5af983ec7e91f928e0418c6b705fcf9602cd19a172d9ea8e` | `224dfd9f0a6a5fbf5af983ec7e91f928e0418c6b705fcf9602cd19a172d9ea8e` | unchanged pre-existing local artifact |
| `cart_readback/prompts/schema.json` | `7a49011e3042d3371bdea11aae201ff4a8d8a2fd5cda4fcd67b23bcf31c7fb57` | `7a49011e3042d3371bdea11aae201ff4a8d8a2fd5cda4fcd67b23bcf31c7fb57` | unchanged pre-existing local artifact |
| `cart_readback/prompts/EVALUATION_PLAN.md` | `944e49a9d6428ac5df1b5b603f330fdc4370314b8e8fd1ce0ad26dc6e12f408a` | `944e49a9d6428ac5df1b5b603f330fdc4370314b8e8fd1ce0ad26dc6e12f408a` | unchanged pre-existing local artifact |
| `cart_readback/prompts/verify_artifacts.py` | `e2134c787c9f277b994c1c39a068ae313f5c39984120e13f13a1bf61d5e82e84` | `05fc14cfdd2979f528296b0893381f59ee2cf16f4504a1f88cb408dec973a5bc` | counterexample attribution wording only |
| `cart_readback/prompts/PREFLIGHT.json` | `941d122067d33d01f8517105c3a662c9b63ccde0f8a7e0c2ed1d9874b28b6b5a` | `dd72bfd822ed834c0a0277afcf421774cb927b36b7651e9ba615db00ad1bb1a0` | fresh imported-dependency receipt/checksums |
| `cart_readback/prompts/SHA256SUMS` | `7a165a0fa1828d89d20fbf3b5ecc0db8c2fc0e5b14212519b68fc7429ffa4a77` | `7de33d079f8f626884a3d903f2d33b76b6c7aac95836b977c668496ec16468f8` | fresh imported-dependency receipt/checksums |

Fresh owner checks and separate-worker final reruns are distinct. Current checks
exercise offline tooling and the fixture backend only. Real inference/provider
schema acceptance, fresh semantic quality, PayPal sandbox, rendered browser flows
and customer value remain open; see current status and the actual draft PR.
