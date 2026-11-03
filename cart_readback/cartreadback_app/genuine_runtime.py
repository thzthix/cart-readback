"""Nonsecret identity for an unselected genuine runtime, never a live adapter.

This pure review/fencing primitive does not construct a connection or supply
external verification. The only capability result is blocked. No supplied flag,
scope name, credential callback or environment setting can change that result.
"""

import hashlib
import hmac
import json
import re
import ssl
import sys
from dataclasses import dataclass, field
from typing import NoReturn

from cartreadback_app.inference_config import (
    LOCAL_SCHEMA_SHA256,
    MANIFEST_SHA256,
    MODEL,
    load_bundle,
)
from cartreadback_app.provider_json import PARSER_VERSION
from cartreadback_app.validation import AppError, canonical, digest

_IDENTITY_REVISION = "genuine-runtime-identity-v1"
_REQUEST_REVISION = "cartreadback-text-generation-contract-v1"
_COUNT_REVISION = "count-contract-unresolved-v1"
_TRANSPORT_REVISION = "genuine-fixed-https-policy-v1-unimplemented"
_CREDENTIAL_REVISION = "credential-binding-absent-v1"
_PRICING_REVISION = "genuine-pricing-unadopted-v1"
_AUTHORIZATION_REVISION = "genuine-authorization-absent-v1"


def _invalid() -> AppError:
    return AppError(
        "GENUINE_RUNTIME_INVALID", "Unsupported genuine runtime identity.", 503
    )


@dataclass(frozen=True, slots=True)
class GenuineRuntimeCapability:
    """An immutable negative result, not an authorizable runtime handle.

    All fields are fixed and excluded from construction. Resolving any blocker
    requires a later reviewed implementation, not a caller assertion. This
    object deliberately has no transport, credentials, count or send methods.
    """

    available: bool = field(default=False, init=False)
    blockers: tuple[str, ...] = field(
        default=(
            "COUNT_CONTRACT_UNRESOLVED",
            "ACCOUNT_PROJECT_UNVERIFIED",
            "CREDENTIAL_BINDING_ABSENT",
            "GENUINE_PRICING_UNADOPTED",
            "GENUINE_AUTHORIZATION_ABSENT",
            "DURABLE_ADMISSION_UNIMPLEMENTED",
            "GENUINE_TRANSPORT_UNIMPLEMENTED",
        ),
        init=False,
    )

    def require_dispatch(self) -> NoReturn:
        """Deny before a future caller may retrieve secrets or create I/O."""
        raise AppError(
            "COUNT_CONTRACT_UNRESOLVED",
            "Genuine runtime unavailable; count equivalence is unresolved.",
            503,
        )


def _identity_document(response_language: str, route: str) -> dict:
    """Bind shipped assets and the whole planned policy, including absent proof."""
    try:
        bundle = load_bundle()
    except AppError:
        raise _invalid() from None
    manifest = json.loads(bundle.manifest_json)
    return {
        "identity_revision": _IDENTITY_REVISION,
        "kind": "unselected-genuine-runtime-plan",
        "provider": "openai-responses",
        "generation_endpoint": "https://api.openai.com/v1/responses",
        "count_endpoint": "https://api.openai.com/v1/responses/input_tokens",
        "model": MODEL,
        "accepted_model_ids": [MODEL],
        "response_language": response_language,
        "assets": {
            "prompt_version": manifest["prompt_version"],
            "prompt_manifest_sha256": MANIFEST_SHA256,
            "system_sha256": hashlib.sha256(
                bundle.system.encode("utf-8")
            ).hexdigest(),
            "user_template_sha256": hashlib.sha256(
                bundle.user_template.encode("utf-8")
            ).hexdigest(),
            "wire_schema_version": manifest["wire_schema_version"],
            "wire_schema_sha256": hashlib.sha256(
                bundle.wire_schema_json.encode("utf-8")
            ).hexdigest(),
            "local_schema_sha256": LOCAL_SCHEMA_SHA256,
        },
        "request_contract": {
            "revision": _REQUEST_REVISION,
            "serialization": "canonical-json-utf8-sort-keys-no-whitespace-v1",
            "instructions": "exact-shipped-system",
            "input": "one-user-one-input_text-exact-shipped-template",
            "template_values": "validated-source-conditions-response_language",
            "text_format": {
                "type": "json_schema",
                "name": "cartreadback_proposal_v1",
                "strict": True,
                "schema": "exact-shipped-wire-schema",
            },
            "service_tier": "default",
            "reasoning": {"effort": "none"},
            "tools": [],
            "prompt_cache_options": {"mode": "explicit"},
            "store": False,
            "background": False,
            "stream": False,
            "max_output_tokens": 2048,
            "additional_fields": "rejected-at-every-level",
            "history_files_images": "unsupported",
            "cache_breakpoints": "unsupported",
            "temperature_top_p_seed": "omitted",
            "generation_body_sha256": None,
        },
        "count_contract": {
            "revision": _COUNT_REVISION,
            "state": "unresolved",
            "verified_contract_reference": None,
            "request_body_sha256": None,
            "equivalence_evidence_reference": None,
            "unresolved_generation_fields": [
                "service_tier",
                "max_output_tokens",
                "prompt_cache_options",
                "store",
                "background",
                "stream",
            ],
        },
        "transport_policy": {
            "revision": _TRANSPORT_REVISION,
            "state": "not-constructed-or-verified",
            "route": route,
            "proxy": "http://proxy.server:3128"
            if route == "pythonanywhere"
            else None,
            "connect_target": "api.openai.com:443",
            "ambient_proxy": "ignored",
            "tls_minimum": "TLSv1.2",
            "tls_hostname_check": True,
            "tls_certificate_check": "CERT_REQUIRED",
            "http_protocol": "HTTP/1.1",
            "http_parser_policy": "strict-status-headers-chunks-v1",
            "json_parser_revision": PARSER_VERSION,
            "validator_revision": "strict-spans-v1+ordered-results-v1",
            "max_request_bytes": 65_536,
            "max_response_bytes": 131_072,
            "max_header_fields": 64,
            "max_header_characters": 16_384,
            "max_envelope_depth": 32,
            "max_wire_bytes": 65_536,
            "max_wire_depth": 8,
            "overall_timeout_seconds": 20,
            "connect_timeout_seconds": 3,
            "read_timeout_seconds": 12,
            "retries": 0,
            "redirects": 0,
            "route_fallbacks": 0,
            "debug_level": 0,
            "concurrency": 1,
        },
        "credential_binding": {
            "revision": _CREDENTIAL_REVISION,
            "state": "absent",
            "verified_account_reference": None,
            "verified_project_reference": None,
            "verified_binding_reference": None,
        },
        "pricing": {
            "revision": _PRICING_REVISION,
            "state": "unadopted",
            "verified_policy_reference": None,
            "count_billing_evidence_reference": None,
        },
        "authorization": {
            "revision": _AUTHORIZATION_REVISION,
            "state": "absent",
            "bounded_authorization_reference": None,
        },
        "host_runtime": {
            "boundary_revision": _IDENTITY_REVISION,
            "python_implementation": sys.implementation.name,
            "python_version": list(sys.version_info),
            "openssl_version": list(ssl.OPENSSL_VERSION_INFO),
            "deployment_verification_reference": None,
        },
        "capability": {
            "available": False,
            "blockers": list(GenuineRuntimeCapability().blockers),
        },
    }


@dataclass(frozen=True, slots=True)
class GenuineRuntimeIdentity:
    """Immutable nonsecret plan identity, distinct from offline configuration.

    Only reviewed language/route enums are inputs. All other settings are fixed;
    unknown endpoint, model, project, credential, price and authorization inputs
    are unsupported. Missing external references are null, never caller labels.
    The digest identifies this plan, not a generation body or provider account.
    Frozen values protect ordinary use, not hostile code in the Python process.
    """

    response_language: str = "en"
    route: str = "direct"
    _document_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate enums and local assets without network or secret lookup."""
        if (
            type(self.response_language) is not str
            or self.response_language not in ("en", "ko")
            or type(self.route) is not str
            or self.route not in ("direct", "pythonanywhere")
        ):
            raise _invalid()
        object.__setattr__(
            self,
            "_document_json",
            canonical(_identity_document(self.response_language, self.route)),
        )

    @property
    def metadata(self) -> dict:
        """Return an owned metadata copy; no live or external-proof assertion."""
        identity = json.loads(self._document_json)
        return {**identity, "runtime_identity_sha256": digest(identity)}

    @property
    def capability(self) -> GenuineRuntimeCapability:
        """Return the fixed immutable blocked result, never an adapter."""
        return GenuineRuntimeCapability()

    def require_same_identity(self, expected_sha256: str) -> None:
        """Reject an absent/malformed/stale review identity without echoing it.

        Matching a plan fingerprint does not resolve any capability blocker,
        admit an operation or authorize a count/generation request.
        """
        if (
            type(expected_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or not hmac.compare_digest(
                expected_sha256, self.metadata["runtime_identity_sha256"]
            )
        ):
            raise AppError(
                "GENUINE_RUNTIME_IDENTITY_MISMATCH",
                "Genuine runtime review identity is missing or stale.",
                503,
            )
