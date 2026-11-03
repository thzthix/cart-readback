# Development and contribution conventions

## Issue-first GitHub flow

Use a lightweight [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow): one scoped issue, one short-lived branch, one draft PR into `main`. `main` is the release/integration branch, not permission to deploy. Do not add permanent `develop` or per-role branches, or a Gitflow release hierarchy without a concrete need. Roles collaborate on work items; they do not each need a standing branch.

1. Search existing issues. Open a feature/scoped-change, bug, or research issue using `.github/ISSUE_TEMPLATE/`. State the user problem, acceptance evidence and boundaries before implementation. PM records priority, one accountable owner and the implementation/review roles. A large feature is split into independently reviewable issues, not one branch per file.
2. Start from the verified current `main` and use the **real issue number** in `<type>/<issue-number>-<short-kebab-description>`. If an unmerged scaffold/server is a required foundation, an explicitly declared draft stack may use that owning branch as its base. Record its PR and exact SHA; dependent readiness remains blocked until the foundation is properly integrated. Do not invent issue numbers or merge a foundation merely to unblock a stack.
3. Implement only that issue's scope. Accompanying tests and docs stay on the same branch. Agree file ownership before parallel edits; separate issues that touch the same contract need an explicit integration order. Keep commits focused; do not rewrite another contributor's branch or shared history.
4. When repository writing is authorized, push the scoped branch and open a **draft** PR targeting `main` (or the declared unmerged foundation for a draft stack). Use the PR template, a semantic title, actual checks and a fixed revision for review. Partial work references `Refs #123`; only a PR satisfying the whole issue uses `Closes #123` in its description. The numbers here and below are format examples, not existing issues.
5. A different review worker inspects the changed artifact and reruns relevant checks independently. Resolve findings, recheck the new revision, then update the evidence. Mark ready for review only when authorized. A role's favorable report is not a GitHub approval.
6. Merge only with explicit applicable merge authority and verified review/check state for the final head commit. No auto-merge. After the authorized merge, verify the merged revision and issue state; delete the completed branch only within that authority. Deployment and contest submission are separate actions.

Branch examples:

| Work | Branch |
| --- | --- |
| Feature | `feat/123-reply-evidence` |
| Bug | `fix/124-reject-stale-revision` |
| Documentation | `docs/125-adapter-contract` |
| Tests only | `test/126-retry-regression` |
| Research | `research/127-payment-id-feasibility` |
| Refactor or maintenance | `refactor/128-split-parser`, `chore/129-tool-config` |

Project naming rule: `^(feat|fix|docs|test|research|refactor|chore)/[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$`. Use lowercase ASCII names; do not put people, dates, secrets or customer data in branch names. Research branches are needed only when an issue produces versioned research artifacts; a discussion-only issue needs no empty branch.

[GitHub's issue-link rules](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue) interpret closing keywords in PR descriptions targeting the default branch. Set the default to `main`; verify the repository's [automatic issue-closing setting](https://github.blog/changelog/2025-04-23-users-can-now-choose-whether-merging-linked-pull-requests-automatically-closes-the-issue/) rather than promising that every link will close an issue. References alone are not completion evidence.

## Roles, authorship and release control

The [team role contracts](docs/TEAM_ROLES.md) describe responsibility, not extra GitHub identities:

| Role | Required handoff |
| --- | --- |
| Research / user problem | Sources, uncertainty, baseline and a bounded decision question in the issue |
| Architect | Interface/risk decision and acceptance boundaries before dependent changes |
| Implementer | Branch/PR, exact revision, changed scope and observed checks |
| Independent evaluator | A separately performed review, fixed revision, reproduced results and unresolved findings |
| PM / release owner | Scope decision, truthful readiness record and the specific authority for any external action |

When several AI workers use **one authenticated GitHub account**, their issues, comments and PRs still come from that account. Identify the contributing and reviewing roles/worker records in the PR body, not as invented humans, bots, collaborators or coauthors. Say "separate worker review under the same account" when that is what happened. Never describe that as a second human's or second account's approval. [GitHub does not permit PR authors to approve their own PRs](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request). If an independent account approval is required but unavailable, leave that stage blocked; do not weaken a protection or create a fake reviewer to bypass it. Posting a GitHub review, merging and enabling auto-merge are separate external actions requiring their applicable authority.

Before any local commit, inspect repository-local `user.name` and `user.email`, and the effective author/committer identity. Do **not** use this environment's inherited `Codex` / `codex@openai.com` identity as the user's identity. The owner must confirm a correct, privacy-safe identity (including their verified GitHub no-reply address when desired). Do not guess a name/email, expose a public email unnecessarily, or change global Git config. Connector-created commits use their actual authenticated actor; verify the returned author/committer and resulting commit instead of assuming local Git config controls them.

AI assistance is disclosed in the **PR body**: tools/tasks, materially generated or edited portions, verification and limitations. Do not append AI-authored, generated-by, bot-signature or `Co-authored-by` attribution footers to commits or PR text. Do not invent contributor identities. The requested absence of attribution footers is not permission to conceal material AI use where disclosure is required.

No backdated commits, fabricated issues/PRs/reviews, or retroactive claims that existing local files went through this workflow. An eventual initial import must be described as an import of pre-existing local work with its actual provenance. Issue-first feature work begins after that truthful bootstrap; bootstrap is not evidence that prior local work had issue/PR review.

### Repository setup checklist (separate from this draft branch)

The scaffold originally introduced the templates; verify their presence and rendering on the actual default branch rather than inferring activation from this text. These imports do not configure branch protection, application CI, licensing or public publication. With applicable authority, verify each setting:

- Confirm the owner, visibility and privacy-safe authorship; make `main` the default branch and enable Issues.
- Put the issue forms and PR template on the default branch and preview all three forms. The [chooser configuration](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository) discourages blank issues; it is not a permission boundary, and maintainers can still use blank issues. Forms deliberately do not assume labels, assignees, projects or team accounts exist. Their YAML follows [GitHub's issue-form syntax](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms). The current [form schema](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema) describes required-field enforcement as public-repository-only; verify behavior for the chosen visibility and do not treat a form as enforcement of review or authorization.
- Where supported by the repository's plan, propose a `main` [protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches): require PRs and resolved conversations; disallow force pushes and branch deletion. Do not silently enable bypasses. Require a separate account's approval only when such a reviewer is actually available and authorized.
- Require only checks that actually exist and have run; do not configure invented or never-reporting status names. Recheck the final head commit after updates. Record protection/CI gaps explicitly if plan, access or reviewer availability blocks enforcement.
- Keep auto-merge off. Prefer an explicitly authorized squash merge with the semantic PR title; inspect the final commit text and remove prohibited attribution trailers. No release tag, deployment or submission follows merely from merging.

## Python
Use the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) as the baseline: readable names, small focused functions, explicit imports, 4-space indentation, documented public contracts, and Google-style Args/Returns/Raises sections when useful. Prefer explicit exception types and avoid catching broad failures merely to report success. Use type annotations for new public interfaces. Avoid mutable defaults. Keep the formatter line target at 80; a formatter cannot guarantee every line or semantic rule satisfies the guide.

Only CartReadback is in this repository; historical prototypes are not imported. A focused style-only change must not alter payment behavior. Ruff checks selected error/import/docstring rules, not the entire Google guide. No claim of Google certification or complete conformance.

## Commits
Adopt [Conventional Commits 1.0](https://www.conventionalcommits.org/en/v1.0.0/): `type(scope): imperative summary`, e.g. `fix(approval): reject expired quote tokens`. This project requires a concise scope for commit and PR titles, although the upstream specification makes it optional. `feat`, `fix`, `test`, `docs`, `refactor`, `chore` are project types; `ci` and `build` apply when those systems actually change. Research-only artifacts use `docs(research): ...` or `chore(research): ...`, not a made-up feature. Mark breaking contracts with `!` and explain the incompatible contract and migration in the body. A body records why and relevant evidence. These are our conventions, not Google's prescribed commit syntax. Conventional Commits does not require attribution footers.

## Pull requests
Follow Google's [change description guidance](https://google.github.io/eng-practices/review/developer/cl-descriptions.html): explain what and why, not just a file list. One coherent intent per draft PR. Include the linked issue, scope/non-goals, risk boundaries, tests actually run, not-run integration stages, and rollback. Include redacted before/after screenshots and accessibility/interaction checks for user-visible changes, or state why not applicable. Do not bundle style rewrites with behavior changes. The PR template is in `.github/pull_request_template.md`.

## Checks
This tree includes the fixture server, buyer UI and offline evaluation tools. Use all applicable component entry points in README.md from cart_readback/. A changed integrated tree requires fresh backend, UI, evaluator, prompt-preflight, compile, lint/format and fixture smoke checks; old local/component receipts do not certify the new head.

For a server import, run the documented domain/actual-loopback HTTP suites, independent Python tests, compile and four fixture smoke scenarios from a clean server-only tree. HTTP static transport tests own their temporary sentinel assets, so an unmerged UI cannot silently make the server pass. The UI import adds python ui/check.py, which starts the HTTP test server, and the independent Node tests. The evaluation import adds corpus/scorer harness checks and a separately dependency-checked prompt preflight.

Ruff availability and dependency installation are separate. The intended optional development-only version is Ruff 0.14.3; pin/verify it when imported, not a runtime requirement or proof of complete Google-style compliance. Domain tests require no network or paid API. Before introducing third-party dependencies, pin a reviewed compatible set and record license/source; do not install arbitrary latest versions as a prerequisite.

For a documentation/template-only PR, parse the changed YAML, inspect form fields/links and branch examples, and report that application behavior was not tested. Offline structure validation is not GitHub's rendered-form validation; preview after authorized publication remains a separate stage.

## Review sequence

Use the [implementation/review/fix contract](docs/TEAM_ROLES.md). Review dialogue need not be reproduced in PR comments; the PR must summarize enough evidence for its reader.
Correctness and authorization first, recovery next, then readability/style. A deterministic failing test outweighs an agent's favorable rating. Reviewers independently check a fixed artifact version and identify exact file/line or command output. Approval of a code review does not authorize live spending, repository publication or contest entry.
