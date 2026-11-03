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

from cartreadback_app.context_capacity import (
    ContextCapacityPolicy,
    HostCapacityAuthorization,
)
from cartreadback_app.inference_config import (
    InferenceConfig,
    configuration_metadata,
    load_bundle,
)
from cartreadback_app.responses_http import (
    HTTPSRoutingConfig,
    unselected_stdlib_connection,
)
from cartreadback_app.validation import AppError, digest, text_hash

ADAPTER_VERSION = "genuine-context-responses-v1"


def blocked() -> AppError:
    """Return one sanitized failure without private host record details."""
    return AppError(
        "CONTEXT_CAPACITY_BLOCKED", "Context analysis unavailable.", 503
    )


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise blocked()


@dataclass(frozen=True)
class CredentialBinding:
    """Nonsecret expected scope and revision, established outside this process."""

    organization: str
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
    """Concrete allowlist of full catalog identities and typed condition values."""

    catalog_sha256: tuple[str, ...]
    condition_values: tuple[tuple[str, str], ...]
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
            type(self.condition_values) is not tuple
            or not self.condition_values
        ):
            raise blocked()
        from cartreadback_app.validation import conditions

        for pair in self.condition_values:
            if type(pair) is not tuple or len(pair) != 2:
                raise blocked()
            conditions([{"kind": pair[0], "value": pair[1]}])

    def allows(self, catalog, conditions, owner) -> bool:
        """Check exact bytes/revision/price and each actual typed buyer value."""
        return (
            text_hash(owner) in self.owner_sha256
            and digest(catalog) in self.catalog_sha256
            and all(
                (item["kind"], item["value"]) in self.condition_values
                for item in conditions
            )
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
        return unselected_stdlib_connection

    @property
    def metadata(self):
        """Bind shipped mechanics and installation, not arbitrary callables."""
        return {
            "kind": "provider",
            "implementation": "scoped-stdlib-https-v1",
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
            for name in ("context_runtime.py", "responses_http.py")
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
    binding, route, response_language="en", timeout_seconds=20.0, *, transport
):
    """Bind execution first, independently of policy and approval identities."""
    if (
        type(binding) is not CredentialBinding
        or type(route) is not HTTPSRoutingConfig
    ):
        raise blocked()
    if (
        type(response_language) is not str
        or response_language not in ("en", "ko")
        or type(timeout_seconds) not in (int, float)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 20
    ):
        raise blocked()
    config = InferenceConfig(response_language=response_language)
    return digest(
        {
            "version": ADAPTER_VERSION,
            "observed_runtime": {
                "python_implementation": sys.implementation.name,
                "python_version_info": tuple(sys.version_info),
                "python_version": sys.version,
                "openssl_version_info": tuple(ssl.OPENSSL_VERSION_INFO),
                "openssl_version": ssl.OPENSSL_VERSION,
            },
            "assets_and_request": configuration_metadata(config, load_bundle()),
            "route": route.metadata,
            "transport": _transport_metadata(transport),
            "binding": asdict(binding),
            "overall_timeout_seconds": timeout_seconds,
            "strategy": "context-capacity-v1",
        }
    )


def host_provenance(
    binding_record_sha256, pricing_adoption_record_sha256, evidence_kind
):
    """Identify external records without claiming this digest proves them."""
    _sha(binding_record_sha256)
    _sha(pricing_adoption_record_sha256)
    if type(evidence_kind) is not str or evidence_kind not in (
        "fabricated-offline",
        "provider",
    ):
        raise blocked()
    return digest(
        {
            "binding_record": binding_record_sha256,
            "pricing_adoption_record": pricing_adoption_record_sha256,
            "evidence_kind": evidence_kind,
        }
    )


@dataclass(frozen=True)
class InstalledProviderContext:
    """Provisioner-installed records; there is no supported live installer yet.

    The pricing record is separate from unchanged unselected reference math.
    Supplying Python objects is trusted host configuration, not external proof.
    """

    binding: CredentialBinding
    scope: ApprovedDataScope
    policy: ContextCapacityPolicy
    authorization: HostCapacityAuthorization
    binding_record_sha256: str
    pricing_adoption_record_sha256: str
    credential_handle: CredentialHandle = field(repr=False, compare=False)
    transport: ProviderTransportBinding | FabricatedTransportBinding
    evidence_kind: str = "fabricated-offline"
    route: HTTPSRoutingConfig = HTTPSRoutingConfig()
    response_language: str = "en"
    timeout_seconds: float = 20.0

    def __post_init__(self):
        """Check noncircular identity consistency, not truth of external records."""
        if (
            type(self.scope) is not ApprovedDataScope
            or type(self.policy) is not ContextCapacityPolicy
            or type(self.authorization) is not HostCapacityAuthorization
        ):
            raise blocked()
        if _transport_metadata(self.transport)["kind"] != self.evidence_kind:
            raise blocked()
        if (
            self.authorization.runtime_sha256 != self.execution_sha256
            or self.authorization.data_scope_sha256
            != digest(asdict(self.scope))
            or self.authorization.policy_sha256
            != text_hash(self.policy.identity)
            or self.authorization.provenance_sha256
            != host_provenance(
                self.binding_record_sha256,
                self.pricing_adoption_record_sha256,
                self.evidence_kind,
            )
            or self.authorization.valid_from < self.policy.valid_from
            or self.authorization.expires_at > self.policy.expires_at
        ):
            raise blocked()
        self._check_handle()

    @property
    def execution_sha256(self):
        """Return execution identity without introducing an authorization cycle."""
        return execution_identity(
            self.binding,
            self.route,
            self.response_language,
            self.timeout_seconds,
            transport=self.transport,
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
class ContextAnalysisRuntime:
    """Host-only selection; an absent install/factory has no dispatch authority."""

    installed: InstalledProviderContext | None = None
    connection_factory: object = field(default=None, repr=False)

    def __post_init__(self):
        """Retain trusted host objects; do not resolve a key or open a socket."""
        if (
            self.installed is not None
            and type(self.installed) is not InstalledProviderContext
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
            type(self.installed) is InstalledProviderContext
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


def resolve_installed_context():
    """Default resolver is deliberately absent; do not infer authority from env."""
    raise blocked()
