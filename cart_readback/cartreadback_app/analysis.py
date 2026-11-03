"""Offline analysis admission and host-owned observation identity checks.

Attempt limits are not dollar authorization or real input-token accounting. No
network transport, credentials or live-enable switch is provided by this module.
"""

from dataclasses import dataclass

from cartreadback_app.responses_adapter import InferenceObservation
from cartreadback_app.validation import AppError, canonical, digest, string


@dataclass(frozen=True)
class AnalysisPolicy:
    """Bound nonfixture injected attempts across all owners of one database."""

    max_attempts: int = 8

    def __post_init__(self) -> None:
        """Reject unbounded settings; this is still an offline-only allowance."""
        if (
            type(self.max_attempts) is not int
            or not 1 <= self.max_attempts <= 64
        ):
            raise AppError("MODEL_UNAVAILABLE", "Invalid analysis policy.", 503)


def checked_observation(observed: object, inputs: dict) -> str:
    """Bind a strictly typed observation to reserved inputs, never model echoes."""
    if type(observed) is not InferenceObservation:
        raise AppError("INVALID_PROPOSAL", "Invalid observation type.", 422)
    source = inputs["catalog"]["source"]
    model = inputs["model"]
    counts = (
        observed.input_tokens,
        observed.output_tokens,
        observed.total_tokens,
    )
    if (
        observed.config_sha256 != model.get("config_sha256")
        or observed.source_sha256 != source["sha256"]
        or type(observed.source_revision) is not int
        or observed.source_revision != source["revision"]
        or observed.conditions_sha256 != digest(inputs["conditions"])
        or observed.model_requested != model.get("model_version")
        or observed.model_returned not in model.get("expected_model_ids", [])
        or any(
            type(count) is not int or not 0 <= count <= 2**31
            for count in counts
        )
        or counts[0] + counts[1] != counts[2]
        or counts[1] > model.get("max_output_tokens", -1)
    ):
        raise AppError(
            "INVALID_PROPOSAL", "Observation identity mismatch.", 422
        )
    string(observed.response_id, "response_id", 256)
    string(observed.request_id, "request_id", 256)
    # Persist only accounting/identity. Proposal text is untrusted and may fail
    # the independent service validator; it must never enter this ledger.
    fields = (
        "config_sha256",
        "source_sha256",
        "source_revision",
        "conditions_sha256",
        "model_requested",
        "model_returned",
        "response_id",
        "request_id",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    )
    return canonical({field: getattr(observed, field) for field in fields})
