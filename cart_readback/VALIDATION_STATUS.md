# Evaluation status at this import

**Offline tooling, not a validated AI + PayPal application.** The issue #6 import
originally stacked on server PR #4 at `d2781cf7f603d83b552c9cd84371544357589bdd`.
This integrated tree also includes the buyer UI. Original component reviews and
fresh exact-head integration review/checks are recorded in PR #8; this file
cannot contain its own final commit hash. Historical tables below describe the
original evaluation import, not automatic certification of later integration.

## Read the historical artifacts correctly

The unchanged `eval/README.md` and prompt evaluation plan record preparation-time
statements. The versioned manifest retains that historical metadata while binding
current imported tooling (see the migration note below). A later **app-external, uncontrolled native-agent
pilot** used the synthetic set. It is now an **exposed regression set**, not a
fresh hidden holdout. No new model run or scoring of pilot outputs occurs in this
import. Archived pilot/review records and old harness logs are deliberately not
shipped; their historical numeric observations are not republished as a leaderboard.

The corpus remains 24 authored synthetic cases / 48 buyer conditions, balanced
16 `match`, 16 `conflict`, 16 `unknown`. Inputs, gold labels and the gold-bearing
builder remain separate files only as a **process discipline**, not secure access
control. All are accessible in this private repository; future promotion claims
need a fresh unexposed set and independently reviewed execution protocol.
The frozen README mentions historical harness receipts that are not imported.
Their absence is intentional; current checks are recorded on the actual PR head.

## What current checks can establish

- The dependency-free scorer checks a fixed denominator, missing/duplicate/foreign
  rows, schema/types, source identity, exact Unicode-codepoint quotes and offsets.
  Its 34 fabricated-output tests exercise tooling, not model quality (31 original
  tests plus three regression tests from the review fixes).
- Canonical gold-span containment is a deterministic **proxy**, not entailment.
  Broad quotes may pass and valid alternate supporting spans may fail. Explanation
  truth, completeness and buyer understanding are not verified by the scorer.
- Always-UNKNOWN can avoid false matches but loses decisive results and is flagged
  as degenerate. The tool emits no causal prompt winner or product acceptance.
- Prompt preflight checks two public authored development examples and malformed
  outputs. It deliberately observes a synthetic false cable `match` passing both
  local schema and exact-span validation. No model produced that counterexample.
- The prompt schema is a full local root-array contract, **not** a provider wire
  request. Provider schema acceptance, envelope/unwrap and refusal/truncation
  handling need a separately reviewed adapter. Prepared candidate B is not a
  performance winner; no adapter is implemented here.

## Fresh author checks of this assembled artifact

Python 3.12.14 and already-available development-only `jsonschema` 4.26.0 were used;
no dependency was installed and runtime requirements are unchanged.

| Check | Observed result |
| --- | --- |
| `python eval/score.py validate` | Exit 0; original corpus and current tooling hashes valid |
| Scorer unittest discovery | Exit 0; 34 tests passed |
| `python prompts/verify_artifacts.py` | Exit 0; regenerated `PREFLIGHT.json` binds imported dependencies |
| Prompt `sha256sum -c SHA256SUMS` | Exit 0; all 10 entries match |
| Compile eval/prompts/server/tests/scripts/review | Exit 0 |
| Domain/HTTP unittest discovery | Exit 0; 41 tests passed |
| Imported independent Python discovery | Exit 0; 29 tests passed; author rerun is not separate-worker review |
| Ruff 0.14.3 lint across Python components | Exit 0 |
| Ruff 0.14.3 aggregate format check | Exit 0; all 19 Python files formatted |

An initial format check exited 1 on three pre-existing files. After a separate
worker checked compatibility, Ruff formatted only `eval/build_holdout.py`,
`eval/score.py` and `eval/test_score.py`; **that formatting phase** had identical
Python ASTs to source and was bound by manifest 1.0.1. Its exact phase hashes and
unchanged original bytes remain in the local review archive.

A distinct separate-worker review then found two correctness defects:

1. The scorer/wrapper accepted empty, control-character and surrogate explanations
   that the app rejects. The scorer now matches that text policy; the wrapper uses
   nonempty/length bounds and a forbidden-character search, not a `$` anchor that
   could miss a trailing LF. Two tests cover all 32 controls, trailing LF,
   surrogates and valid Unicode/length boundaries.
2. A foreign case ID containing a JSON-escaped lone surrogate crashed CLI report
   printing. JSON report output now ASCII-escapes strings without changing their
   parsed values. A subprocess test retains the error and all 48 denominator
   conditions instead of emitting a traceback.

**Dataset version stays 1.0.0; current manifest version is 1.0.2.** The manifest
binds changed tool/schema bytes, retains the formatting-phase manifest hash and
original tool/schema hashes, and identifies original manifest SHA-256
`aebd3463ffcc6a08eb4c7a71dfcdc8e451269c4b11992ae67873c7c5180e40a3`.
Input/gold, labels, metric definitions and all prompt/template/schema/plan bytes
remain unchanged. Validation eligibility intentionally differs for the defective
strings, so old external outputs must not be silently regraded as original-version
results. The original corpus/manifest validation passed before migration.

The frozen prompt schema's anchored explanation regex alone can accept trailing
LF in the local validator; the required app postcheck rejects it. Prompt schema
bytes are preserved, not relabeled a complete standalone API validator.

Preflight code differs only by replacing inaccurate "Human-authored"
counterexample attribution with "Author-constructed synthetic"; its receipt and
checksums were regenerated, not reused as current evidence.

## Open gates

Fresh separate-worker review/reruns are required after integration changes; see
PR #8 for the actual fixed revision and disposition.
Real application inference, provider API/schema acceptance, fresh semantic-quality
validation, actual PayPal sandbox lifecycle/recovery, rendered browser/accessibility
flows and customer benefit versus the good same-source non-AI table are **not run**.
These checks incur no inference charges or payment calls. The owner separately
authorized current project PR merges. No formal APPROVE, independent-account
approval, deployment/public-release/license or contest-submission authority is
implied by either the checks or a merge.
