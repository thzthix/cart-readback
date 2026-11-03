"""Independent offline probes; synthetic inputs are not real-model evidence."""

import unittest

from cartreadback_app.catalog import fixtures, validate_product
from cartreadback_app.inference import (
    FixtureInferenceAdapter,
    validate_proposal,
)
from cartreadback_app.validation import AppError, conditions, parse_json


class IndependentSourceTests(unittest.TestCase):
    """Exercise the documented domain boundary independently of author tests."""

    def test_all_six_catalog_entries_validate_including_multiline_text(self):
        products = fixtures()
        self.assertEqual(6, len(products))
        self.assertEqual(6, len({item["sku_id"] for item in products}))
        for product in products:
            with self.subTest(sku=product["sku_id"]):
                validate_product(product)

    def test_layout_is_language_not_physical_geometry(self):
        for layout in ("UK_QWERTY", "DE_QWERTZ", "US_QWERTY"):
            with self.subTest(layout=layout):
                self.assertEqual(
                    [{"kind": "layout", "value": layout}],
                    conditions([{"kind": "layout", "value": layout}]),
                )
        for geometry in ("ISO", "ANSI"):
            with self.subTest(geometry=geometry), self.assertRaises(AppError):
                conditions([{"kind": "layout", "value": geometry}])

    def test_german_layout_cannot_match_uk_requirement(self):
        product = next(
            p for p in fixtures() if p["baseline"]["layout"] == "DE_QWERTZ"
        )
        result = FixtureInferenceAdapter().propose(
            product["source"],
            [{"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"}],
        )
        self.assertEqual("conflict", result[0]["status"])
        self.assertTrue(result[0]["evidence"])

    def test_absent_cable_fact_stays_unknown(self):
        products = [
            p
            for p in fixtures()
            if "unknown" in p["baseline"]["included_cable"].lower()
        ]
        self.assertTrue(products)
        for product in products:
            with self.subTest(sku=product["sku_id"]):
                result = FixtureInferenceAdapter().propose(
                    product["source"],
                    [
                        {
                            "condition_id": "c1",
                            "kind": "included_cable",
                            "value": "any cable",
                        }
                    ],
                )
                self.assertEqual("unknown", result[0]["status"])

    def test_source_instructions_do_not_override_cable_conflict(self):
        product = next(
            p
            for p in fixtures()
            if "UNTRUSTED INSTRUCTION" in p["source"]["text"]
        )
        result = FixtureInferenceAdapter().propose(
            product["source"],
            [
                {
                    "condition_id": "c1",
                    "kind": "included_cable",
                    "value": "USB-A to USB-C",
                }
            ],
        )
        self.assertEqual("conflict", result[0]["status"])

    def test_unicode_spans_are_codepoints_and_wrong_source_is_rejected(self):
        source = {"source_id": "synthetic:unicode", "text": "🛒 UK QWERTY"}
        condition = [{"condition_id": "c1"}]
        proposal = [
            {
                "condition_id": "c1",
                "status": "match",
                "explanation": "Fixture.",
                "evidence": [
                    {
                        "source_id": source["source_id"],
                        "start": 2,
                        "end": 11,
                        "quote": "UK QWERTY",
                    }
                ],
            }
        ]
        self.assertEqual(
            proposal, validate_proposal(source, condition, proposal)
        )
        proposal[0]["evidence"][0]["source_id"] = "synthetic:wrong-sku"
        with self.assertRaises(AppError):
            validate_proposal(source, condition, proposal)

    def test_span_booleans_out_of_range_and_missing_evidence_are_rejected(self):
        source = {"source_id": "synthetic:probe", "text": "fact"}
        condition = [{"condition_id": "c1"}]
        for start, end, quote in (
            (False, 4, "fact"),
            (0, 5, "fact"),
            (0, 4, "wrong"),
            (4, 4, ""),
        ):
            proposal = [
                {
                    "condition_id": "c1",
                    "status": "match",
                    "explanation": "Fixture.",
                    "evidence": [
                        {
                            "source_id": source["source_id"],
                            "start": start,
                            "end": end,
                            "quote": quote,
                        }
                    ],
                }
            ]
            with (
                self.subTest(start=start, end=end),
                self.assertRaises(AppError),
            ):
                validate_proposal(source, condition, proposal)
        with self.assertRaises(AppError):
            validate_proposal(
                source,
                condition,
                [
                    {
                        "condition_id": "c1",
                        "status": "match",
                        "explanation": "Fixture.",
                        "evidence": [],
                    }
                ],
            )

    def test_parser_rejects_duplicate_keys_nonfinite_depth_and_bad_unicode(
        self,
    ):
        cases = [
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
            b'{"a":' + b"[" * 20 + b"0" + b"]" * 20 + b"}",
            b'{"a":"\xff"}',
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(AppError):
                parse_json(raw)


if __name__ == "__main__":
    unittest.main()
