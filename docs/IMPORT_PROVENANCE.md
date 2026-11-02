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

## Pending imports and evidence boundaries
The existing fixture server, browser UI, evaluation/scorer and prompt artifacts
are not in this scaffold. Each requires a separate real issue, numbered branch,
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
