# CartReadback semantic-grounding holdout v1

**24 synthetic, predeclared cases / 48 buyer conditions**: 16 `match`, 16
`conflict`, 16 `unknown`. Two conditions per case; no customer/interview data.
This is evaluation preparation, **not an actual-model inference experiment,
app integration test, model-quality result, or user-value validation**.

Blair's evaluation worker authored these cases from `API_CONTRACT.md` and
`PROJECT_BRIEF.md`, without reading app fixture expectations or prompt
candidates. The author is itself an AI worker and may be able to answer the
cases; its authorship and the fabricated self-tests are not independent model
inference observations. Applicable repository instructions were also read.

## Files and separation

- `holdout-inputs.jsonl`: **only** `case_id`, `source`, `conditions`. Every
  source text explicitly labels itself synthetic. Exact source-byte SHA-256
  and Unicode code-point spans are used; no normalization.
- `holdout-gold.jsonl`: separate labels, canonical supporting/context spans,
  reasons, synthetic provenance and coverage tags. **Do not give to prompt
  authors, implementers tuning prompts, or an input-only pilot runner.**
- `build_holdout.py`: reproducible authoring file containing gold; same access
  discipline as gold. It does not automatically re-freeze the manifest.
- `score.py`: dependency-free Python 3.11+ offline scorer. It has no model,
  credential, payment, HTTP, app-client, or network integration.
- `test_score.py`: fabricated-output **harness tests**, not quality scores.
- `predictions.schema.json`: external JSONL wrapper contract; Python also
  enforces condition identity, exact source quotes and code-point offsets.
- `provenance.example.json`: required run/model/budget fields; use `unknown`
  instead of inventing controls or token usage.
- `manifest.json`: dataset version, predeclared counts, freeze metadata and
  SHA-256 of corpus and tooling. Hash mismatch fails closed.
- `harness-selftest-results.json` / `.log`: actual offline check records tied
  to the manifest hash, not model predictions or a quality leaderboard.

These are ordinary **shared-workspace files**. This separation is a process
instruction, not an immutable/hidden/secure holdout guarantee. Prompt and
implementation workers were instructed not to read them. Record any access,
gold sharing, or unexpected prompt exposure as leakage; do not claim that
filesystem secrecy or model-training decontamination was proven.

## Coverage and labeling policy (fixed before predictions)

All three language/keycap layouts; ISO/ANSI physical-geometry traps; cable
inclusion versus compatibility, pictured accessory, explicit exclusion,
missing facts, unresolved contradiction, negation, optional/conditional
inclusion, selected versus other SKU, source prompt injection, emoji,
combining accents, nonbreaking spaces and punctuation.

`match` needs explicit positive evidence for the selected SKU. `conflict`
needs explicit exclusion or a clearly incompatible single-valued fact/complete
only-item list. Another cable being mentioned alone does **not** logically
exclude a requested second cable. `unknown` applies to missing, ambiguous,
contradictory or unresolved conditional facts. Physical ISO is not UK;
compatibility, ports and product photos do not establish included items.
Unknown contextual quotes do not turn absence into proof of non-inclusion.

## Actual offline commands

Run from `cart_readback/` (no packages to install):

```sh
python eval/score.py validate
python -m unittest discover -s eval -p 'test_score.py' -v
python -m compileall -q eval
```

Score **external** predictions; the scorer never generates predictions:

```sh
python eval/score.py score /path/to/external-predictions.jsonl \
  --provenance /path/to/run-provenance.json > /path/to/score-report.json
python eval/score.py compare /path/to/A-report.json \
  /path/to/B-report.json /path/to/C-report.json > /path/to/comparison.json
```

A prediction line is `{"case_id":"...","results":[...]}`. The results array
uses exactly the API result keys `condition_id`, `status`, `explanation`,
`evidence`; each evidence item uses `source_id`, `start`, `end`, `quote`.
Results cover each supplied condition exactly once. A runner may put a model's
bare-array result inside this wrapper, **without editing/repairing it**. JSONL
order may differ. Missing cases remain in the fixed denominator; duplicate
case IDs are invalidated rather than cherry-picked. Malformed JSON/duplicate
keys, foreign IDs, extra fields, invalid scalars/spans and source mismatches
are reported. No quote/offset repair, fallback answer or retry is performed.

Exit 0 means scoring/validation completed, **not model quality passed**. Exit
2 means corpus/provenance/I/O/command validation failed. Per-prediction
failures are retained in a completed score report rather than dropping cases.

## How to read results honestly

- `status_accuracy`: raw exact predeclared status, separate from formatting.
- `label_accuracy`: exact predeclared status and schema/source-quote validity.
- `critical_false_match`: every proposed `match` against gold `conflict` or
  `unknown`, including recognizable false-match attempts in malformed rows.
- `grounded_proxy_accuracy`: correct status plus canonical gold span
  containment for decisive labels. Source quotes must be exact. Unknown may
  have no evidence under the API contract.
- `correct_decisive`, `excess_abstain`, `appropriate_unknown`, abstention rate,
  confusion matrix and fixed-denominator counts prevent “always unknown”
  from looking useful simply because it has zero false matches.
- `all_unknown_degenerate` and `zero_useful_decisive_results` explicitly flag
  that degenerate strategy. No weighted utility score or tuned threshold is
  invented, and no automatic winner/product acceptance gate is emitted.

Canonical support containment is only a **transparent deterministic proxy**:
valid quotations alone are not semantic entailment. An equally good alternate
short span can fail the proxy; a broad quote can pass it. The scorer does not
judge explanation truth, completeness, misleading extra text, prompt-injection
resistance beyond this set, or real buyer understanding. Preserve raw outputs
for independent, blinded semantic review; report proxy and review separately.
Never call this a complete semantic verifier.

## Future A/B/C comparison (not run here)

Candidate IDs are neutral opaque prompt IDs, not UI/user-study arms. Candidate
definitions are maintained independently by the prompt worker; this author
did not inspect them. Before inference, freeze prompts and hashes, corpus,
model/version, identical settings and total input/output/call budgets,
per-case fresh context, trial IDs, scoring policy and attempted-run ledger.
Use identical source/conditions, case ordering or a fixed recorded shuffle,
one first response per case and no output repair or selective retry. Log all
attempts, errors, raw outputs, actual token usage/latency where available and
budget exhaustion. Compare all candidates, not only the best run. The
strong non-AI table/checklist baseline and complete preparation/input/review/
correction effort belong to a separate future user-value study.

`compare` checks corpus identity, distinct candidate IDs and supplied
model/settings/budget/trial metadata. Unknown controls or an agent pilot are
labeled `descriptive_only_uncontrolled`; a matched metadata declaration is
still `declared_same_budget_unverified`, never verified causality. The scorer
cannot enforce the budgets or verify caller-provided provenance. An input-only
independent agent pilot must use `prediction_kind: model_agent_pilot`, not
`actual_model`, and `comparison_control: uncontrolled_pilot` when budgets are
not controlled. It is not a provider-API or app integration test.

Do not edit cases, gold, thresholds or prompts after seeing results and keep
calling this held out. Fix factual ambiguities with an explicit version bump,
change reason, preserved old results and a fresh unexposed holdout for future
claims. Do not rerun candidates until a favorable seed appears. No actual
model, agent pilot, A/B/C comparison, PayPal sandbox, customer interview or
user-value study was executed by this evaluation worker.
