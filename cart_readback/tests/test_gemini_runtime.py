"""Nonsecret host record tests; no credential discovery or external transport."""

import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

from cartreadback_app.gemini_client import CURRENT_MODEL, GeminiConfig
from cartreadback_app.gemini_http import unselected_gemini_connection
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
from cartreadback_app.validation import AppError, digest, text_hash
from test_gemini_capacity import CONDITIONS, NOW, SOURCE, authorization, policy


class Handle:
    def __init__(self, binding):
        self.binding = binding
        self.borrowed = False

    def borrow(self, **kwargs):
        self.borrowed = True
        raise AssertionError("No runtime constructor may read a key")


def installed(**changes):
    binding = CredentialBinding(
        "fabricated-project", "key-version", "host-version"
    )
    config = GeminiConfig(CURRENT_MODEL, model=CURRENT_MODEL)
    scope = ApprovedDataScope(
        (digest(SOURCE),), (digest(CONDITIONS),), (text_hash("owner"),)
    )
    transport = FabricatedTransportBinding(lambda *args, **kwargs: None)
    adopted = policy()
    auth = authorization(
        adopted,
        "a" * 64,
        runtime_sha256=execution_identity(binding, config, transport=transport),
        data_scope_sha256=digest(asdict(scope)),
        provenance_sha256=host_provenance(
            "b" * 64, adopted.pricing_record_sha256, "fabricated-offline"
        ),
    )
    values = dict(
        binding=binding,
        config=config,
        scope=scope,
        policy=adopted,
        authorization=auth,
        binding_record_sha256="b" * 64,
        pricing_adoption_record_sha256=adopted.pricing_record_sha256,
        credential_handle=Handle(binding),
        transport=transport,
    )
    return InstalledGeminiContext(**(values | changes))


class GeminiRuntimeTests(unittest.TestCase):
    def test_default_and_ambient_key_unavailable_no_socket(self):
        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "fabricated-secret"}),
            patch("socket.create_connection", side_effect=AssertionError),
        ):
            self.assertFalse(GeminiAnalysisRuntime().available(NOW))
            host = installed()
            self.assertTrue(GeminiAnalysisRuntime(host).available(NOW))
            self.assertFalse(host.credential_handle.borrowed)

    def test_exact_owner_catalog_and_conditions(self):
        scope = installed().scope
        self.assertTrue(scope.allows(SOURCE, CONDITIONS, "owner"))
        self.assertFalse(scope.allows(SOURCE, CONDITIONS, "foreign"))
        self.assertFalse(
            scope.allows(SOURCE | {"revision": 2}, CONDITIONS, "owner")
        )
        self.assertFalse(
            scope.allows(
                SOURCE, [CONDITIONS[0] | {"condition_id": "c2"}], "owner"
            )
        )
        self.assertFalse(scope.allows(SOURCE, CONDITIONS + CONDITIONS, "owner"))

    def test_stale_credential_version_fails_without_borrow(self):
        host = installed()
        host.credential_handle.binding = replace(
            host.binding, credential_version="changed"
        )
        self.assertFalse(GeminiAnalysisRuntime(host).available(NOW))
        self.assertFalse(host.credential_handle.borrowed)

    def test_replaced_factory_rejected(self):
        runtime = GeminiAnalysisRuntime(
            installed(), lambda *args, **kwargs: None
        )
        self.assertFalse(runtime.available(NOW))

    def test_provider_binding_fixed_factory(self):
        transport = ProviderTransportBinding("revision")
        self.assertIs(transport.factory, unselected_gemini_connection)
        with self.assertRaises(TypeError):
            ProviderTransportBinding("revision", factory=lambda: None)

    def test_fabricated_binding_cannot_claim_provider(self):
        with self.assertRaises(AppError):
            installed(evidence_kind="provider")

    def test_expired_nonfinite_and_backward_before_window(self):
        runtime = GeminiAnalysisRuntime(installed())
        for now in (NOW + 80, NOW - 6, float("nan"), float("inf"), True):
            with self.subTest(now=now):
                self.assertFalse(runtime.available(now))

    def test_changed_policy_project_or_model_is_not_approved(self):
        host = installed()
        for changes in (
            {"policy": replace(host.policy, project="different")},
            {"config": replace(host.config, response_language="ko")},
            {"pricing_adoption_record_sha256": "c" * 64},
            {"binding": replace(host.binding, host_revision="different")},
            {"transport": FabricatedTransportBinding(host.transport.factory)},
        ):
            with self.subTest(changes=changes), self.assertRaises(AppError):
                replace(host, **changes)

    def test_scope_is_immutable_hashes_not_labels(self):
        for values in (
            ([], (), ()),
            (("all",), (digest(CONDITIONS),), (text_hash("owner"),)),
        ):
            with self.assertRaises(AppError):
                ApprovedDataScope(*values)


if __name__ == "__main__":
    unittest.main()
