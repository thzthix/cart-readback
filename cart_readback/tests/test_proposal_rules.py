"""Public synthetic rejection-rule probes, never model evaluation or live calls."""

import copy
import json
import unittest

from cartreadback_app.gemini_client import (
    CURRENT_MODEL,
    GeminiClient,
    GeminiConfig,
    classify_gemini_usage,
)
from cartreadback_app.inference import PROPOSAL_RULES, rejection_rule
from cartreadback_app.validation import AppError, canonical
from test_gemini_client import envelope
from test_responses_adapter import domain


class ProposalRuleTests(unittest.TestCase):
    def setUp(self):
        self.source, self.conditions, self.results = domain()
        self.client = GeminiClient(
            GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
        )
        self.prepared = self.client.prepare(self.source, self.conditions)

    def probe(self, expected, outer=None, inner=None):
        value = envelope(copy.deepcopy(self.results))
        value["modelVersion"] = CURRENT_MODEL
        if outer:
            outer(value)
        if inner:
            wire = json.loads(
                value["candidates"][0]["content"]["parts"][0]["text"]
            )
            inner(wire)
            value["candidates"][0]["content"]["parts"][0]["text"] = canonical(
                wire
            )
        raw = canonical(value).encode()
        usage = classify_gemini_usage(raw, self.client.config)
        self.assertEqual(
            usage.accounting_contract, "no-explicit-profile-conflict"
        )
        with self.assertRaises(AppError) as caught:
            self.client.parse(self.prepared, raw)
        self.assertEqual(caught.exception.code, "INVALID_PROPOSAL")
        self.assertEqual(rejection_rule(caught.exception), expected)
        self.assertNotIn("synthetic:test", str(caught.exception))
        self.assertEqual(
            self.client.prepare(self.source, self.conditions), self.prepared
        )

    def test_envelope_and_json_rule_matrix(self):
        for rule, mutate in (
            (
                "RULE_CANDIDATE_INDEX",
                lambda v: v["candidates"][0].update(index=1),
            ),
            (
                "RULE_CONTENT",
                lambda v: v["candidates"][0]["content"].update(role="user"),
            ),
            (
                "RULE_CONTENT",
                lambda v: v["candidates"][0]["content"].update(extra=True),
            ),
            (
                "RULE_PARTS",
                lambda v: v["candidates"][0]["content"].update(parts=[]),
            ),
            (
                "RULE_SIGNATURE",
                lambda v: v["candidates"][0]["content"]["parts"][0].update(
                    thoughtSignature="%%%"
                ),
            ),
            (
                "RULE_OUTPUT_JSON",
                lambda v: v["candidates"][0]["content"]["parts"][0].update(
                    text="{"
                ),
            ),
        ):
            with self.subTest(rule=rule):
                self.probe(rule, outer=mutate)

    def test_proposal_rule_matrix(self):
        for rule, mutate in (
            ("RULE_ROOT_FIELDS", lambda v: v.update(extra=True)),
            ("RULE_ORDER", lambda v: v["results"].reverse()),
            ("RULE_COUNT", lambda v: v["results"].pop()),
            (
                "RULE_RESULT_FIELDS",
                lambda v: v["results"][0].update(extra=True),
            ),
            (
                "RULE_CONDITION_REFERENCE",
                lambda v: v["results"][0].update(condition_id="other"),
            ),
            (
                "RULE_RESULT_STATUS",
                lambda v: v["results"][0].update(status="accepted"),
            ),
            (
                "RULE_EXPLANATION",
                lambda v: v["results"][0].update(explanation="one\ntwo"),
            ),
            (
                "RULE_EVIDENCE_ARRAY",
                lambda v: v["results"][0].update(evidence={}),
            ),
            (
                "RULE_EVIDENCE_REQUIRED",
                lambda v: v["results"][0].update(evidence=[]),
            ),
            (
                "RULE_SPAN_FIELDS",
                lambda v: v["results"][0]["evidence"][0].update(extra=True),
            ),
            (
                "RULE_SPAN_QUOTE_FORMAT",
                lambda v: v["results"][0]["evidence"][0].update(quote=""),
            ),
            (
                "RULE_SPAN_START",
                lambda v: v["results"][0]["evidence"][0].update(start=-1),
            ),
            (
                "RULE_SPAN_END",
                lambda v: v["results"][0]["evidence"][0].update(end=0),
            ),
            (
                "RULE_SPAN_SOURCE",
                lambda v: v["results"][0]["evidence"][0].update(
                    source_id="other"
                ),
            ),
            (
                "RULE_SPAN_QUOTE",
                lambda v: v["results"][0]["evidence"][0].update(
                    quote="different"
                ),
            ),
            (
                "RULE_SPAN_QUOTE",
                lambda v: v["results"][0]["evidence"][0].update(start=0),
            ),
        ):
            with self.subTest(rule=rule):
                self.probe(rule, inner=mutate)

    def test_rule_metadata_cannot_contain_arbitrary_values(self):
        for value in (None, {}, [], True, "synthetic-private-detail", object()):
            error = AppError("INVALID_PROPOSAL", "not emitted")
            error.rejection_rule = value
            self.assertIsNone(rejection_rule(error))
        self.assertEqual(len(PROPOSAL_RULES), 26)

    def test_service_invalid_proposal_keeps_known_accounting(self):
        from test_gemini_service import GeminiServiceTests

        fixture = GeminiServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        wire = json.loads(
            fixture.state["body"]["candidates"][0]["content"]["parts"][0][
                "text"
            ]
        )
        wire["results"][0]["evidence"][0]["quote"] = "PUBLIC_INVALID_QUOTE"
        fixture.state["body"]["candidates"][0]["content"]["parts"][0][
            "text"
        ] = canonical(wire)
        checkout = fixture.flow.analyze()["checkout"]
        self.assertEqual(checkout["analysis_error"], "INVALID_PROPOSAL")
        self.assertEqual(
            checkout["analysis_diagnostic"],
            {
                "stage": "exchange-validation",
                "category": "RULE_SPAN_QUOTE",
                "http_status": 200,
            },
        )
        self.assertEqual(checkout["analysis"]["accounting_state"], "known")
        self.assertTrue(checkout["analysis"]["usage_observed"])
        self.assertEqual(checkout["state"], "ANALYSIS_BLOCKED")
        self.assertEqual(checkout["results"], [])
        self.assertEqual(fixture.state["calls"], 1)
        self.assertIsNotNone(
            fixture.rows("gemini_capacity_operations")[0]["reservation"]
        )
        self.assertNotIn("PUBLIC_INVALID_QUOTE", canonical(checkout))


class RuleIsolationTests(unittest.TestCase):
    def test_annotation_does_not_mutate_reused_validator_error(self):
        from cartreadback_app.inference import _at_proposal_rule

        original = AppError("INVALID_INPUT", "Fixed local message.", 400)

        def failing():
            raise original

        for rule in ("RULE_SPAN_START", "RULE_SPAN_END"):
            with self.assertRaises(AppError) as caught:
                _at_proposal_rule(rule, failing)
            self.assertIsNot(caught.exception, original)
            self.assertEqual(caught.exception.code, original.code)
            self.assertEqual(caught.exception.status, original.status)
            self.assertEqual(rejection_rule(caught.exception), rule)
            self.assertFalse(hasattr(original, "rejection_rule"))
