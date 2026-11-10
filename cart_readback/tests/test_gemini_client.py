"""Fabricated Gemini envelopes; no real provider, credential or billing evidence."""

import dataclasses
import json
import socket
import time
import unittest
from unittest import mock

from cartreadback_app.gemini_client import (
    CURRENT_MODEL,
    ENDPOINT,
    MAX_OUTPUT_TOKENS,
    MODEL,
    GeminiClient,
    GeminiConfig,
    classify_gemini_usage,
)
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.validation import AppError, canonical
from test_responses_adapter import domain


def client():
    return GeminiClient(GeminiConfig(MODEL))


def envelope(results):
    return {
        "modelVersion": MODEL,
        "responseId": "fabricated_response",
        "candidates": [
            {
                "index": 0,
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [{"text": canonical({"results": results})}],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "totalTokenCount": 120,
        },
    }


def encoded(value):
    return canonical(value).encode("utf-8")


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("real network prohibited"),
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.client = client()
        self.source, self.conditions, self.results = domain()
        self.prepared = self.client.prepare(self.source, self.conditions)
        self.value = envelope(self.results)

    def parse(self, value=None):
        return self.client.parse(
            self.prepared, encoded(self.value if value is None else value)
        )

    def assert_error(self, function, code=None):
        with self.assertRaises(AppError) as caught:
            function()
        if code is not None:
            self.assertEqual(code, caught.exception.code)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_exact_request_and_unchanged_prompt(self):
        body = json.loads(self.prepared.body)
        self.assertEqual(
            {"systemInstruction", "contents", "generationConfig"}, set(body)
        )
        self.assertEqual(
            self.client.bundle.system,
            body["systemInstruction"]["parts"][0]["text"],
        )
        self.assertEqual("user", body["contents"][0]["role"])
        self.assertEqual(1, len(body["contents"]))
        config = body["generationConfig"]
        self.assertEqual({"thinkingBudget": 0}, config["thinkingConfig"])
        self.assertEqual(1, config["candidateCount"])
        self.assertEqual(MAX_OUTPUT_TOKENS, config["maxOutputTokens"])
        self.assertEqual("application/json", config["responseMimeType"])
        self.assertEqual(
            json.loads(self.client.bundle.wire_schema_json),
            config["responseJsonSchema"],
        )
        self.assertNotIn("tools", body)
        self.assertNotIn("propose", dir(self.client))
        self.assertEqual(
            "client-unselected", self.client.metadata["execution_mode"]
        )
        self.assertEqual(
            self.prepared, self.client.prepare(self.source, self.conditions)
        )

    def test_repeated_visible_parts_keep_exact_json_validation(self):
        candidate = self.value["candidates"][0]
        text = candidate["content"]["parts"][0]["text"]
        candidate.pop("index")
        candidate["avgLogprobs"] = -0.1
        self.value["promptFeedback"] = {"safetyRatings": []}
        self.value["usageMetadata"]["cachedContentTokenCount"] = 0
        candidate["content"]["parts"] = [
            {"text": text[:12], "thoughtSignature": "ZmFrZQ=="},
            {"text": text[12:], "thought": False},
        ]
        self.assertEqual(self.results, self.parse().results)
        self.assertNotIn("ZmFrZQ==", repr(self.parse()))
        for extra in (
            {"text": "{}", "thought": True},
            {"inlineData": {"mimeType": "image/png", "data": "ZmFrZQ=="}},
            {"functionCall": {"name": "fake"}},
            {"text": "", "thoughtSignature": "not base64"},
        ):
            with self.subTest(extra=extra):
                candidate["content"]["parts"].append(extra)
                self.assert_error(self.parse, "INVALID_PROPOSAL")
                candidate["content"]["parts"].pop()

    def test_repeated_parts_do_not_relax_domain_evidence(self):
        self.results[0]["evidence"][0]["quote"] = "WRONG"
        text = canonical({"results": self.results})
        self.value["candidates"][0]["content"]["parts"] = [
            {"text": text[:12]},
            {"text": text[12:]},
        ]
        self.assert_error(self.parse, "INVALID_PROPOSAL")

    def test_incomplete_omitted_zero_output_retains_only_usage(self):
        current = GeminiClient(GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL))
        prepared = current.prepare(self.source, self.conditions)
        self.value["modelVersion"] = CURRENT_MODEL
        self.value["candidates"][0].update(finishReason="MAX_TOKENS")
        self.value["candidates"][0].pop("content")
        usage = self.value["usageMetadata"]
        usage.pop("candidatesTokenCount")
        usage.update(thoughtsTokenCount=7, totalTokenCount=107)
        observed = classify_gemini_usage(encoded(self.value), current.config)
        self.assertEqual(
            (0, 7, 107),
            (
                observed.candidate_tokens,
                observed.output_tokens,
                observed.total_tokens,
            ),
        )
        self.assert_error(
            lambda: current.parse(prepared, encoded(self.value)),
            "MODEL_INCOMPLETE",
        )
        usage["totalTokenCount"] = 120
        self.assert_error(
            lambda: classify_gemini_usage(encoded(self.value), current.config),
            "MODEL_BUDGET_EXCEEDED",
        )

    def test_omission_is_not_null_or_missing_accounting(self):
        for field, value in (
            ("candidatesTokenCount", None),
            ("candidatesTokenCount", True),
            ("candidatesTokenCount", -1),
        ):
            with self.subTest(field=field, value=value):
                data = envelope(self.results)
                data["usageMetadata"][field] = value
                self.assert_error(
                    lambda: classify_gemini_usage(
                        encoded(data), self.client.config
                    ),
                    "MODEL_BUDGET_EXCEEDED",
                )
        for field in ("promptTokenCount", "totalTokenCount"):
            data = envelope(self.results)
            data["usageMetadata"].pop(field)
            self.assert_error(
                lambda: classify_gemini_usage(
                    encoded(data), self.client.config
                ),
                "MODEL_BUDGET_EXCEEDED",
            )

    def test_success_and_no_mutable_result_alias(self):
        observation = self.parse()
        self.assertEqual(self.results, observation.results)
        self.assertEqual(
            (100, 20, 120),
            (
                observation.input_tokens,
                observation.output_tokens,
                observation.total_tokens,
            ),
        )
        self.assertEqual(
            self.prepared.request_sha256, observation.request_sha256
        )
        observation.results.clear()
        self.assertEqual(self.results, observation.results)
        self.assertEqual(MODEL, observation.model_returned)

    def test_current_lite_contract_includes_thoughts_in_output(self):
        current = GeminiClient(GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL))
        prepared = current.prepare(self.source, self.conditions)
        body = json.loads(prepared.body)
        self.assertEqual(
            {"thinkingLevel": "MINIMAL"},
            body["generationConfig"]["thinkingConfig"],
        )
        value = envelope(self.results)
        value["modelVersion"] = CURRENT_MODEL
        value["usageMetadata"].update(thoughtsTokenCount=7, totalTokenCount=127)
        observation = current.parse(prepared, encoded(value))
        self.assertEqual(
            (20, 7, 27, 127),
            (
                observation.candidate_tokens,
                observation.thought_tokens,
                observation.output_tokens,
                observation.total_tokens,
            ),
        )
        self.assertEqual(CURRENT_MODEL, observation.model_requested)
        self.assertIn(CURRENT_MODEL, current.metadata["endpoint"])
        value["usageMetadata"]["totalTokenCount"] = 120
        self.assert_error(
            lambda: current.parse(prepared, encoded(value)),
            "MODEL_BUDGET_EXCEEDED",
        )
        value["usageMetadata"].update(
            thoughtsTokenCount=2048, totalTokenCount=2168
        )
        self.assert_error(
            lambda: current.parse(prepared, encoded(value)),
            "MODEL_BUDGET_EXCEEDED",
        )
        self.assert_error(lambda: GeminiConfig(CURRENT_MODEL))

    def test_read_only_config_prevents_identity_drift(self):
        with self.assertRaises(AttributeError):
            self.client.config = GeminiConfig(MODEL + "-different")
        with self.assertRaises(AttributeError):
            self.client.bundle = None
        self.assertEqual(self.results, self.parse().results)

    def test_final_text_signature_is_validated_and_discarded(self):
        current = GeminiClient(GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL))
        prepared = current.prepare(self.source, self.conditions)
        value = envelope(self.results)
        value["modelVersion"] = CURRENT_MODEL
        part = value["candidates"][0]["content"]["parts"][0]
        signature = "c3ludGhldGljLXNpZ25hdHVyZQ=="
        part.update(thoughtSignature=signature, thought=False)
        observation = current.parse(prepared, encoded(value))
        self.assertEqual(self.results, observation.results)
        self.assertNotIn(signature, repr(observation))
        self.assertNotIn(signature, prepared.body.decode())
        for bad in (None, True, "not base64", "", "a" * 65_537):
            part["thoughtSignature"] = bad
            self.assert_error(
                lambda: current.parse(prepared, encoded(value)),
                "INVALID_PROPOSAL",
            )
        part["thoughtSignature"] = signature
        part["thought"] = True
        self.assert_error(
            lambda: current.parse(prepared, encoded(value)), "INVALID_PROPOSAL"
        )

    def test_contradictory_error_is_not_success(self):
        self.value["error"] = {"message": "SECRET"}
        self.assert_error(self.parse, "MODEL_UNAVAILABLE")

    def test_cache_tool_details_cannot_contradict_zero_counters(self):
        for key in (
            "cacheTokensDetails",
            "toolUsePromptTokensDetails",
            "unrecognizedTokensDetails",
        ):
            for details in (
                "SECRET",
                [{"modality": "IMAGE", "tokenCount": 100}],
                [{"modality": "TEXT", "tokenCount": 50}],
            ):
                with self.subTest(key=key, details=details):
                    value = envelope(self.results)
                    value["usageMetadata"][key] = details
                    self.assert_error(
                        lambda: self.parse(value), "MODEL_BUDGET_EXCEEDED"
                    )

    def test_wrong_config_and_forged_request_block_before_transport(self):
        for changed in (
            dataclasses.replace(self.prepared, body=b"{}"),
            dataclasses.replace(self.prepared, config_sha256="a" * 64),
            dataclasses.replace(self.prepared, inputs_json="{}"),
        ):
            with self.subTest(changed=changed):
                self.assert_error(
                    lambda: self.client.parse(changed, encoded(self.value)),
                    "MODEL_UNAVAILABLE",
                )
        self.assert_error(
            lambda: GeminiConfig("gemini-2.5-flash-lite\r\nSECRET")
        )
        self.assert_error(lambda: GeminiConfig(MODEL, "unsupported"))
        other = GeminiClient(GeminiConfig(MODEL, "ko"))
        self.assert_error(
            lambda: other.parse(self.prepared, encoded(self.value))
        )

    def test_model_and_response_identity_must_be_actual_and_exact(self):
        for key, bad in (
            ("modelVersion", "gemini-other"),
            ("modelVersion", None),
            ("responseId", "SECRET\n"),
            ("responseId", None),
        ):
            with self.subTest(key=key, value=bad):
                value = envelope(self.results)
                value[key] = bad
                self.assert_error(lambda: self.parse(value), "INVALID_PROPOSAL")

    def test_usage_is_required_bounded_and_not_boolean(self):
        for key, bad in (
            ("promptTokenCount", None),
            ("promptTokenCount", -1),
            ("promptTokenCount", True),
            ("promptTokenCount", 1_048_577),
            ("candidatesTokenCount", 2049),
            ("totalTokenCount", 121),
            ("thoughtsTokenCount", 1),
            ("cachedContentTokenCount", 1),
            ("toolUsePromptTokenCount", 1),
            ("newTokenCount", 1),
        ):
            with self.subTest(key=key, value=bad):
                value = envelope(self.results)
                value["usageMetadata"][key] = bad
                self.assert_error(
                    lambda: self.parse(value), "MODEL_BUDGET_EXCEEDED"
                )
        self.value.pop("usageMetadata")
        self.assert_error(self.parse, "MODEL_BUDGET_EXCEEDED")

    def test_supported_zero_counters_and_text_details(self):
        self.value["usageMetadata"].update(
            {
                "thoughtsTokenCount": 0,
                "cachedContentTokenCount": 0,
                "toolUsePromptTokenCount": 0,
                "promptTokensDetails": [
                    {"modality": "TEXT", "tokenCount": 100}
                ],
                "candidatesTokensDetails": [
                    {"modality": "TEXT", "tokenCount": 20}
                ],
            }
        )
        self.assertEqual(self.results, self.parse().results)
        self.value["usageMetadata"]["promptTokensDetails"][0]["modality"] = (
            "IMAGE"
        )
        self.assert_error(self.parse, "MODEL_BUDGET_EXCEEDED")

    def test_refusal_truncation_multiple_candidates_never_unknown_success(self):
        for mutate in (
            lambda value: value.update(
                promptFeedback={"blockReason": "SAFETY"}
            ),
            lambda value: value["candidates"][0].update(
                finishReason="MAX_TOKENS"
            ),
            lambda value: value["candidates"][0].update(finishReason="SAFETY"),
            lambda value: value["candidates"].append(value["candidates"][0]),
            lambda value: value["candidates"][0].update(
                safetyRatings=[{"blocked": True}]
            ),
            lambda value: value["candidates"][0].update(index=True),
        ):
            value = envelope(self.results)
            mutate(value)
            self.assert_error(lambda: self.parse(value))

    def test_tool_thought_empty_and_extra_parts_rejected(self):
        for parts in (
            [{"functionCall": {"name": "SECRET", "args": {}}}],
            [{"text": "{}", "thought": True}],
            [{"text": "{}", "thoughtSignature": "SECRET"}],
            [{"text": "{}"}, {"text": "{}"}],
            [],
            [{"text": None}],
            [{"text": ""}],
        ):
            with self.subTest(parts=parts):
                self.value["candidates"][0]["content"]["parts"] = parts
                self.assert_error(self.parse)

    def test_existing_domain_and_exact_span_validation_applies(self):
        for mutate in (
            lambda results: results[0].update(condition_id="wrong"),
            lambda results: results[0].update(status="approved"),
            lambda results: results[0]["evidence"][0].update(quote="SECRET"),
            lambda results: results[0].update(extra="SECRET"),
            lambda results: results.reverse(),
        ):
            results = json.loads(canonical(self.results))
            mutate(results)
            self.assert_error(
                lambda: self.parse(envelope(results)), "INVALID_PROPOSAL"
            )

    def test_duplicate_invalid_utf8_nonfinite_and_excessive_depth(self):
        for raw in (
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b'{"a":"\xff"}',
            b'{"a":' + b"[" * 33 + b"0" + b"]" * 33 + b"}",
            b" " * 131_073,
        ):
            self.assert_error(lambda: self.client.parse(self.prepared, raw))

    def test_explicit_synchronous_exchange_and_sanitized_transport_error(self):
        calls = []
        parent = self

        class Transport:
            def send(self, endpoint, body, *, deadline):
                calls.append((endpoint, body))
                return encoded(parent.value)

        self.client.transport = Transport()
        self.assertEqual(
            self.results,
            self.client.exchange(
                self.prepared, deadline=Deadline(time.monotonic() + 3, 1, 1)
            ).results,
        )
        self.assertEqual([(ENDPOINT, self.prepared.body)], calls)
        self.client.transport.send = mock.Mock(side_effect=ValueError("SECRET"))
        self.assert_error(
            lambda: self.client.exchange(
                self.prepared, deadline=Deadline(time.monotonic() + 3, 1, 1)
            ),
            "MODEL_UNAVAILABLE",
        )
        self.assert_error(
            lambda: self.client.exchange(
                self.prepared, deadline=Deadline(time.monotonic() - 1, 1, 1)
            ),
            "MODEL_TIMEOUT",
        )


if __name__ == "__main__":
    unittest.main()
