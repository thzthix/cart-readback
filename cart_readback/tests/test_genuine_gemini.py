"""Independent fabricated accounting and proposal acceptance boundaries."""

import copy
import dataclasses
import json
import socket
import unittest
from unittest import mock

from cartreadback_app.gemini_capacity import (
    GeminiCapacityPolicy,
    GeminiClaim,
    GeminiReservation,
    HostGeminiAuthorization,
)
from cartreadback_app.gemini_client import (
    CURRENT_MODEL,
    MODEL,
    GeminiClient,
    GeminiConfig,
    classify_gemini_usage,
)
from cartreadback_app.gemini_runtime import (
    ApprovedDataScope,
    CredentialBinding,
    FabricatedTransportBinding,
    GeminiAnalysisRuntime,
    InstalledGeminiContext,
    ProviderTransportBinding,
    execution_identity,
    host_provenance,
)
from cartreadback_app.genuine_gemini import GenuineGeminiAdapter
from cartreadback_app.validation import AppError, canonical, digest, text_hash
from test_gemini_client import envelope
from test_responses_adapter import domain
from test_responses_http import FakeConnection, FakeResponse


class IndependentGeminiAccountingTests(unittest.TestCase):
    def setUp(self):
        self.source, self.conditions, self.results = domain()
        self.config = GeminiConfig(MODEL)
        self.client = GeminiClient(self.config)
        self.prepared = self.client.prepare(self.source, self.conditions)
        self.value = envelope(self.results)

    def raw(self):
        return canonical(self.value).encode()

    def usage(self):
        return classify_gemini_usage(self.raw(), self.config)

    def test_valid_usage_contains_no_text_or_raw_identifiers(self):
        accounting = self.usage()
        self.assertEqual(
            (100, 20, 120),
            (
                accounting.input_tokens,
                accounting.output_tokens,
                accounting.total_tokens,
            ),
        )
        self.assertEqual(64, len(accounting.response_id_sha256))
        self.assertNotIn("fabricated_response", repr(accounting))
        self.assertNotIn("proposal", accounting.__dict__)

    def test_refusal_retains_accounting(self):
        self.value["promptFeedback"] = {"blockReason": "SAFETY"}
        self.value.pop("candidates")
        self.assertEqual(100, self.usage().input_tokens)
        with self.assertRaises(AppError) as caught:
            self.client.parse(self.prepared, self.raw())
        self.assertEqual("MODEL_REFUSED", caught.exception.code)

    def test_invalid_json_proposal_retains_accounting(self):
        self.value["candidates"][0]["content"]["parts"][0]["text"] = "not json"
        self.assertEqual(20, self.usage().output_tokens)
        with self.assertRaises(AppError):
            self.client.parse(self.prepared, self.raw())

    def test_invalid_span_retains_accounting(self):
        results = copy.deepcopy(self.results)
        results[0]["evidence"][0]["quote"] = "not source text"
        self.value = envelope(results)
        self.assertEqual(120, self.usage().total_tokens)
        with self.assertRaises(AppError):
            self.client.parse(self.prepared, self.raw())

    def test_incomplete_proposal_retains_accounting(self):
        self.value["candidates"][0]["finishReason"] = "MAX_TOKENS"
        self.assertEqual("completed", self.usage().response_status)
        with self.assertRaises(AppError) as caught:
            self.client.parse(self.prepared, self.raw())
        self.assertEqual("MODEL_INCOMPLETE", caught.exception.code)

    def test_wrong_model_has_no_accounting(self):
        self.value["modelVersion"] = CURRENT_MODEL
        with self.assertRaises(AppError):
            self.usage()

    def test_contradictory_counts_have_no_accounting(self):
        self.value["usageMetadata"]["totalTokenCount"] += 1
        with self.assertRaises(AppError):
            self.usage()

    def test_35_thoughts_are_billed_output(self):
        self.config = GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
        self.value["modelVersion"] = CURRENT_MODEL
        self.value["usageMetadata"].update(
            thoughtsTokenCount=17, totalTokenCount=137
        )
        usage = self.usage()
        self.assertEqual(
            (20, 17, 37),
            (usage.candidate_tokens, usage.thought_tokens, usage.output_tokens),
        )
        self.value["usageMetadata"].update(
            thoughtsTokenCount=2048, totalTokenCount=2168
        )
        with self.assertRaises(AppError):
            self.usage()

    def test_25_thoughts_contradict_contract(self):
        self.value["usageMetadata"].update(
            thoughtsTokenCount=1, totalTokenCount=121
        )
        with self.assertRaises(AppError):
            self.usage()

    def test_tool_activity_is_not_known_contract(self):
        self.value["candidates"][0]["content"]["parts"] = [
            {"functionCall": {"name": "unapproved", "args": {}}}
        ]
        self.assertEqual(
            "unsupported-provider-activity", self.usage().accounting_contract
        )

    def test_signatures_are_never_in_accounting(self):
        self.value["candidates"][0]["content"]["parts"][0][
            "thoughtSignature"
        ] = "ZmFicmljYXRlZC1zaWduYXR1cmU="
        self.assertNotIn("Signature", json.dumps(self.usage().__dict__))

    def test_duplicate_envelope_key_has_no_accounting(self):
        raw = b'{"modelVersion":"other",' + self.raw()[1:]
        with self.assertRaises(AppError):
            classify_gemini_usage(raw, self.config)


class GenuineGeminiAdapterTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("network")
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.source, self.conditions, self.results = domain()
        self.events = []
        self.raw = canonical(envelope(self.results)).encode()
        self.response = FakeResponse(self.raw)
        self.connection = FakeConnection(self.response, self.events)
        self.factory = mock.Mock(return_value=self.connection)
        binding = CredentialBinding("synthetic_project", "v1", "host1")
        config = GeminiConfig(MODEL, "ko")
        transport = FabricatedTransportBinding(self.factory)
        policy = GeminiCapacityPolicy(
            90,
            200,
            MODEL,
            MODEL,
            1048576,
            1,
            1,
            binding.project,
            "synthetic_tier",
            "a" * 64,
            "b" * 64,
        )
        scope = ApprovedDataScope(
            ("c" * 64,), (digest(self.conditions),), (text_hash("owner"),)
        )
        auth = HostGeminiAuthorization(
            "d" * 64,
            host_provenance("e" * 64, "b" * 64, "fabricated-offline"),
            digest(dataclasses.asdict(scope)),
            execution_identity(binding, config, transport=transport),
            text_hash(policy.identity),
            90,
            200,
            1,
            1048576,
            2048,
            10,
        )
        self.handle = mock.Mock()
        self.handle.binding = binding
        self.handle.borrow.return_value = "synthetic-key"
        self.installed = InstalledGeminiContext(
            binding,
            scope,
            policy,
            auth,
            "e" * 64,
            "b" * 64,
            self.handle,
            transport,
            config,
        )
        self.runtime = GeminiAnalysisRuntime(self.installed)
        self.adapter = GenuineGeminiAdapter(self.runtime, lambda: 100)
        self.prepared = self.adapter.prepare(self.source, self.conditions)
        self.claim = GeminiClaim(
            GeminiReservation(
                "operation",
                self.prepared.request_sha256,
                "f" * 64,
                "a" * 64,
                1048576,
                2048,
                3,
            ),
            "claim",
            120,
        )
        self.guard = mock.Mock(return_value=None)

    def exchange(self):
        return self.adapter.exchange(
            self.prepared,
            self.claim,
            self.adapter.deadline(self.claim),
            claim_guard=self.guard,
        )

    def test_prepare_is_offline_and_exact_gemini_wire(self):
        self.factory.assert_not_called()
        self.handle.borrow.assert_not_called()
        self.assertIn("generationConfig", json.loads(self.prepared.request))
        self.assertEqual(
            "ko", json.loads(self.prepared.inputs_json)["response_language"]
        )

    def test_actual_transport_composition_guards_and_classifies(self):
        exchange = self.exchange()
        self.assertGreater(self.guard.call_count, 5)
        self.handle.borrow.assert_called_once()
        self.assertEqual("fabricated-offline", exchange.evidence_kind)
        self.assertEqual(1, self.connection.closed)
        self.assertEqual(1, self.response.closed)
        self.assertEqual(
            (False, "", self.results),
            self.adapter.classify(
                exchange, self.installed.policy, self.prepared
            ),
        )
        requests = [event for event in self.events if event[0] == "request"]
        self.assertEqual(1, len(requests))
        self.assertIn("gemini-2.5-flash-lite", requests[0][2])

    def test_missing_or_rejecting_guard_has_no_effect(self):
        with self.assertRaises(AppError):
            self.adapter.exchange(
                self.prepared, self.claim, self.adapter.deadline(self.claim)
            )
        self.guard.side_effect = AppError("BLOCKED", "Blocked", 503)
        with self.assertRaises(AppError):
            self.exchange()
        self.factory.assert_not_called()
        self.handle.borrow.assert_not_called()

    def test_replaced_factory_rejected_before_effects(self):
        self.adapter.runtime = GeminiAnalysisRuntime(
            self.installed, connection_factory=mock.Mock()
        )
        with self.assertRaises(AppError):
            self.exchange()
        self.factory.assert_not_called()
        self.handle.borrow.assert_not_called()

    def test_provider_binding_cannot_accept_arbitrary_factory(self):
        binding = ProviderTransportBinding("host1")
        self.assertIsNot(binding.factory, self.factory)
        with self.assertRaises(TypeError):
            ProviderTransportBinding("host1", factory=self.factory)

    def test_original_classification_survives_runtime_removal(self):
        exchange = self.exchange()
        self.adapter.runtime = GeminiAnalysisRuntime()
        self.assertEqual(
            (False, "", self.results),
            self.adapter.classify(
                exchange, self.installed.policy, self.prepared
            ),
        )

    def test_changed_credential_binding_denies_before_constructor(self):
        self.handle.binding = dataclasses.replace(
            self.installed.binding, credential_version="v2"
        )
        with self.assertRaises(AppError):
            self.exchange()
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
