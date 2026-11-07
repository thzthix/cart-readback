"""Host-only Gemini composition with independently fenced usage and proposals.

No default CLI/HTTP path selects this adapter. The Service owns the durable claim
and synchronous worker lifetime. Injected fabricated wire is never live evidence.
"""

import json
import time

from cartreadback_app.gemini_capacity import GeminiClaim, parse_accounting
from cartreadback_app.gemini_client import GeminiClient, GeminiConfig
from cartreadback_app.gemini_http import GeminiHTTPTransport
from cartreadback_app.gemini_runtime import (
    ADAPTER_VERSION,
    GeminiAnalysisRuntime,
    blocked,
)
from cartreadback_app.genuine_responses import (
    GenuineExchange,
    PreparedGeneration,
)
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.validation import AppError, canonical, text_hash


class GenuineGeminiAdapter:
    """Compose the real Gemini request client and guarded one-shot HTTPS code."""

    def __init__(self, runtime, clock):
        """Retain the exact immutable host runtime without resolving credentials."""
        if type(runtime) is not GeminiAnalysisRuntime:
            raise blocked()
        self.runtime = runtime
        self.clock = clock

    @property
    def metadata(self):
        """Return private identity; Service explicitly projects public keys."""
        installed = self.runtime.installed
        client = GeminiClient(installed.config) if installed else None
        return {
            "provider": "google-gemini-generate-content",
            "model_version": installed.config.model
            if installed
            else "unavailable",
            "prompt_version": json.loads(client.bundle.manifest_json)[
                "prompt_version"
            ]
            if client
            else "cartreadback-prompt-v2-wire",
            "adapter_version": ADAPTER_VERSION,
            "validator_version": "strict-spans-v1+ordered-results-v1",
            "is_fixture": False,
            "execution_mode": "genuine-gemini-capacity",
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
        }

    def prepare(self, source, conditions):
        """Build exact generation bytes without secret reads or provider I/O."""
        installed = self.runtime.require(self.clock())
        prepared = GeminiClient(installed.config).prepare(source, conditions)
        return PreparedGeneration(
            prepared.body,
            installed.execution_sha256,
            canonical(
                {
                    **json.loads(prepared.inputs_json),
                    "response_language": installed.config.response_language,
                }
            ),
        )

    def deadline(self, claim):
        """Clamp monotonic lifetime to both exact wall-clock approval deadlines."""
        started = time.monotonic()
        now = self.clock()
        installed = self.runtime.require(now)
        wall_expiry = min(claim.expires_at, installed.authorization.expires_at)
        deadline = Deadline(
            min(
                started + installed.timeout_seconds,
                started + wall_expiry - now,
                time.monotonic() + wall_expiry - self.clock(),
            ),
            3.0,
            12.0,
        )
        deadline.remaining()
        return deadline

    def exchange(self, prepared, claim, deadline, *, claim_guard=None):
        """Run one exact durable claim with Service rechecks at every I/O step."""
        if (
            type(prepared) is not PreparedGeneration
            or type(claim) is not GeminiClaim
            or type(deadline) is not Deadline
            or not callable(claim_guard)
        ):
            raise blocked()
        installed = self.runtime.require(self.clock())
        client = GeminiClient(installed.config)
        inputs = json.loads(prepared.inputs_json)
        rebuilt = client.prepare(inputs["source"], inputs["conditions"])
        if (
            prepared.request != rebuilt.body
            or inputs["response_language"] != installed.config.response_language
            or prepared.runtime_sha256 != installed.execution_sha256
            or prepared.request_sha256 != claim.reservation.request_sha256
        ):
            raise blocked()
        current = self.deadline(claim)
        deadline = Deadline(
            min(deadline.expires_at, current.expires_at),
            deadline.connect_limit,
            deadline.read_limit,
        )

        def guard(*, endpoint, body, deadline):
            current_install = self.runtime.require(self.clock())
            if (
                current_install.execution_sha256 != prepared.runtime_sha256
                or endpoint != client.metadata["endpoint"]
                or body != prepared.request
                or self.clock() >= claim.expires_at
            ):
                raise blocked()
            deadline.remaining()
            return claim_guard(endpoint=endpoint, body=body, deadline=deadline)

        def borrow(*, deadline):
            guard(
                endpoint=client.metadata["endpoint"],
                body=prepared.request,
                deadline=deadline,
            )
            return installed.credential_handle.borrow(
                expected_binding=installed.binding, deadline=deadline
            )

        transport = GeminiHTTPTransport(
            self.runtime.connection_factory, borrow, guard
        )
        raw = transport.send(
            client.metadata["endpoint"], prepared.request, deadline=deadline
        )
        # This local opaque envelope digest is not a provider request header.
        # The ledger separately deduplicates the provider responseId hash.
        return GenuineExchange(
            claim.reservation.operation_id,
            claim.claim_token,
            prepared.request_sha256,
            prepared.runtime_sha256,
            text_hash(raw.decode("utf-8")),
            raw,
            installed.evidence_kind,
            False,
        )

    @staticmethod
    def classify(exchange, policy, prepared):
        """Keep valid accounting when semantic/refusal validation rejects prose."""
        try:
            usage = json.loads(parse_accounting(exchange.envelope, policy))
            fault = (
                exchange.protocol_fault
                or usage["accounting_contract"]
                != "no-explicit-profile-conflict"
            )
        except AppError:
            fault = True
        if fault:
            return True, "MODEL_OUTCOME_UNKNOWN", None
        try:
            inputs = json.loads(prepared.inputs_json)
            client = GeminiClient(
                GeminiConfig(
                    policy.expected_model_version,
                    inputs["response_language"],
                    model=policy.model,
                )
            )
            rebuilt = client.prepare(inputs["source"], inputs["conditions"])
            if rebuilt.body != prepared.request:
                raise blocked()
            observation = client.parse(rebuilt, exchange.envelope)
            return False, "", observation.results
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
