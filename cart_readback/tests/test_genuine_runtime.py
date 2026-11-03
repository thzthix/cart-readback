"""Pure identity/denial checks, never genuine-provider or account evidence."""

import dataclasses
import hashlib
import inspect
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from cartreadback_app import genuine_runtime
from cartreadback_app.genuine_runtime import (
    GenuineRuntimeCapability,
    GenuineRuntimeIdentity,
)
from cartreadback_app.inference_config import InferenceConfig, load_bundle
from cartreadback_app.responses_adapter import OfflineResponsesAdapter
from cartreadback_app.validation import AppError, digest, text_hash


class HostileString(str):
    def __eq__(self, other):
        raise AssertionError("Untrusted equality invoked")


class GenuineRuntimeTests(unittest.TestCase):
    def test_identity_is_distinct_and_deterministic(self):
        identity = GenuineRuntimeIdentity()
        self.assertNotIsInstance(identity, InferenceConfig)
        self.assertEqual(identity, GenuineRuntimeIdentity())
        self.assertEqual(identity.metadata, GenuineRuntimeIdentity().metadata)
        self.assertEqual(
            identity.metadata["kind"], "unselected-genuine-runtime-plan"
        )
        self.assertNotIn("is_fixture", identity.metadata)
        document = identity.metadata
        fingerprint = document.pop("runtime_identity_sha256")
        self.assertEqual(fingerprint, digest(document))
        identity.require_same_identity(fingerprint)

    def test_deep_metadata_copy_cannot_mutate_identity_or_capability(self):
        identity = GenuineRuntimeIdentity()
        original = identity.metadata
        edited = identity.metadata
        edited["credential_binding"]["verified_project_reference"] = "claimed"
        edited["capability"]["available"] = True
        edited["capability"]["blockers"].clear()
        edited["request_contract"]["tools"].append({"type": "function"})
        self.assertEqual(identity.metadata, original)
        self.assertFalse(identity.capability.available)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.route = "pythonanywhere"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.capability.available = True
        self.assertFalse(hasattr(identity, "__dict__"))

    def test_supported_language_and_route_changes_stale_identity(self):
        original = GenuineRuntimeIdentity()
        fingerprint = original.metadata["runtime_identity_sha256"]
        hashes = set()
        for language in ("en", "ko"):
            for route in ("direct", "pythonanywhere"):
                candidate = GenuineRuntimeIdentity(language, route)
                value = candidate.metadata["runtime_identity_sha256"]
                hashes.add(value)
                if candidate != original:
                    with self.assertRaises(AppError) as caught:
                        candidate.require_same_identity(fingerprint)
                    self.assertEqual(
                        caught.exception.code,
                        "GENUINE_RUNTIME_IDENTITY_MISMATCH",
                    )
        self.assertEqual(len(hashes), 4)

    def test_all_policy_revisions_and_host_versions_are_bound(self):
        fingerprint = GenuineRuntimeIdentity().metadata[
            "runtime_identity_sha256"
        ]
        revisions = (
            "_IDENTITY_REVISION",
            "_REQUEST_REVISION",
            "_COUNT_REVISION",
            "_TRANSPORT_REVISION",
            "_CREDENTIAL_REVISION",
            "_PRICING_REVISION",
            "_AUTHORIZATION_REVISION",
            "PARSER_VERSION",
        )
        for name in revisions:
            with self.subTest(name=name):
                with mock.patch.object(genuine_runtime, name, "new-revision"):
                    candidate = GenuineRuntimeIdentity()
                self.assertNotEqual(
                    candidate.metadata["runtime_identity_sha256"], fingerprint
                )
        with mock.patch.object(
            genuine_runtime.sys, "version_info", (3, 99, 0, "final", 0)
        ):
            candidate = GenuineRuntimeIdentity()
        self.assertNotEqual(
            candidate.metadata["runtime_identity_sha256"], fingerprint
        )
        with mock.patch.object(
            genuine_runtime.ssl, "OPENSSL_VERSION_INFO", (9, 9, 9, 9, 9)
        ):
            candidate = GenuineRuntimeIdentity()
        self.assertNotEqual(
            candidate.metadata["runtime_identity_sha256"], fingerprint
        )

    def test_every_document_value_participates_in_digest(self):
        identity = GenuineRuntimeIdentity()
        original = identity.metadata
        fingerprint = original.pop("runtime_identity_sha256")

        def check_values(value, path=()):
            if type(value) is dict:
                for key, child in value.items():
                    check_values(child, (*path, key))
                return
            mutated = json.loads(json.dumps(original))
            target = mutated
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = {"changed": value}
            self.assertNotEqual(digest(mutated), fingerprint, path)

        check_values(original)

    def test_bad_enums_have_sanitized_errors_without_callback_execution(self):
        callback = mock.Mock(side_effect=AssertionError("called"))
        secret = "synthetic-not-a-real-secret-marker"
        for value in (True, 1, None, [], {}, callback, HostileString("direct")):
            for name in ("response_language", "route"):
                with self.subTest(name=name, value_type=type(value).__name__):
                    with self.assertRaises(AppError) as caught:
                        GenuineRuntimeIdentity(**{name: value})
                    self.assertEqual(
                        caught.exception.code, "GENUINE_RUNTIME_INVALID"
                    )
        for name in ("response_language", "route"):
            with self.assertRaises(AppError) as caught:
                GenuineRuntimeIdentity(**{name: secret})
            self.assertNotIn(secret, repr(caught.exception))
        callback.assert_not_called()

    def test_endpoint_model_account_and_proof_overrides_not_supported(self):
        allowed = set(inspect.signature(GenuineRuntimeIdentity).parameters)
        self.assertEqual(allowed, {"response_language", "route"})
        unsupported = {
            "endpoint": "https://untrusted.invalid/v1/responses",
            "model": "other-model",
            "project": "claimed-project",
            "verified_project_reference": "claimed-proof",
            "credential_binding": "claimed-proof",
            "credential_provider": mock.Mock(),
            "connection_factory": mock.Mock(),
            "price_policy": "claimed-proof",
            "authorization": "claimed-proof",
            "count_equivalent": True,
            "verified": True,
            "enabled": True,
            "_document_json": "{}",
        }
        for name, value in unsupported.items():
            with self.subTest(name=name), self.assertRaises(TypeError):
                GenuineRuntimeIdentity(**{name: value})
        for name in ("available", "blockers"):
            with self.assertRaises(TypeError):
                GenuineRuntimeCapability(**{name: True})

    def test_no_network_secret_or_ambient_configuration_lookup(self):
        baseline = GenuineRuntimeIdentity().metadata
        with (
            mock.patch("socket.socket", side_effect=AssertionError("I/O")),
            mock.patch(
                "http.client.HTTPSConnection",
                side_effect=AssertionError("connection constructed"),
            ),
            mock.patch.object(
                os, "getenv", side_effect=AssertionError("env read")
            ),
            mock.patch.object(
                os, "environ", {"OPENAI_API_KEY": "synthetic-secret-marker"}
            ),
        ):
            identity = GenuineRuntimeIdentity()
            self.assertEqual(identity.metadata, baseline)
            for _ in range(2):
                with self.assertRaises(AppError) as caught:
                    identity.capability.require_dispatch()
                self.assertEqual(
                    caught.exception.code, "COUNT_CONTRACT_UNRESOLVED"
                )
        public = (
            repr(identity)
            + repr(identity.capability)
            + json.dumps(identity.metadata)
        )
        self.assertNotIn("synthetic-secret-marker", public)
        self.assertNotIn(
            hashlib.sha256(b"synthetic-secret-marker").hexdigest(), public
        )

    def test_asset_mismatch_fails_closed(self):
        original_read = Path.read_bytes

        def changed(path):
            content = original_read(path)
            if path.name == "arm-B-system.txt":
                return content + b"\n"
            return content

        with mock.patch.object(Path, "read_bytes", changed):
            with self.assertRaises(AppError) as caught:
                GenuineRuntimeIdentity()
        self.assertEqual(caught.exception.code, "GENUINE_RUNTIME_INVALID")

    def test_absent_evidence_and_unresolved_count_never_look_verified(self):
        identity = GenuineRuntimeIdentity()
        metadata = identity.metadata
        self.assertEqual(metadata["count_contract"]["state"], "unresolved")
        self.assertIsNone(
            metadata["count_contract"]["equivalence_evidence_reference"]
        )
        self.assertIsNone(
            metadata["request_contract"]["generation_body_sha256"]
        )
        for section in ("credential_binding", "pricing", "authorization"):
            for key, value in metadata[section].items():
                if key.endswith("reference"):
                    self.assertIsNone(value)
        self.assertEqual(len(identity.capability.blockers), 7)
        for name in ("send", "observe", "propose", "count", "build_request"):
            self.assertFalse(hasattr(identity, name))
            self.assertFalse(hasattr(identity.capability, name))

    def test_plan_binds_actual_offline_request_contract_without_relabelling(
        self,
    ):
        bundle = load_bundle()
        source_text = "Layout: UK_QWERTY."
        source = {
            "source_id": "synthetic:test",
            "revision": 1,
            "sha256": text_hash(source_text),
            "text": source_text,
        }
        conditions = [
            {"condition_id": "c1", "kind": "layout", "value": "UK_QWERTY"}
        ]
        transport = mock.Mock()
        adapter = OfflineResponsesAdapter(transport)
        payload = json.loads(adapter.build_request(source, conditions))
        identity = GenuineRuntimeIdentity().metadata
        contract = identity["request_contract"]
        self.assertEqual(
            set(payload),
            {
                "model",
                "instructions",
                "input",
                "text",
                "reasoning",
                "tools",
                "service_tier",
                "max_output_tokens",
                "prompt_cache_options",
                "store",
                "background",
                "stream",
            },
        )
        self.assertEqual(payload["model"], identity["model"])
        self.assertEqual(payload["instructions"], bundle.system)
        for key in (
            "service_tier",
            "reasoning",
            "tools",
            "prompt_cache_options",
            "store",
            "background",
            "stream",
            "max_output_tokens",
        ):
            self.assertEqual(payload[key], contract[key])
        text_format = payload["text"]["format"]
        self.assertEqual(
            text_format["schema"], json.loads(bundle.wire_schema_json)
        )
        for key in ("type", "name", "strict"):
            self.assertEqual(text_format[key], contract["text_format"][key])
        self.assertEqual(
            adapter.metadata["execution_mode"], "offline-injected-only"
        )
        transport.assert_not_called()
        transport.send.assert_not_called()

    def test_malformed_or_stale_fingerprint_does_not_echo_input(self):
        identity = GenuineRuntimeIdentity()
        for value in (None, True, [], "", "0" * 64, "A" * 64, "private-marker"):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(AppError) as caught:
                    identity.require_same_identity(value)
                self.assertNotIn("private-marker", repr(caught.exception))


if __name__ == "__main__":
    unittest.main()
