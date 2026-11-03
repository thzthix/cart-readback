"""Distinct context-capacity adapter; fabricated tests are not live evidence.

Only the service drives a committed claim into exchange. There is no propose()
shortcut, subclassing/relabeling of the offline adapter, or count preflight.
"""

import hashlib
import json
import time
from dataclasses import dataclass

from cartreadback_app.context_capacity import ContextClaim, parse_accounting
from cartreadback_app.context_runtime import (
    ADAPTER_VERSION,
    ContextAnalysisRuntime,
    blocked,
)
from cartreadback_app.inference_config import (
    ENDPOINT,
    MODEL,
    InferenceConfig,
    load_bundle,
)
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.responses_adapter import (
    Deadline,
    WireResponse,
    _provider_text,
    _validate_results,
    build_text_request,
)
from cartreadback_app.responses_http import (
    ScopedHTTPSTransport,
    valid_request_id,
)
from cartreadback_app.validation import AppError, canonical, text_hash


@dataclass(frozen=True)
class PreparedGeneration:
    """Owned exact request bytes, execution identity and source inputs."""

    request: bytes
    runtime_sha256: str
    inputs_json: str

    @property
    def request_sha256(self):
        """Hash the exact bytes that must reach the claimed exchange."""
        return hashlib.sha256(self.request).hexdigest()


@dataclass(frozen=True)
class GenuineExchange:
    """Host-recorded exchange identity, never provider-echoed authority."""

    operation_id: str
    claim_token: str
    request_sha256: str
    runtime_sha256: str
    request_id: str
    envelope: bytes
    evidence_kind: str
    protocol_fault: bool = False


class GenuineResponsesAdapter:
    """One host-bound exchange with accounting independent of semantic parsing."""

    def __init__(self, runtime, clock):
        """Retain an exact host runtime, not an unscoped credential callback."""
        if type(runtime) is not ContextAnalysisRuntime:
            raise blocked()
        self.runtime = runtime
        self.clock = clock

    @property
    def metadata(self):
        """Return private review identity; service projects public metadata."""
        installed = self.runtime.installed
        bundle = load_bundle()
        return {
            "provider": "openai-responses",
            "model_version": MODEL,
            "prompt_version": json.loads(bundle.manifest_json)[
                "prompt_version"
            ],
            "adapter_version": ADAPTER_VERSION,
            "validator_version": "strict-spans-v1+ordered-results-v1",
            "is_fixture": False,
            "execution_mode": "genuine-context-capacity",
            "execution_kind": (
                "provider-runtime"
                if installed.evidence_kind == "provider"
                else "fabricated-offline"
            )
            if installed
            else "unavailable",
            "runtime_sha256": installed.execution_sha256
            if self.runtime.transport_matches
            else None,
            "host_authorization_sha256": text_hash(
                canonical(installed.authorization.__dict__)
            )
            if installed
            else None,
            "host_binding_record_sha256": installed.binding_record_sha256
            if installed
            else None,
            "pricing_adoption_record_sha256": installed.pricing_adoption_record_sha256
            if installed
            else None,
        }

    def prepare(self, source, conditions):
        """Build immutable request bytes after the host record gate, without I/O."""
        installed = self.runtime.require(self.clock())
        raw = build_text_request(
            source,
            conditions,
            config=InferenceConfig(
                response_language=installed.response_language
            ),
            bundle=load_bundle(),
            metadata={"max_output_tokens": 2048, "max_request_bytes": 65_536},
        )
        return PreparedGeneration(
            raw,
            installed.execution_sha256,
            canonical({"source": source, "conditions": conditions}),
        )

    def deadline(self, claim):
        """Clamp precise UTC expiry to monotonic time, including gate overhead."""
        started = time.monotonic()
        now = self.clock()
        installed = self.runtime.require(now)
        wall_expiry = min(claim.expires_at, installed.authorization.expires_at)
        expires = min(
            started + installed.timeout_seconds,
            started + (wall_expiry - now),
            time.monotonic() + (wall_expiry - self.clock()),
        )
        deadline = Deadline(expires, 3.0, 12.0)
        deadline.remaining()
        return deadline

    def exchange(self, prepared, claim, deadline):
        """Exchange claimed exact bytes outside SQLite, with no retry/fallback."""
        installed = self.runtime.require(self.clock())
        if (
            type(prepared) is not PreparedGeneration
            or type(claim) is not ContextClaim
            or prepared.runtime_sha256 != installed.execution_sha256
            or prepared.request_sha256 != claim.reservation.request_sha256
            or self.clock() >= claim.expires_at
        ):
            raise blocked()
        if type(deadline) is not Deadline:
            raise blocked()
        current_deadline = self.deadline(claim)
        deadline = Deadline(
            min(deadline.expires_at, current_deadline.expires_at),
            deadline.connect_limit,
            deadline.read_limit,
        )
        deadline.remaining()
        transport = ScopedHTTPSTransport(
            self.runtime.connection_factory,
            installed,
            self.clock,
            claim.expires_at,
        )
        response = transport.send(ENDPOINT, prepared.request, deadline=deadline)
        if type(response) is not WireResponse:
            raise blocked()
        chunks = bytearray()
        fault = False
        try:
            if response.status_code != 200 or not valid_request_id(
                response.request_id
            ):
                raise blocked()
            iterator = iter(response.body)
            try:
                # Keep complete independently received bytes for late accounting.
                # The HTTPS implementation still enforces its I/O deadlines.
                for chunk in iterator:
                    if (
                        type(chunk) is not bytes
                        or len(chunks) + len(chunk) > 131_072
                    ):
                        raise blocked()
                    chunks.extend(chunk)
            finally:
                close = getattr(iterator, "close", None)
                if close:
                    close()
        except Exception:
            fault = True
        finally:
            if response.close:
                try:
                    response.close()
                except Exception:
                    fault = True
        return GenuineExchange(
            claim.reservation.operation_id,
            claim.claim_token,
            prepared.request_sha256,
            prepared.runtime_sha256,
            response.request_id,
            bytes(chunks),
            installed.evidence_kind,
            fault,
        )

    @staticmethod
    def classify(exchange, policy, prepared):
        """Classify billing protocol before parsing proposal; return no authority."""
        protocol_fault = exchange.protocol_fault
        try:
            accounting = json.loads(parse_accounting(exchange.envelope, policy))
            protocol_fault = (
                protocol_fault
                or accounting["usage_finality"] != "terminal-model-usage"
                or accounting["accounting_contract"]
                != "no-explicit-profile-conflict"
            )
        except AppError:
            protocol_fault = True
        if protocol_fault:
            return True, "MODEL_OUTCOME_UNKNOWN", None
        inputs = json.loads(prepared.inputs_json)
        try:
            envelope = strict_provider_json(
                exchange.envelope, max_bytes=131_072, max_depth=32
            )
            text = _provider_text(envelope, (MODEL,))
            wire = strict_provider_json(
                text.encode("utf-8"), max_bytes=65_536, max_depth=8
            )
            results = _validate_results(
                inputs["source"], inputs["conditions"], wire
            )
            return False, "", results
        except AppError as error:
            code = (
                error.code
                if error.code
                in {"MODEL_REFUSED", "MODEL_INCOMPLETE", "MODEL_UNAVAILABLE"}
                else "INVALID_PROPOSAL"
            )
            return False, code, None
        except Exception:
            return False, "INVALID_PROPOSAL", None
