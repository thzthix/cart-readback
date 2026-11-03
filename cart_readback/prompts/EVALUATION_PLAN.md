# CartReadback prompt v1 — preparation and evaluation plan

Status: **prepared, not integrated, no model calls and no A/B/C results**. Theo/Morgan are development responsibilities (contract and evidence review), not deployed runtime agents or identities whose labels confer accuracy. Work is confined to `prompts/`; the real-model adapter remains disabled. No credentials, accounts, paid calls, PayPal calls, source-fixture changes, or runtime changes are included.

## Frozen artifacts and task variables

- Prompt version: `cartreadback-prompt-v1`. Candidate **B**: exact `readback-system.txt` bytes. One release contains the three predeclared comparison arms, not three successive tuned versions.
- `template.json`: provider-neutral user template, strict input schema, rendering/host checks, A/B/C assembly, unset execution settings, and exactly **two public, authored synthetic development examples**. They are not merchant/customer data, holdout, or model outputs. Expected explanations are illustrative rather than exact-string grading targets.
- `arm-A-system.txt`, `arm-B-system.txt`, `arm-C-system.txt`: separate exact system prompts for input-only execution. B is byte-identical to `readback-system.txt`. `readback-user-template.txt` is the shared user template without any example/answer labels. Do not pass all of `template.json` to an evaluator/model: it contains the two public development answer keys.
- `schema.json`: full local JSON Schema Draft 2020-12 for the current **bare array** `InferenceAdapter.propose(source, conditions) -> list[dict]` result. Not a universal vendor schema subset.
- `SHA256SUMS`: SHA-256 of exact UTF-8 file bytes. No normalization. It binds the prepared artifacts, not execution or semantic truth. Read contract/interface hashes in the preflight record below; changes require review and a new prompt release before use.

Variables are the exact server-owned `source` (ID, revision, UTF-8 SHA-256 and unmodified text), one/two typed buyer conditions including their IDs/order, and explicit explanation `response_language` (`en` or `ko`). Layout enums describe language/keycaps, not ISO/ANSI geometry. Source language, explanation language, layout and cable connector type are separate concepts. No price, merchant credentials, consent, payment state or tool is supplied to the model. Host code, not model echo, binds source/model/prompt/adapter/validator identities to the immutable review.

Render by serializing the validated request as JSON and inserting it once; never recursively evaluate placeholders in source text. JSON escaping/delimiters reduce accidental ambiguity but do **not** make adversarial text trustworthy. Source commands, fake role delimiters and desired outputs remain data. The model receives no browse/payment tool. Reject invalid host inputs before a call; do not ask the model to repair IDs, hashes or missing buyer preferences.

## Meaning is not a substring test

| Source situation | Required treatment |
| --- | --- |
| Explicit applicable desired layout/included item | `match`, with sufficient exact contextual evidence |
| Explicit incompatible layout, direct exclusion, or clearly complete/single-valued incompatible inclusion fact | `conflict`, with evidence containing the exclusion/qualifier |
| Negated desired phrase | Never keyword-match it; decide from the complete denial and scope |
| Missing fact, picture, supported connector, optional accessory, unknown bundle condition | `unknown`; absence is not exclusion, compatibility is not inclusion |
| Applicable contradictory assertions with no explicit resolution | `unknown`; preserve both sides rather than choose one |
| Source instructions, a quoted fake answer, another SKU's facts | Not a fact establishing this SKU's condition |

Two included cable types can coexist. An arbitrary mention of another cable is not automatically a conflict; evaluate whether the description really establishes a complete/single-valued inclusion fact. The existing fixture's authored `Included cable:` field is a declared fact, not a license to treat all free prose as a closed inventory. `any cable` may match explicit cable inclusion with unspecified ends; the exact requested end types then remain unknown. A buyer's acknowledgement never upgrades `unknown` or `conflict`.

`schema.json` can enforce output shape, enums, bounds and nonempty match/conflict evidence. It cannot prove expected condition-ID membership/uniqueness, source identity, `end > start`, an exact source slice, current version/hash, relevance, negation handling, or entailment. The existing `validate_proposal` checks the condition references and exact spans, **not unrestricted semantic correctness**. The offline preflight intentionally confirms that a semantically false `match` with an exact quote still passes both structural validators. It is a documented limitation, not model evaluation.

## Current offsets and a future adapter decision

The current contract is Unicode **code point** `[start,end)`. Offsets count decoded `source.text`, not escape syntax, UTF-8 bytes, JavaScript UTF-16 units or visual graphemes. Candidate B requests exact quotes **and** those offsets; the host rejects mismatches. Do not silently recalculate or snap malformed spans, normalize text, strip Markdown, downgrade a technical failure to `unknown`, or retry until an apparent pass. Refusal, truncation, no content and invalid schema/spans must produce blocked analysis, never a confirmable invented result.

A preferable candidate for a later **ADR**, not an implementation here, is model-selected exact quote plus an occurrence discriminator, with deterministic code deriving codepoint offsets from the immutable source. That proposal must define a strict intermediate schema, unique/ambiguous/repeated-quote handling, no fuzzy matching/normalization, explicit adapter version, evidence-length rules, new tests and snapshot invalidation. Ambiguous/missing matches must block, not take the first occurrence. Compare it as a separately versioned offset experiment; do not conflate it with the A/B/C prompt test. The final validated API spans would remain codepoints unless the API contract is explicitly revised.

Provider constrained decoding is optional additional structure, not a semantic validator. For example, OpenAI's current Structured Outputs documentation requires a root object and supports only its documented JSON Schema subset; our root-array/full-conditional schema is **not** a drop-in configuration. Before an authorized integration, decide and document a provider wire envelope/schema projection and exact unwrap mapping under adapter/ADR review, or use plain JSON text plus strict local validation. Recheck the selected vendor/model's current support; do not silently discard local constraints. Provider refusal/incomplete-output handling also needs explicit adapter mapping. No such transport mapping is implemented or tested here. [Official Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)

## Predeclared comparison — not executed

All three arms share the same minimal task, trust boundary, output schema, user template and offset rules:

- **A — role label:** common baseline plus “expert keyboard catalog reviewer”.
- **B — explicit contract:** common baseline plus detailed evidence/scope/negation/unknown rules; no persona. Prepared candidate, not a measured winner.
- **C — simple baseline:** common minimal task, no role label or detailed decision checklist. It is not intentionally deprived of essential safety or output-format instructions.

A/C examines the role-label addition, with the small token-length difference disclosed. B/C examines the **bundled explicit-contract and length** change. B/A changes multiple factors and cannot identify a pure persona effect. No demographic identity, inflated experience claim, agent debate, self-score or majority vote is an accuracy measure. The role study in the existing research pack found no consistent overall benefit on its factual-question/model setting; it does not establish this task's outcome. [Zheng et al., EMNLP Findings 2024](https://aclanthology.org/2024.findings-emnlp.888/)

The concrete objective/output/source/tool/boundary variables follow the task-contract guidance in the existing vendor research source. That is a design rationale, not evidence that adding a runtime multi-agent system would help this two-condition task. The architecture remains one proposal adapter. [Anthropic's research-system engineering account](https://www.anthropic.com/research/multi-agent-research-system)

Before any authorized run, freeze exact provider/model version, supported decoding/reasoning settings, token/call budget, repetitions, independent evaluator manifest, arm-order schedule and stop rules. Unsupported seed/temperature parameters are recorded as unsupported, not presented as determinism. No settings were changed by these artifacts. Use the same source/conditions/language per case and rotate A/B/C order with a recorded reproducible schedule. Each call starts without other arm outputs or mutable conversation history. No automatic retries in the primary comparison; count refusals/timeouts/truncations as failures and retain the raw record. Any separately approved diagnostic retry must be reported outside the primary denominator and total cost.

## Separately proposed native-agent offline pilot

The parent may separately authorize a diagnostic, input-only pilot with 24 cases and one independent native agent per arm, requesting the same `gpt-6.1-sol` / `xhigh` setting. This preparation does not run it. Supply only that arm's system file, the common user template, the common output schema and input-only cases; keep gold labels and other-arm outputs private. A requested identical model/effort setting does not establish actual identical token/time budgets. A single-pass native-agent response file with uncontrolled usage is **not** a third-party provider API call, an integrated app adapter, a controlled A/B/C performance experiment or a reliability guarantee. Use any later recorded outputs only to find source-grounding/format failures and describe the actual invocation context, missing telemetry and input isolation limits. Its records/results belong in a separate pilot report; do not rewrite this frozen preparation as executed app evidence.

## Independent semantic evaluation and decision gate

The evaluator owns hidden cases/labels. Prompt authors must not read `eval/holdout` or another agent's corpus. These two public dev cases are excluded from holdout. Freeze prompt hashes **before** the evaluator reveals any private results. If labels leak or prompt changes after holdout feedback, retire that holdout for later promotion claims. No prompt-derived annotations or model self-grading substitute for independent evidence review.

Score case/condition results, reporting denominators and raw failures rather than a single blended success percentage:

1. JSON/schema pass; exact-span pass; completeness/condition-ID pass; blocked/refused/truncated rate.
2. Status confusion matrix and unsupported `match` count, separately for absent, negated, conditional, contradictory, wrong-scope and injected source text.
3. Evidence entails the status and retains decisive negation/conditions; exact quote alone earns no semantic credit. Report false conflicts and unnecessary unknowns too, so “always unknown” cannot win.
4. Token usage, latency, recorded full preparation/input/review/correction effort, all unsuccessful calls and any diagnostic retries. Account for B's longer input. Small synthetic samples do not prove population reliability.

Human/independent rubric adjudication is blinded to arm labels where practical. A disagreement stays recorded with the raw source/output and reason; do not modify a label merely to improve a score. Claim a prompt advantage only within the frozen evaluated cases/settings and with uncertainty/repetition limits visible. Any unsupported confident inclusion/layout or instruction-following failure blocks promotion pending diagnosis; an artifact preflight is not a release gate pass.

Keep a separate **good structured same-source table/checklist** as the product-value baseline. Comparing A/B/C tests prompts, not customer demand or AI usefulness. Measure the non-AI and AI flows using identical information and total preparation/input/review/correction effort with real authorized participants before claiming savings. If the good table is simpler or AI makes unsupported assertions, narrow or stop the AI path rather than weaken the baseline.

## Checks actually run / not run

The adjacent offline `verify_artifacts.py` checks schema validity, both authored examples against input/output schemas and existing `validate_proposal`, source hashes, template assembly, and malformed-output rejection. It also demonstrates the known semantic-validator gap without reading any evaluator corpus. See `PREFLIGHT.json` for exact command/result and file/dependency hashes. It never instantiates a real model/payment adapter or makes a network request. The pre-existing `jsonschema` 4.26.0 package was used only for this offline development check; no dependency was installed and the application remains unchanged. Ruff 0.14.3 `check` and `format --check` passed for `prompts/verify_artifacts.py` after formatting. No full runtime-suite rerun was needed or claimed for this prompt-only change.

**Not run:** real inference, provider schema acceptance, model offset accuracy, A/B/C calls, independent holdout performance, actual PayPal sandbox, live money, browser/customer study, publication or contest submission. No accuracy, time-saving or persona-effect score is claimed. Existing fixture/runtime test results do not become actual-model evidence.
