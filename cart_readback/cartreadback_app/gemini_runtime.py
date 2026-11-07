"""Trusted host installation records, with absent default provisioning.

These Python records bind externally established facts; they do not verify them.
Tests fabricate the whole boundary. Python hosts and factories are trusted code,
not a sandbox or cryptographic attestation. No environment/browser resolver exists.
"""

import hashlib
import math
import re
import ssl
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from cartreadback_app.gemini_capacity import (
    GeminiCapacityPolicy,
    HostGeminiAuthorization,
)
from cartreadback_app.gemini_client import GeminiClient, GeminiConfig
from cartreadback_app.gemini_http import unselected_gemini_connection
from cartreadback_app.validation import AppError, digest, text_hash

ADAPTER_VERSION = "genuine-gemini-generation-v1"


def blocked() -> AppError:
    """Return one sanitized failure without private host record details."""
    return AppError(
        "GEMINI_CAPACITY_BLOCKED", "Gemini analysis unavailable.", 503
    )


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise blocked()


@dataclass(frozen=True)
class CredentialBinding:
    """Nonsecret expected scope and revision, established outside this process."""

    project: str
    credential_version: str
    host_revision: str

    def __post_init__(self):
        """Require bounded header-safe nonsecret identifiers, never key material."""
        for value in asdict(self).values():
            if (
                type(value) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
            ):
                raise blocked()


class CredentialHandle(Protocol):
    """Opaque provisioner handle; it must enforce its exact binding on borrow."""

    @property
    def binding(self) -> CredentialBinding:
        """Report the current nonsecret binding version, without reading a key."""
        ...

    def borrow(self, *, expected_binding, deadline) -> str:
        """Borrow only for the matching committed claim's scope and deadline."""
        ...


@dataclass(frozen=True)
class ApprovedDataScope:
    """Exact full catalog, ordered conditions and owner identities."""

    catalog_sha256: tuple[str, ...]
    conditions_sha256: tuple[str, ...]
    owner_sha256: tuple[str, ...]

    def __post_init__(self):
        """Reject empty/mutable scopes; labels alone cannot approve source data."""
        if type(self.catalog_sha256) is not tuple or not self.catalog_sha256:
            raise blocked()
        if type(self.owner_sha256) is not tuple or not self.owner_sha256:
            raise blocked()
        for value in (*self.catalog_sha256, *self.owner_sha256):
            _sha(value)
        if (
            type(self.conditions_sha256) is not tuple
            or not self.conditions_sha256
        ):
            raise blocked()
        for value in self.conditions_sha256:
            _sha(value)

    def allows(self, catalog, conditions, owner) -> bool:
        """Check exact bytes/revision/price and the complete ordered requirements."""
        return (
            text_hash(owner) in self.owner_sha256
            and digest(catalog) in self.catalog_sha256
            and digest(conditions) in self.conditions_sha256
        )


@dataclass(frozen=True)
class ProviderTransportBinding:
    """One shipped constructor; this record supplies no provisioning authority."""

    installation_revision: str

    def __post_init__(self):
        """Validate a nonsecret externally established installation revision."""
        if (
            type(self.installation_revision) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.installation_revision)
            is None
        ):
            raise blocked()

    @property
    def factory(self):
        """Select only the shipped implementation, without constructing I/O."""
        return unselected_gemini_connection

    @property
    def metadata(self):
        """Bind shipped mechanics and installation, not arbitrary callables."""
        return {
            "kind": "provider",
            "implementation": "gemini-fixed-origin-https-v1",
            "implementation_sha256": _transport_source_sha256(),
            "installation_revision": self.installation_revision,
        }


@dataclass(frozen=True)
class FabricatedTransportBinding:
    """Own a fake factory for one in-process installation, never provider proof."""

    factory: object = field(repr=False, compare=False)
    installation_generation: str = field(
        default_factory=lambda: uuid4().hex, init=False
    )

    def __post_init__(self):
        """Require mechanics; ordinary replacement gets a fresh generation."""
        if not callable(self.factory):
            raise blocked()

    @property
    def metadata(self):
        """Expose nonsecret freshness only; never hash captures or credentials."""
        return {
            "kind": "fabricated-offline",
            "implementation": "fabricated-host-factory-v1",
            "implementation_sha256": _transport_source_sha256(),
            "installation_generation": self.installation_generation,
        }


def _transport_source_sha256():
    # Observe reviewed wrapper/mechanics bytes, not callable repr or captures.
    # Python hosts remain trusted; this hash is identity, not attestation.
    return digest(
        {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in (
                "gemini_runtime.py",
                "gemini_http.py",
                "gemini_client.py",
                "gemini_capacity.py",
                "genuine_gemini.py",
                "service.py",
            )
        }
    )


def _transport_metadata(transport):
    if type(transport) not in (
        ProviderTransportBinding,
        FabricatedTransportBinding,
    ):
        raise blocked()
    transport.__post_init__()
    return transport.metadata


def execution_identity(
    binding, config, timeout_seconds=20.0, *, transport, policy
):
    """Bind execution and exact external policy before approval identity."""
    if (
        type(binding) is not CredentialBinding
        or type(config) is not GeminiConfig
        or type(policy) is not GeminiCapacityPolicy
        or policy.project != binding.project
        or policy.model != config.model
        or policy.expected_model_version != config.expected_model_version
    ):
        raise blocked()
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 20
    ):
        raise blocked()
    config.__post_init__()
    policy.__post_init__()
    return digest(
        {
            "version": ADAPTER_VERSION,
            "capacity_policy_sha256": text_hash(policy.identity),
            "observed_runtime": {
                "python_implementation": sys.implementation.name,
                "python_version_info": tuple(sys.version_info),
                "python_version": sys.version,
                "openssl_version_info": tuple(ssl.OPENSSL_VERSION_INFO),
                "openssl_version": ssl.OPENSSL_VERSION,
            },
            "assets_and_request": GeminiClient(config).metadata,
            "transport": _transport_metadata(transport),
            "binding": asdict(binding),
            "overall_timeout_seconds": timeout_seconds,
            "strategy": "gemini-capacity-v1",
        }
    )


def host_provenance(
    binding_record_sha256,
    pricing_adoption_record_sha256,
    evidence_kind,
    *,
    policy,
):
    """Identify external records without claiming this digest proves them."""
    if type(policy) is not GeminiCapacityPolicy:
        raise blocked()
    policy.__post_init__()
    _sha(binding_record_sha256)
    _sha(pricing_adoption_record_sha256)
    if type(evidence_kind) is not str or evidence_kind not in (
        "fabricated-offline",
        "provider",
    ):
        raise blocked()
    return digest(
        {
            "capacity_policy_sha256": text_hash(policy.identity),
            "binding_record": binding_record_sha256,
            "pricing_adoption_record": pricing_adoption_record_sha256,
            "evidence_kind": evidence_kind,
        }
    )


@dataclass(frozen=True)
class InstalledGeminiContext:
    """Explicit prepared host records; no ambient discovery or approval inference.

    The pricing record identifies externally adopted project rates.
    Supplying Python objects is trusted host configuration, not external proof.
    """

    binding: CredentialBinding
    scope: ApprovedDataScope
    policy: GeminiCapacityPolicy
    authorization: HostGeminiAuthorization
    binding_record_sha256: str
    pricing_adoption_record_sha256: str
    credential_handle: CredentialHandle = field(repr=False, compare=False)
    transport: ProviderTransportBinding | FabricatedTransportBinding
    config: GeminiConfig
    evidence_kind: str = "fabricated-offline"
    timeout_seconds: float = 20.0

    def __post_init__(self):
        """Check noncircular identity consistency, not truth of external records."""
        if (
            type(self.scope) is not ApprovedDataScope
            or type(self.policy) is not GeminiCapacityPolicy
            or type(self.authorization) is not HostGeminiAuthorization
        ):
            raise blocked()
        if _transport_metadata(self.transport)["kind"] != self.evidence_kind:
            raise blocked()
        if (
            self.authorization.admission_mode != self.policy.admission_mode
            or self.authorization.runtime_sha256 != self.execution_sha256
            or self.authorization.data_scope_sha256
            != digest(asdict(self.scope))
            or self.authorization.policy_sha256
            != text_hash(self.policy.identity)
            or self.authorization.provenance_sha256
            != host_provenance(
                self.binding_record_sha256,
                self.pricing_adoption_record_sha256,
                self.evidence_kind,
                policy=self.policy,
            )
            or self.authorization.valid_from < self.policy.valid_from
            or self.authorization.expires_at > self.policy.expires_at
        ):
            raise blocked()
        if (
            self.policy.project != self.binding.project
            or self.config.model != self.policy.model
            or self.config.expected_model_version
            != self.policy.expected_model_version
            or self.pricing_adoption_record_sha256
            != self.policy.pricing_record_sha256
        ):
            raise blocked()
        self._check_handle()

    @property
    def execution_sha256(self):
        """Return execution identity without introducing an authorization cycle."""
        return execution_identity(
            self.binding,
            self.config,
            self.timeout_seconds,
            transport=self.transport,
            policy=self.policy,
        )

    def _check_handle(self):
        try:
            current_binding = getattr(self.credential_handle, "binding", None)
            borrow = getattr(self.credential_handle, "borrow", None)
            if (
                type(current_binding) is not CredentialBinding
                or current_binding != self.binding
                or not callable(borrow)
            ):
                raise blocked()
        except Exception:
            raise blocked() from None

    def validate(self, now):
        """Recheck immutable record relations, handle version and bounded time."""
        self.__post_init__()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or not self.authorization.valid_from
            <= now
            < self.authorization.expires_at
        ):
            raise blocked()


@dataclass(frozen=True)
class GeminiAnalysisRuntime:
    """Host-only selection; an absent install/factory has no dispatch authority."""

    installed: InstalledGeminiContext | None = None
    connection_factory: object = field(default=None, repr=False)

    def __post_init__(self):
        """Retain trusted host objects; do not resolve a key or open a socket."""
        if (
            self.installed is not None
            and type(self.installed) is not InstalledGeminiContext
        ):
            raise blocked()
        if self.connection_factory is None and self.installed is not None:
            object.__setattr__(
                self, "connection_factory", self.installed.transport.factory
            )
        if self.connection_factory is not None and not callable(
            self.connection_factory
        ):
            raise blocked()

    @property
    def transport_matches(self):
        """Reject unrelated mechanics without invoking any selected callable."""
        return (
            type(self.installed) is InstalledGeminiContext
            and type(self.installed.transport)
            in (ProviderTransportBinding, FabricatedTransportBinding)
            and self.connection_factory is self.installed.transport.factory
        )

    def require(self, now):
        """Fail closed until the host has installed both records and mechanics."""
        if not self.transport_matches:
            raise blocked()
        try:
            self.installed.validate(now)
        except Exception:
            raise blocked() from None
        return self.installed

    def available(self, now):
        """Report present host dispatch capability, never a completed call."""
        try:
            self.require(now)
            return True
        except Exception:
            return False


def resolve_installed_gemini():
    """Default resolver is deliberately absent; do not infer authority from env."""
    raise blocked()
