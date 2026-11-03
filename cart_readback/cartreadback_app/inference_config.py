"""Immutable offline adapter identity and exact reviewed prompt assets."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from cartreadback_app.provider_json import PARSER_VERSION
from cartreadback_app.validation import AppError, digest

ENDPOINT = "https://api.openai.com/v1/responses"
MODEL = "gpt-6-luna"
ADAPTER_VERSION = "responses-offline-wire-v2-tier"
MANIFEST_SHA256 = (
    "5960e0e6e078e4defc5b00ad7afb73bc6dcd0a202811b6b11e9fa8e09ad4832b"
)
LOCAL_SCHEMA_SHA256 = (
    "7a49011e3042d3371bdea11aae201ff4a8d8a2fd5cda4fcd67b23bcf31c7fb57"
)


def _unavailable() -> AppError:
    return AppError(
        "MODEL_UNAVAILABLE", "Unsupported offline adapter config.", 503
    )


@dataclass(frozen=True)
class InferenceConfig:
    """Trusted non-secret settings; this does not authorize real dispatch.

    No environment/config-file credential lookup or live-enable setting exists.
    A future production transport must separately implement count/budget gates.
    Shorter deadlines are permitted for deterministic offline timeout tests.
    """

    response_language: str = "en"
    model: str = MODEL
    expected_model_ids: tuple[str, ...] = (MODEL,)
    overall_timeout_seconds: float = 20.0
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 12.0
    service_tier: str = "default"
    execution_mode: str = "offline-injected-only"

    def __post_init__(self) -> None:
        """Reject unknown modes/models/settings before any transport call."""
        if (
            self.response_language not in ("en", "ko")
            or self.model != MODEL
            or type(self.expected_model_ids) is not tuple
            or self.expected_model_ids != (MODEL,)
            or self.service_tier != "default"
            or self.execution_mode != "offline-injected-only"
        ):
            raise _unavailable()
        for value, maximum in (
            (self.overall_timeout_seconds, 20),
            (self.connect_timeout_seconds, 3),
            (self.read_timeout_seconds, 12),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 < value <= maximum
            ):
                raise _unavailable()


@dataclass(frozen=True)
class PromptBundle:
    """Verified exact strings, never mutable dictionaries from callers."""

    system: str
    user_template: str
    wire_schema_json: str
    manifest_json: str


def load_bundle() -> PromptBundle:
    """Load only shipped v2 assets and verify frozen local schema unchanged."""
    root = Path(__file__).resolve().parents[1] / "prompts"
    try:
        manifest_bytes = (root / "v2-wire/manifest.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
            raise _unavailable()
        if (
            hashlib.sha256((root / "schema.json").read_bytes()).hexdigest()
            != LOCAL_SCHEMA_SHA256
        ):
            raise _unavailable()
        manifest = json.loads(manifest_bytes)
        content = {}
        for name, expected in manifest["artifact_sha256"].items():
            raw = (root / "v2-wire" / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise _unavailable()
            content[name] = raw.decode("utf-8", errors="strict")
        return PromptBundle(
            content["arm-B-system.txt"],
            content["readback-user-template.txt"],
            content["schema.json"],
            manifest_bytes.decode("utf-8"),
        )
    except (OSError, UnicodeError, ValueError, KeyError) as error:
        raise _unavailable() from error


def configuration_metadata(
    config: InferenceConfig, bundle: PromptBundle
) -> dict:
    """Generate host-owned non-secret configuration identity, not model echo."""
    manifest = json.loads(bundle.manifest_json)
    identity = {
        **asdict(config),
        "provider": "openai-responses",
        "endpoint": ENDPOINT,
        "model_version": config.model,
        "prompt_version": manifest["prompt_version"],
        "prompt_bundle_sha256": digest(manifest["artifact_sha256"]),
        "local_schema_version": "cartreadback-proposal-schema-v1",
        "local_schema_sha256": LOCAL_SCHEMA_SHA256,
        "prompt_manifest_sha256": MANIFEST_SHA256,
        "wire_schema_version": manifest["wire_schema_version"],
        "wire_schema_sha256": manifest["artifact_sha256"]["schema.json"],
        "adapter_version": ADAPTER_VERSION,
        "validator_version": "strict-spans-v1+ordered-results-v1",
        "parser_version": PARSER_VERSION,
        "max_request_bytes": 65_536,
        "max_envelope_bytes": 131_072,
        "max_envelope_depth": 32,
        "max_wire_bytes": 65_536,
        "max_wire_depth": 8,
        "max_output_tokens": 2048,
        "reasoning_effort": "none",
        "temperature": "omitted",
        "top_p": "omitted",
        "seed": "omitted",
        "tools": [],
        "history": "none",
        "prompt_cache_options": {"mode": "explicit"},
        "prompt_cache_breakpoints": "omitted",
        "store": False,
        "background": False,
        "stream": False,
        "retries": 0,
        "concurrency": 1,
        "token_count_and_cost_ledger": "not-implemented-live-blocked",
        "is_fixture": False,
    }
    # Normalize tuples to JSON values so metadata round trips stably.
    identity = json.loads(json.dumps(identity))
    return {**identity, "config_sha256": digest(identity)}
