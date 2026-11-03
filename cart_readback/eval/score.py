"""Score external CartReadback JSONL predictions offline; never run a model."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATUSES = {"match", "conflict", "unknown"}
LAYOUTS = {"UK_QWERTY", "DE_QWERTZ", "US_QWERTY"}
CABLES = {"USB-C to USB-C", "USB-A to USB-C", "any cable"}
RESULT_KEYS = {"condition_id", "status", "explanation", "evidence"}
SPAN_KEYS = {"source_id", "start", "end", "quote"}


def sha256(path: Path) -> str:
    """Return SHA-256 of exact file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def parse_json(text: str) -> Any:
    """Parse strict JSON, rejecting duplicate keys and NaN/Infinity."""
    return json.loads(
        text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def read_jsonl(path: Path) -> list:
    """Read strict nonblank JSONL; data validation fails rather than repairs."""
    return [
        parse_json(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def span_errors(span: Any, source: dict) -> list[str]:
    """Validate exact Unicode-code-point source identity and span slicing."""
    if type(span) is not dict or set(span) != SPAN_KEYS:
        return ["span_fields"]
    errors = []
    if span["source_id"] != source["source_id"]:
        errors.append("source_id")
    start, end, quote = span["start"], span["end"], span["quote"]
    if type(start) is not int or type(end) is not int:
        return errors + ["span_integer_type"]
    if not 0 <= start < end <= len(source["text"]):
        return errors + ["span_bounds"]
    if type(quote) is not str or not 0 < len(quote) <= 1000:
        return errors + ["quote_type_or_length"]
    if source["text"][start:end] != quote:
        errors.append("quote_mismatch")
    return errors


def result_errors(result: Any, source: dict) -> list[str]:
    """Check the API's result schema without interpreting explanation prose."""
    if type(result) is not dict or set(result) != RESULT_KEYS:
        return ["result_fields"]
    errors = []
    if type(result["condition_id"]) is not str:
        errors.append("condition_id_type")
    if type(result["status"]) is not str or result["status"] not in STATUSES:
        errors.append("status_enum")
    explanation = result["explanation"]
    if (
        type(explanation) is not str
        or not 1 <= len(explanation) <= 500
        or any(
            ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF
            for char in explanation
        )
    ):
        errors.append("explanation_type_length_or_character")
    evidence = result["evidence"]
    if type(evidence) is not list or len(evidence) > 4:
        return errors + ["evidence_type_or_count"]
    if result["status"] in ("match", "conflict") and not evidence:
        errors.append("decisive_without_evidence")
    for span in evidence:
        errors.extend(span_errors(span, source))
    return errors


def load_corpus(root: Path = ROOT) -> tuple[dict, dict, dict]:
    """Load and validate the frozen synthetic corpus and manifest hashes."""
    manifest = parse_json((root / "manifest.json").read_text("utf-8"))
    for filename, expected_hash in manifest["sha256"].items():
        if sha256(root / filename) != expected_hash:
            raise ValueError(f"manifest hash mismatch: {filename}")
    inputs = read_jsonl(root / "holdout-inputs.jsonl")
    gold = read_jsonl(root / "holdout-gold.jsonl")
    by_id, expected = {}, {}
    distribution = Counter()
    for row in inputs:
        if type(row) is not dict or set(row) != {
            "case_id",
            "source",
            "conditions",
        }:
            raise ValueError("input fields")
        case_id, source, conditions = (
            row["case_id"],
            row["source"],
            row["conditions"],
        )
        if type(case_id) is not str or case_id in by_id:
            raise ValueError("input case identity")
        if set(source) != {"source_id", "revision", "sha256", "text"}:
            raise ValueError("source fields")
        text = source["text"]
        if not text.startswith("SYNTHETIC catalog record. "):
            raise ValueError("source not explicitly synthetic")
        if (
            len(text) > 16000
            or source["sha256"]
            != hashlib.sha256(text.encode("utf-8")).hexdigest()
        ):
            raise ValueError("source hash or length")
        if type(source["revision"]) is not int or source["revision"] < 1:
            raise ValueError("source revision")
        if not 1 <= len(conditions) <= 2:
            raise ValueError("condition count")
        kinds, ids = set(), set()
        for condition in conditions:
            if set(condition) != {"condition_id", "kind", "value"}:
                raise ValueError("condition fields")
            if condition["condition_id"] in ids or condition["kind"] in kinds:
                raise ValueError("duplicate condition")
            ids.add(condition["condition_id"])
            kinds.add(condition["kind"])
            allowed = LAYOUTS if condition["kind"] == "layout" else CABLES
            if condition["kind"] not in ("layout", "included_cable") or (
                condition["value"] not in allowed
            ):
                raise ValueError("condition enum")
        by_id[case_id] = row
    for row in gold:
        case_id = row["case_id"]
        if (
            case_id not in by_id
            or case_id in expected
            or row["synthetic"] is not True
        ):
            raise ValueError("gold case identity/provenance")
        wanted = {item["condition_id"] for item in by_id[case_id]["conditions"]}
        actual = [item["condition_id"] for item in row["results"]]
        if set(actual) != wanted or len(actual) != len(wanted):
            raise ValueError("gold condition identity")
        for result in row["results"]:
            candidate = {**result, "explanation": result["reason"]}
            del candidate["reason"]
            if not result["reason"] or result_errors(
                candidate, by_id[case_id]["source"]
            ):
                raise ValueError(f"invalid gold: {case_id}")
            distribution[result["status"]] += 1
        expected[case_id] = row
    if set(by_id) != set(expected):
        raise ValueError("missing gold cases")
    if (
        len(by_id) != manifest["case_count"]
        or dict(distribution) != manifest["label_counts"]
    ):
        raise ValueError("manifest counts")
    return by_id, expected, manifest


def read_predictions(path: Path) -> tuple[dict, list[str]]:
    """Read external predictions, retaining malformed/duplicate row failures."""
    predictions, errors = {}, []
    for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = parse_json(line)
        except (ValueError, TypeError) as error:
            errors.append(f"line {number}: {error}")
            continue
        if type(row) is not dict or type(row.get("case_id")) is not str:
            errors.append(f"line {number}: missing string case_id")
            continue
        case_id = row["case_id"]
        if case_id in predictions:
            previous = predictions[case_id]
            accumulated = []
            for repeated in (previous, row):
                if type(repeated.get("results")) is list:
                    accumulated.extend(repeated["results"])
            # Preserve all recognizable match attempts, but invalidate the case.
            predictions[case_id] = {
                "case_id": case_id,
                "results": accumulated,
                "_invalid_duplicate_case": True,
            }
            errors.append(f"line {number}: duplicate case_id {case_id}")
        else:
            predictions[case_id] = row
    return predictions, errors


def validate_provenance(value: Any) -> dict:
    """Require run/model/budget metadata; unknown means uncontrolled, not zero."""
    required = {
        "run_id",
        "candidate_id",
        "prediction_kind",
        "model",
        "model_version",
        "prompt_sha256",
        "settings",
        "budget",
        "comparison_control",
        "trial_id",
    }
    if type(value) is not dict or not required <= set(value):
        raise ValueError("provenance missing required run/model/budget fields")
    if any(
        type(value[key]) is not str or not value[key]
        for key in required - {"settings", "budget"}
    ):
        raise ValueError("provenance scalar fields must be nonempty strings")
    if value["prediction_kind"] not in {
        "actual_model",
        "model_agent_pilot",
        "external_baseline",
        "fabricated_harness_test",
        "unspecified_external",
    }:
        raise ValueError("prediction_kind enum")
    if value["comparison_control"] not in {"controlled", "uncontrolled_pilot"}:
        raise ValueError("comparison_control enum")
    if type(value["settings"]) is not dict or not {
        "temperature",
        "seed",
        "reasoning_effort",
    } <= set(value["settings"]):
        raise ValueError(
            "settings metadata required; use unknown if unavailable"
        )
    if type(value["budget"]) is not dict or not {
        "max_input_tokens",
        "max_output_tokens",
        "max_calls_per_case",
    } <= set(value["budget"]):
        raise ValueError("budget metadata required; use unknown if unavailable")
    return value


def _support_covered(evidence: list, gold_spans: list) -> bool:
    # Canonical-span containment is a transparent proxy, not an entailment model.
    return all(
        any(
            span["start"] <= required["start"]
            and span["end"] >= required["end"]
            for span in evidence
        )
        for required in gold_spans
    )


def score_predictions(
    predictions: dict,
    parse_errors: list[str],
    provenance: dict,
    root: Path = ROOT,
) -> dict:
    """Score statuses, schema, source quotes and a canonical-evidence proxy.

    Unknown can have no evidence. Explanation truth and alternative correct
    evidence require independent review and are not silently called verified.
    """
    provenance = validate_provenance(provenance)
    inputs, gold, manifest = load_corpus(root)
    errors = list(parse_errors)
    extra = sorted(set(predictions) - set(inputs))
    errors.extend(f"foreign case_id: {case_id}" for case_id in extra)
    counts = Counter()
    confusion = {
        actual: {
            pred: 0 for pred in ("match", "conflict", "unknown", "invalid")
        }
        for actual in ("match", "conflict", "unknown")
    }
    details = []
    for case_id, case in inputs.items():
        row = predictions.get(case_id)
        row_errors = []
        results = {}
        raw_match_ids = set()
        if type(row) is not dict or set(row) != {"case_id", "results"}:
            row_errors.append("missing_case_or_row_fields")
        if type(row) is dict and type(row.get("results")) is list:
            for result in row["results"]:
                if (
                    type(result) is not dict
                    or type(result.get("condition_id")) is not str
                ):
                    row_errors.append("result_identity")
                    continue
                condition_id = result["condition_id"]
                if result.get("status") == "match":
                    raw_match_ids.add(condition_id)
                if condition_id in results:
                    row_errors.append("duplicate_condition_id")
                results[condition_id] = result
        else:
            row_errors.append("results_not_array")
        wanted = {item["condition_id"] for item in case["conditions"]}
        if set(results) != wanted or (
            type(row) is dict
            and isinstance(row.get("results"), list)
            and len(row["results"]) != len(wanted)
        ):
            row_errors.append("condition_id_set_or_count")
        all_valid = not row_errors
        case_correct = True
        condition_details = []
        for expected in gold[case_id]["results"]:
            condition_id, actual = expected["condition_id"], expected["status"]
            candidate = results.get(condition_id)
            validation = list(row_errors)
            validation.extend(result_errors(candidate, case["source"]))
            valid = not validation
            all_valid = all_valid and valid
            raw_status = (
                candidate.get("status") if type(candidate) is dict else None
            )
            predicted = (
                raw_status
                if type(raw_status) is str and raw_status in STATUSES
                else "invalid"
            )
            confusion[actual][predicted] += 1
            counts["condition_count"] += 1
            counts["schema_valid_conditions"] += valid
            counts["raw_status_correct"] += predicted == actual
            label_correct = valid and predicted == actual
            counts["label_correct"] += label_correct
            canonical = valid and (
                actual == "unknown"
                or _support_covered(candidate["evidence"], expected["evidence"])
            )
            grounded_proxy_correct = label_correct and canonical
            counts["grounded_proxy_correct"] += grounded_proxy_correct
            case_correct = case_correct and grounded_proxy_correct
            false_match = condition_id in raw_match_ids and actual != "match"
            counts["critical_false_match"] += false_match
            counts["predicted_unknown"] += predicted == "unknown"
            counts["appropriate_unknown"] += (
                valid and predicted == actual == "unknown"
            )
            counts["excess_abstain"] += (
                predicted == "unknown" and actual != "unknown"
            )
            counts["correct_decisive"] += (
                grounded_proxy_correct and actual != "unknown"
            )
            counts["valid_correct_label_missing_canonical_support"] += (
                label_correct and not canonical
            )
            condition_details.append(
                {
                    "condition_id": condition_id,
                    "expected_status": actual,
                    "predicted_status": predicted,
                    "schema_source_quote_valid": valid,
                    "validation_errors": sorted(set(validation)),
                    "label_correct": label_correct,
                    "canonical_support_covered": canonical,
                    "grounded_proxy_correct": grounded_proxy_correct,
                    "critical_false_match": false_match,
                }
            )
        counts["schema_valid_cases"] += all_valid
        counts["all_conditions_correct_cases"] += case_correct
        details.append({"case_id": case_id, "conditions": condition_details})
    n = counts["condition_count"]
    summary = {
        name: counts[name]
        for name in (
            "condition_count",
            "schema_valid_conditions",
            "schema_valid_cases",
            "raw_status_correct",
            "label_correct",
            "grounded_proxy_correct",
            "critical_false_match",
            "predicted_unknown",
            "appropriate_unknown",
            "excess_abstain",
            "correct_decisive",
            "valid_correct_label_missing_canonical_support",
            "all_conditions_correct_cases",
        )
    }
    summary.update(
        {
            "case_count": len(inputs),
            "missing_case_count": len(set(inputs) - set(predictions)),
            "foreign_case_count": len(extra),
            "parse_or_identity_error_count": len(errors),
            "status_accuracy": counts["raw_status_correct"] / n,
            "label_accuracy": counts["label_correct"] / n,
            "grounded_proxy_accuracy": counts["grounded_proxy_correct"] / n,
            "abstention_rate": counts["predicted_unknown"] / n,
            "all_unknown_degenerate": counts["predicted_unknown"] == n,
            "zero_useful_decisive_results": counts["correct_decisive"] == 0,
        }
    )
    return {
        "report_version": "1.0.0",
        "dataset_version": manifest["dataset_version"],
        "input_sha256": manifest["sha256"]["holdout-inputs.jsonl"],
        "gold_sha256": manifest["sha256"]["holdout-gold.jsonl"],
        "provenance": provenance,
        "provenance_verified_by_scorer": False,
        "model_inference_executed_by_scorer": False,
        "scope": "offline synthetic scoring; not app integration or user-value evidence",
        "evidence_limit": "canonical-span containment proxy; explanation entailment not verified",
        "summary": summary,
        "confusion": confusion,
        "input_errors": errors,
        "cases": details,
    }


def compare_reports(reports: list[dict]) -> dict:
    """Describe same-corpus candidates; do not infer a winner or causal effect."""
    if len(reports) < 2:
        raise ValueError("comparison needs at least two reports")
    first = reports[0]
    shared_keys = ("input_sha256", "gold_sha256", "dataset_version")
    if any(
        any(row[key] != first[key] for key in shared_keys) for row in reports
    ):
        raise ValueError("comparison corpus mismatch")
    candidates = [row["provenance"]["candidate_id"] for row in reports]
    if len(candidates) != len(set(candidates)):
        raise ValueError("candidate IDs must be distinct within one trial")
    reasons = []
    for row in reports:
        meta = validate_provenance(row["provenance"])
        if meta["comparison_control"] != "controlled":
            reasons.append("declared uncontrolled pilot")
        if meta["prediction_kind"] != "actual_model":
            reasons.append("not verified actual API-model experiment")
        if (
            "unknown"
            in json.dumps(
                {
                    key: meta[key]
                    for key in (
                        "model",
                        "model_version",
                        "settings",
                        "budget",
                        "prompt_sha256",
                    )
                }
            ).lower()
        ):
            reasons.append("unknown budget/model/settings metadata")
        if row["summary"]["schema_valid_cases"] != row["summary"]["case_count"]:
            reasons.append("incomplete or malformed outputs")
        if row["summary"]["parse_or_identity_error_count"]:
            reasons.append("input identity errors")
    for key in ("model", "model_version", "settings", "budget", "trial_id"):
        if any(
            row["provenance"][key] != first["provenance"][key]
            for row in reports
        ):
            reasons.append(f"different {key}")
    return {
        "comparison_version": "1.0.0",
        "dataset_version": first["dataset_version"],
        "comparison_status": "descriptive_only_uncontrolled"
        if reasons
        else "declared_same_budget_unverified",
        "limitations": sorted(set(reasons))
        + [
            "Caller metadata is not verified; scorer does not execute models.",
            "Synthetic small-set observations do not establish user value or causal improvement.",
            "No automatic winner, threshold tuning, or prompt selection is performed.",
        ],
        "candidates": [
            {
                "candidate_id": row["provenance"]["candidate_id"],
                "run_id": row["provenance"]["run_id"],
                "summary": row["summary"],
            }
            for row in reports
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Run validate, score or compare without network or model dependencies."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "validate", help="validate frozen corpus and file hashes"
    )
    score_parser = commands.add_parser(
        "score", help="score external JSONL only"
    )
    score_parser.add_argument("predictions", type=Path)
    score_parser.add_argument("--provenance", type=Path, required=True)
    compare_parser = commands.add_parser(
        "compare", help="compare external score reports"
    )
    compare_parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            inputs, _, manifest = load_corpus()
            report = {
                "valid": True,
                "dataset_version": manifest["dataset_version"],
                "case_count": len(inputs),
                "label_counts": manifest["label_counts"],
            }
        elif args.command == "score":
            predictions, errors = read_predictions(args.predictions)
            provenance = parse_json(args.provenance.read_text("utf-8"))
            report = score_predictions(predictions, errors, provenance)
            report["prediction_file_sha256"] = sha256(args.predictions)
            report["provenance_file_sha256"] = sha256(args.provenance)
        else:
            report = compare_reports(
                [parse_json(path.read_text("utf-8")) for path in args.reports]
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    # External IDs/provenance may contain escaped lone surrogates. Keep their
    # diagnostic values without emitting unencodable Unicode to stdout.
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
