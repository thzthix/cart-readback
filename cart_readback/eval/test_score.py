"""Fabricated-output harness tests only: no observations of model quality."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import build_holdout
import score

ROOT = Path(__file__).resolve().parent


def provenance(candidate="HARNESS"):
    return {
        "run_id": f"fabricated-harness-{candidate}",
        "candidate_id": candidate,
        "prediction_kind": "fabricated_harness_test",
        "model": "NONE-no-model-called",
        "model_version": "NONE",
        "prompt_sha256": "unknown",
        "settings": {
            "temperature": "unknown",
            "seed": "unknown",
            "reasoning_effort": "unknown",
        },
        "budget": {
            "max_input_tokens": "unknown",
            "max_output_tokens": "unknown",
            "max_calls_per_case": 0,
        },
        "comparison_control": "uncontrolled_pilot",
        "trial_id": "harness-selftest-not-inference",
    }


class ScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs, cls.gold, cls.manifest = score.load_corpus()

    def predictions(self):
        rows = {}
        for case_id, gold in self.gold.items():
            results = []
            for expected in gold["results"]:
                result = copy.deepcopy(expected)
                result["explanation"] = result.pop("reason")
                results.append(result)
            rows[case_id] = {"case_id": case_id, "results": results}
        return rows

    def run_score(self, rows):
        return score.score_predictions(rows, [], provenance())

    def test_case_count_and_distribution_predeclared(self):
        self.assertEqual(len(self.inputs), 24)
        self.assertEqual(
            self.manifest["label_counts"],
            {"match": 16, "conflict": 16, "unknown": 16},
        )
        self.assertTrue(
            all(len(row["conditions"]) == 2 for row in self.inputs.values())
        )

    def test_inputs_contain_no_gold(self):
        for row in self.inputs.values():
            self.assertEqual(set(row), {"case_id", "source", "conditions"})
            self.assertTrue(row["source"]["text"].startswith("SYNTHETIC "))

    def test_builder_reproduces_frozen_data(self):
        inputs, gold = build_holdout.create_cases()
        self.assertEqual(inputs, list(self.inputs.values()))
        self.assertEqual(gold, list(self.gold.values()))

    def test_fabricated_oracle_is_harness_sanity_not_quality(self):
        report = self.run_score(self.predictions())
        self.assertEqual(report["summary"]["grounded_proxy_correct"], 48)
        self.assertEqual(report["summary"]["critical_false_match"], 0)
        self.assertEqual(
            report["provenance"]["prediction_kind"], "fabricated_harness_test"
        )
        self.assertFalse(report["provenance_verified_by_scorer"])

    def test_all_unknown_does_not_masquerade_as_utility(self):
        rows = self.predictions()
        for row in rows.values():
            for result in row["results"]:
                result.update(status="unknown", evidence=[])
        summary = self.run_score(rows)["summary"]
        self.assertEqual(summary["label_correct"], 16)
        self.assertEqual(summary["excess_abstain"], 32)
        self.assertEqual(summary["critical_false_match"], 0)
        self.assertTrue(summary["all_unknown_degenerate"])
        self.assertTrue(summary["zero_useful_decisive_results"])

    def test_all_match_has_32_critical_false_matches(self):
        rows = self.predictions()
        for case_id, row in rows.items():
            source = self.inputs[case_id]["source"]
            for result in row["results"]:
                result.update(
                    status="match",
                    evidence=[
                        {
                            "source_id": source["source_id"],
                            "start": 0,
                            "end": len(source["text"]),
                            "quote": source["text"],
                        }
                    ],
                )
        self.assertEqual(
            self.run_score(rows)["summary"]["critical_false_match"], 32
        )

    def test_false_match_even_with_invalid_quote_is_critical(self):
        rows = self.predictions()
        rows["CH004"]["results"][0].update(status="match", evidence=[])
        report = self.run_score(rows)
        self.assertEqual(report["summary"]["critical_false_match"], 1)
        self.assertFalse(
            report["cases"][3]["conditions"][0]["schema_source_quote_valid"]
        )

    def test_wrong_source_id_rejected(self):
        rows = self.predictions()
        rows["CH001"]["results"][0]["evidence"][0]["source_id"] = "foreign"
        self.assertEqual(
            self.run_score(rows)["summary"]["schema_valid_conditions"], 47
        )

    def test_forged_quote_rejected(self):
        rows = self.predictions()
        rows["CH001"]["results"][0]["evidence"][0]["quote"] = "invented"
        summary = self.run_score(rows)["summary"]
        self.assertEqual(summary["schema_valid_conditions"], 47)
        self.assertEqual(summary["raw_status_correct"], 48)
        self.assertEqual(summary["label_correct"], 47)

    def test_byte_and_utf16_offsets_rejected(self):
        for unit in ("utf-8", "utf-16-le"):
            with self.subTest(unit=unit):
                rows = self.predictions()
                span = rows["CH014"]["results"][0]["evidence"][0]
                text = self.inputs["CH014"]["source"]["text"]
                divisor = 2 if unit == "utf-16-le" else 1
                span["start"] = (
                    len(text[: span["start"]].encode(unit)) // divisor
                )
                span["end"] = span["start"] + len(span["quote"])
                self.assertEqual(
                    self.run_score(rows)["summary"]["schema_valid_conditions"],
                    47,
                )

    def test_combining_and_nbsp_are_not_normalized(self):
        self.assertIn("Cafe\u0301", self.inputs["CH022"]["source"]["text"])
        self.assertIn("DE\u00a0QWERTZ", self.inputs["CH024"]["source"]["text"])
        self.assertEqual(
            self.run_score(self.predictions())["summary"][
                "schema_valid_conditions"
            ],
            48,
        )

    def test_bool_is_not_offset_integer(self):
        rows = self.predictions()
        rows["CH001"]["results"][0]["evidence"][0]["start"] = True
        self.assertEqual(
            self.run_score(rows)["summary"]["schema_valid_conditions"], 47
        )

    def test_negative_reversed_and_out_of_bounds_spans_rejected(self):
        source = self.inputs["CH001"]["source"]
        span = self.predictions()["CH001"]["results"][0]["evidence"][0]
        for start, end in (
            (-1, 2),
            (3, 3),
            (4, 3),
            (0, len(source["text"]) + 1),
        ):
            with self.subTest(start=start, end=end):
                self.assertTrue(
                    score.span_errors(
                        {**span, "start": start, "end": end}, source
                    )
                )

    def test_correct_quote_wrong_semantics_not_fully_credited(self):
        rows = self.predictions()
        source = self.inputs["CH001"]["source"]
        rows["CH001"]["results"][0]["evidence"] = [
            {
                "source_id": source["source_id"],
                "start": 0,
                "end": 9,
                "quote": "SYNTHETIC",
            }
        ]
        summary = self.run_score(rows)["summary"]
        self.assertEqual(summary["label_correct"], 48)
        self.assertEqual(summary["grounded_proxy_correct"], 47)
        self.assertEqual(
            summary["valid_correct_label_missing_canonical_support"], 1
        )

    def test_unknown_can_have_no_evidence(self):
        rows = self.predictions()
        for row in rows.values():
            for result in row["results"]:
                if result["status"] == "unknown":
                    result["evidence"] = []
        self.assertEqual(
            self.run_score(rows)["summary"]["grounded_proxy_correct"], 48
        )

    def test_decisive_status_requires_evidence(self):
        rows = self.predictions()
        rows["CH001"]["results"][0]["evidence"] = []
        self.assertEqual(
            self.run_score(rows)["summary"]["schema_valid_conditions"], 47
        )

    def test_missing_case_counts_wrong_not_dropped_denominator(self):
        rows = self.predictions()
        del rows["CH001"]
        summary = self.run_score(rows)["summary"]
        self.assertEqual(summary["condition_count"], 48)
        self.assertEqual(summary["label_correct"], 46)
        self.assertEqual(summary["missing_case_count"], 1)

    def test_duplicate_condition_invalidates_whole_case(self):
        rows = self.predictions()
        rows["CH001"]["results"].append(
            copy.deepcopy(rows["CH001"]["results"][0])
        )
        self.assertEqual(
            self.run_score(rows)["summary"]["schema_valid_conditions"], 46
        )

    def test_duplicate_condition_cannot_hide_critical_false_match(self):
        rows = self.predictions()
        wrong = copy.deepcopy(rows["CH004"]["results"][0])
        wrong["status"] = "match"
        rows["CH004"]["results"].insert(0, wrong)
        self.assertEqual(
            self.run_score(rows)["summary"]["critical_false_match"], 1
        )

    def test_foreign_condition_or_extra_field_invalidates_case(self):
        for change in ("foreign", "extra"):
            rows = self.predictions()
            if change == "foreign":
                rows["CH001"]["results"][0]["condition_id"] = "c99"
            else:
                rows["CH001"]["paid"] = True
            self.assertEqual(
                self.run_score(rows)["summary"]["schema_valid_conditions"], 46
            )

    def test_empty_control_and_surrogate_explanations_rejected(self):
        invalid = [""] + [f"bad{chr(code)}text" for code in range(32)]
        invalid += ["bad\ud800text", "bad\udffftext", "bad\n"]
        for explanation in invalid:
            with self.subTest(explanation=repr(explanation)):
                rows = self.predictions()
                rows["CH001"]["results"][0]["explanation"] = explanation
                summary = self.run_score(rows)["summary"]
                self.assertEqual(summary["condition_count"], 48)
                self.assertEqual(summary["schema_valid_conditions"], 47)
                self.assertEqual(summary["raw_status_correct"], 48)
                self.assertEqual(summary["label_correct"], 47)

    def test_valid_unicode_explanation_boundaries_preserved(self):
        for explanation in ("x", "\uc124" * 500, "emoji \U0001f600", "DEL\x7f"):
            with self.subTest(explanation=repr(explanation)):
                rows = self.predictions()
                rows["CH001"]["results"][0]["explanation"] = explanation
                summary = self.run_score(rows)["summary"]
                self.assertEqual(summary["schema_valid_conditions"], 48)
                self.assertEqual(summary["label_correct"], 48)

    def test_explanation_span_count_and_status_constraints(self):
        base = self.predictions()["CH001"]["results"][0]
        source = self.inputs["CH001"]["source"]
        for changed in (
            {**base, "explanation": "x" * 501},
            {**base, "status": "MATCH"},
            {**base, "status": ["match"]},
            {**base, "evidence": base["evidence"] * 5},
            {**base, "evidence": None},
            {**base, "extra": "forbidden"},
        ):
            self.assertTrue(score.result_errors(changed, source))

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for value in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError):
                score.parse_json(value)

    def test_duplicate_and_malformed_jsonl_preserved_as_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external.jsonl"
            row = self.predictions()["CH001"]
            path.write_text(
                json.dumps(row) + "\n" + json.dumps(row) + "\nnot-json\n",
                "utf-8",
            )
            rows, errors = score.read_predictions(path)
            self.assertTrue(rows["CH001"]["_invalid_duplicate_case"])
            self.assertEqual(len(errors), 2)

    def test_duplicate_case_cannot_hide_false_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "external.jsonl"
            good = self.predictions()["CH004"]
            bad = copy.deepcopy(good)
            bad["results"][0]["status"] = "match"
            path.write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n")
            rows, errors = score.read_predictions(path)
            summary = score.score_predictions(rows, errors, provenance())[
                "summary"
            ]
            self.assertEqual(summary["schema_valid_cases"], 0)
            self.assertEqual(summary["critical_false_match"], 1)

    def test_foreign_case_reported(self):
        rows = self.predictions()
        rows["FOREIGN"] = {"case_id": "FOREIGN", "results": []}
        self.assertEqual(
            self.run_score(rows)["summary"]["foreign_case_count"], 1
        )

    def test_missing_model_budget_metadata_rejected(self):
        value = provenance()
        del value["budget"]
        with self.assertRaises(ValueError):
            score.validate_provenance(value)

    def test_uncontrolled_comparison_not_causal_winner(self):
        first = self.run_score(self.predictions())
        second = copy.deepcopy(first)
        second["provenance"] = provenance("OTHER")
        comparison = score.compare_reports([first, second])
        self.assertEqual(
            comparison["comparison_status"], "descriptive_only_uncontrolled"
        )
        self.assertNotIn("winner", comparison)

    def test_comparison_corpus_or_candidate_mismatch_rejected(self):
        first = self.run_score(self.predictions())
        with self.assertRaises(ValueError):
            score.compare_reports([first, copy.deepcopy(first)])
        second = copy.deepcopy(first)
        second["provenance"] = provenance("OTHER")
        second["input_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            score.compare_reports([first, second])

    def test_manifest_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(
                json.dumps({"sha256": {"holdout-inputs.jsonl": "0" * 64}})
            )
            (root / "holdout-inputs.jsonl").write_text("changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                score.load_corpus(root)

    def test_cli_validate_actual_subprocess(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "score.py"), "validate"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_cli_foreign_surrogate_id_retains_report_and_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "malformed-external.jsonl"
            predictions.write_text('{"case_id":"\\ud800","results":[]}\n')
            meta = root / "fabricated-provenance.json"
            meta.write_text(json.dumps(provenance()))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "score.py"),
                    "score",
                    str(predictions),
                    "--provenance",
                    str(meta),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["condition_count"], 48)
            self.assertEqual(report["summary"]["missing_case_count"], 24)
            self.assertEqual(report["summary"]["label_correct"], 0)
            self.assertTrue(report["input_errors"])
            self.assertIn("\\ud800", result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_cli_score_actual_subprocess_with_fabricated_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predictions = root / "fabricated-harness.jsonl"
            predictions.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in self.predictions().values()
                )
            )
            meta = root / "fabricated-provenance.json"
            meta.write_text(json.dumps(provenance()))
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "score.py"),
                    "score",
                    str(predictions),
                    "--provenance",
                    str(meta),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["summary"]["label_correct"], 48
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
