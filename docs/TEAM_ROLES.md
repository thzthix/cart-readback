# AI roles, handoffs and genuine review loop

These are AI responsibilities, not human employees, extra GitHub identities or a
runtime multi-agent checkout architecture. The actual authenticated account owns
its GitHub actions. Separate-worker review is not independent-account approval.

| Role | Accountable output |
| --- | --- |
| Alex — AI PM | One bounded issue, allowed paths/dependencies, evidence/unknowns and owner gate. |
| Theo — AI Architect | API/authority/recovery decisions and compatibility boundaries before dependent edits. |
| Ryan — AI Backend | Deterministic fixture server, consent/money/operation ledger and documented checks. |
| Chloe — AI Design/Frontend | Buyer effort, same-source baseline, uncertainty rendering and explicit actions. |
| Blair — AI Independent Review/Evaluation | Separately performed artifact inspection, reproducers, actual reruns and unresolved findings. |

A role label does not prove expertise or improve correctness. No majority vote,
self-score, fictional meeting or fabricated favorable review counts as evidence.
If a reviewer writes a fix, another worker verifies that fix.

## Handoff envelope
Include the actual issue/PR, implementer/reviewer worker reference, exact base and
head commit (or local file-set manifest before publication), original import-source
hashes, changed paths, intent, acceptance conditions, actual commands/exits/counts,
failed/skipped/not-run stages, strongest objection and next authorized gate.
Receiver reads original code/contract rather than trusting an author's self-score.

## Implementation → review → fix → independent retest
1. Create a real issue before a numbered scoped branch. For an import, distinguish
   existing local work from new review fixes; never invent earlier GitHub history.
2. Freeze a clean exact artifact. The reviewer inspects it before favorable author
   summaries where practical, then checks authority/correctness, recovery and
   clarity. Do not let an unmerged component silently satisfy another's checks.
3. Reproduce suspected defects. Report severity, file/line, expected/observed buyer
   impact, minimal command/interaction and fix condition. Unknown is not a pass or
   a confirmed finding. Do not invent a defect merely to produce dialogue.
4. The implementer fixes or disputes each finding on the owning branch with
   evidence and a narrow regression. Contract changes go to the architect and
   dependent owners. Do not skip failing tests or bundle unrelated cleanup.
5. A separate worker reruns the reproducer and affected aggregate checks on the
   new exact revision. Mark findings fixed/open/not-reproduced; previous passes
   do not certify later edits, integration or generated outputs.
6. Summarize final evidence and remaining gates in the draft PR. Dialogue can stay
   in a task/shared review note or genuine comments; no scripted PR back-and-forth
   is required. Include necessary evidence if the detailed record is inaccessible.

## Severity and claims
S0: severe payment/owner/consent bypass, duplicate money action or secret exposure;
block affected release without creating real financial harm to reproduce it.
S1: core buyer/recovery error, false success or unsupported fact presented as known;
fix/retest before readiness. S2: bounded functional/accessibility/reproducibility or
materially misleading documentation defect; fix or obtain explicit owner disposition.
S3: cosmetic/readability issue; may explicitly defer. Severity follows demonstrated
impact, not confidence. Keep unverified suspicions and unavailable checks separate.

Valid quotes are not semantic proof. Fixture payments are not PayPal responses.
Minimal-DOM/static contrast and local HTTP checks are not rendered-browser,
native-keyboard or accessibility certification. Model, sandbox and buyer-value
checks are separate from fixture regression.

## README-only newcomer check
Give a separate tester only the candidate README, a clean staged tree, its
artifact ID, the safety scope and an output location—not hidden setup recipes or
old test receipts. Can the tester distinguish this scaffold from future executable
imports, follow available links and explain unknown/acknowledgement boundaries?
For a later executable stage, can they launch from repository-root instructions,
reach the loopback URL, identify fixture actions and recover interrupted flows?
The author fixes gaps; the tester retries a fresh clean tree. Correctly declining
to launch an absent scaffold app is not successful application execution.

## GitHub and release gate
PRs start draft. A genuine COMMENT review under the actual account can record
separate-role evidence; it does not supply another human/account's approval.
Do not submit formal APPROVE as a fictional reviewer or weaken required review
settings. No merge, auto-merge, public release, deployment, spending or submission
follows from a worker's favorable finding. Disclose material AI help in the PR
body; keep actual verified author/committer identity and omit AI/coauthor trailers.
