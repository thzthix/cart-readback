"""Gemini text request and strict observation client, not an installed runtime.

No service/CLI selects this client. A host must separately provide durable call,
token and cost admission, approved data, and securely provisioned credentials.
The synchronous exchange has no hidden worker or automatic retry.
"""

import base64
import binascii
import json
import re
from dataclasses import asdict, dataclass
from types import MappingProxyType

from cartreadback_app.inference_config import load_bundle
from cartreadback_app.provider_json import PARSER_VERSION, strict_provider_json
from cartreadback_app.responses_adapter import (
    Deadline,
    _validate_results,
    _validated_input,
)
from cartreadback_app.validation import AppError, canonical, digest, text_hash

HOST = "generativelanguage.googleapis.com"
MODEL = "gemini-2.5-flash-lite"
CURRENT_MODEL = "gemini-3.5-flash-lite"
PATH = f"/v1beta/models/{MODEL}:generateContent"
ENDPOINT = f"https://{HOST}{PATH}"
ENDPOINT_PATHS = MappingProxyType(
    {
        f"https://{HOST}/v1beta/models/{model}:generateContent": f"/v1beta/models/{model}:generateContent"
        for model in (MODEL, CURRENT_MODEL)
    }
)
MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 131_072
MAX_OUTPUT_TOKENS = 2048


def unavailable(code="MODEL_UNAVAILABLE") -> AppError:
    """Return a bounded failure without provider payload or secret details."""
    messages = {
        "MODEL_UNAVAILABLE": "Gemini client unavailable.",
        "MODEL_TIMEOUT": "Gemini deadline exceeded; no retry.",
        "MODEL_REFUSED": "Gemini refused this analysis.",
        "MODEL_INCOMPLETE": "Gemini analysis incomplete.",
        "MODEL_BUDGET_EXCEEDED": "Gemini usage unavailable.",
        "INVALID_PROPOSAL": "Invalid Gemini proposal.",
    }
    if code not in messages:
        code = "MODEL_UNAVAILABLE"
    status = (
        422
        if code in {"MODEL_REFUSED", "MODEL_INCOMPLETE", "INVALID_PROPOSAL"}
        else 503
    )
    return AppError(code, messages[code], status)


@dataclass(frozen=True)
class GeminiConfig:
    """Explicit expected provider model version, not a verified account record.

    Only explicit 2.5/3.5 Flash-Lite text contracts are supported. Availability,
    legacy project eligibility and pricing must be reverified before use.
    An alias echo is not proof of a pinned model checkpoint or billed tier.
    """

    expected_model_version: str
    response_language: str = "en"
    model: str = MODEL

    def __post_init__(self):
        """Require exact nonsecret response identity and supported language."""
        if (
            type(self.model) is not str
            or self.model not in (MODEL, CURRENT_MODEL)
            or type(self.expected_model_version) is not str
            or re.fullmatch(
                re.escape(self.model) + r"(?:-[a-z0-9.-]{1,64})?",
                self.expected_model_version,
            )
            is None
            or self.response_language not in ("en", "ko")
        ):
            raise unavailable()


@dataclass(frozen=True)
class PreparedGeminiRequest:
    """Immutable request bytes and exact owned domain inputs."""

    body: bytes
    inputs_json: str
    config_sha256: str

    @property
    def request_sha256(self):
        """Hash the exact bytes intended for generation, never credentials."""
        return text_hash(self.body.decode("utf-8"))


@dataclass(frozen=True)
class GeminiObservation:
    """Normalized provider response facts, not semantic or payment authority."""

    proposal_json: str
    request_sha256: str
    config_sha256: str
    model_requested: str
    model_returned: str
    response_id: str
    input_tokens: int
    candidate_tokens: int
    thought_tokens: int
    output_tokens: int
    total_tokens: int

    @property
    def results(self):
        """Return a fresh domain result value without mutable aliases."""
        return json.loads(self.proposal_json)


def _usage(envelope, config):
    usage = envelope.get("usageMetadata")
    if type(usage) is not dict:
        raise unavailable("MODEL_BUDGET_EXCEEDED")
    counts = [
        usage.get(key)
        for key in (
            "promptTokenCount",
            "candidatesTokenCount",
            "totalTokenCount",
        )
    ]
    thoughts = usage.get("thoughtsTokenCount", 0)
    if (
        any(type(value) is not int or value < 0 for value in counts)
        or type(thoughts) is not int
        or thoughts < 0
        or (config.model == MODEL and thoughts != 0)
        or counts[0] > 1_048_576
        or counts[1] + thoughts > MAX_OUTPUT_TOKENS
        or counts[0] + counts[1] + thoughts != counts[2]
    ):
        raise unavailable("MODEL_BUDGET_EXCEEDED")
    # Zero-valued proto counters may be omitted. This text-only contract does
    # supports thoughts only for 3.5; tools, cache and unknown billing fail.
    for key, value in usage.items():
        if key.endswith("TokenCount") and key not in {
            "promptTokenCount",
            "candidatesTokenCount",
            "totalTokenCount",
            "thoughtsTokenCount",
        }:
            if type(value) is not int or value != 0:
                raise unavailable("MODEL_BUDGET_EXCEEDED")
    for key, expected in (
        ("promptTokensDetails", counts[0]),
        ("candidatesTokensDetails", counts[1]),
        ("cacheTokensDetails", 0),
        ("toolUsePromptTokensDetails", 0),
    ):
        if key in usage:
            details = usage[key]
            if details == [] and expected == 0:
                continue
            if (
                type(details) is not list
                or len(details) != 1
                or type(details[0]) is not dict
                or set(details[0]) != {"modality", "tokenCount"}
                or details[0]["modality"] != "TEXT"
                or type(details[0]["tokenCount"]) is not int
                or details[0]["tokenCount"] != expected
            ):
                raise unavailable("MODEL_BUDGET_EXCEEDED")
    for key in usage:
        if key.endswith("TokensDetails") and key not in {
            "promptTokensDetails",
            "candidatesTokensDetails",
            "cacheTokensDetails",
            "toolUsePromptTokensDetails",
        }:
            raise unavailable("MODEL_BUDGET_EXCEEDED")
    return counts[0], counts[1], thoughts, counts[1] + thoughts, counts[2]


@dataclass(frozen=True)
class GeminiAccounting:
    """Bounded independent usage, with no proposal text or continuation data."""

    response_id_sha256: str
    model: str
    input_tokens: int
    candidate_tokens: int
    thought_tokens: int
    output_tokens: int
    total_tokens: int
    accounting_contract: str
    response_status: str = "completed"
    usage_finality: str = "terminal-model-usage"


def classify_gemini_usage(raw: bytes, config: GeminiConfig) -> GeminiAccounting:
    """Validate usage independently of refused, incomplete or invalid prose.

    Exact model and coherent counters are required. Explicit non-text/tool/cache
    activity retains supported counters but makes the accounting contract UNKNOWN.
    HTTP framing and deadline faults are separately owned by the transport host.
    """
    if type(config) is not GeminiConfig:
        raise unavailable()
    config.__post_init__()
    envelope = strict_provider_json(
        raw, max_bytes=MAX_RESPONSE_BYTES, max_depth=32
    )
    response_id = envelope.get("responseId")
    if (
        envelope.get("modelVersion") != config.expected_model_version
        or envelope.get("error") is not None
        or type(response_id) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", response_id) is None
    ):
        raise unavailable("MODEL_BUDGET_EXCEEDED")
    usage = _usage(envelope, config)
    conflict = False
    for key in ("toolUse", "toolUsage", "tools", "cachedContent"):
        if key in envelope and envelope[key] not in (None, [], {}):
            conflict = True
    candidates = envelope.get("candidates")
    if type(candidates) is list:
        for candidate in candidates:
            if type(candidate) is not dict:
                continue
            if any(
                key in candidate
                for key in ("groundingMetadata", "urlContextMetadata")
            ):
                conflict = True
            content = candidate.get("content")
            if type(content) is not dict:
                continue
            parts = content.get("parts")
            if type(parts) is list:
                for part in parts:
                    if type(part) is dict and set(part) - {
                        "text",
                        "thought",
                        "thoughtSignature",
                    }:
                        conflict = True
    return GeminiAccounting(
        text_hash(response_id),
        config.model,
        *usage,
        "unsupported-provider-activity"
        if conflict
        else "no-explicit-profile-conflict",
    )


class GeminiClient:
    """Prepare/parse Gemini requests, with explicit synchronous transport only.

    This is not an InferenceAdapter and cannot be passed to Service as a
    proposal source. No credential loading, budget authority or live selection
    is inferred from constructing it. All transport exceptions are sanitized.
    """

    def __init__(self, config: GeminiConfig, transport=None):
        """Load verified shared evidence assets without I/O or credentials."""
        if type(config) is not GeminiConfig:
            raise unavailable()
        config.__post_init__()
        self._config = config
        self._bundle = load_bundle()
        self.transport = transport
        self._metadata = {
            "provider": "google-gemini-generate-content",
            "model_version": config.model,
            "adapter_version": "gemini-generation-client-v1",
            "parser_version": PARSER_VERSION,
            "prompt_bundle_sha256": digest(
                json.loads(self.bundle.manifest_json)
            ),
            "endpoint": f"https://{HOST}/v1beta/models/{config.model}:generateContent",
            "execution_mode": "client-unselected",
            "is_fixture": False,
            **asdict(config),
        }
        self._metadata["config_sha256"] = digest(self._metadata)

    @property
    def config(self):
        """Expose the immutable selected configuration without a setter."""
        return self._config

    @property
    def bundle(self):
        """Expose the verified immutable prompt bundle without a setter."""
        return self._bundle

    @property
    def metadata(self):
        """Return host identity only, not evidence of an enabled provider."""
        return json.loads(canonical(self._metadata))

    def prepare(
        self, source: dict, conditions: list[dict]
    ) -> PreparedGeminiRequest:
        """Build canonical text-only generation bytes without dispatching."""
        inputs = _validated_input(source, conditions)
        request_input = {
            **inputs,
            "response_language": self.config.response_language,
        }
        before, rest = self.bundle.user_template.split("{{request_json}}")
        middle, after = rest.split("{{output_schema_json}}")
        user = (
            before
            + canonical(request_input)
            + middle
            + self.bundle.wire_schema_json
            + after
        )
        body = canonical(
            {
                "systemInstruction": {"parts": [{"text": self.bundle.system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "candidateCount": 1,
                    "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": json.loads(
                        self.bundle.wire_schema_json
                    ),
                    "thinkingConfig": (
                        {"thinkingBudget": 0}
                        if self.config.model == MODEL
                        else {"thinkingLevel": "MINIMAL"}
                    ),
                },
            }
        ).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise unavailable("MODEL_BUDGET_EXCEEDED")
        return PreparedGeminiRequest(
            body, canonical(inputs), self._metadata["config_sha256"]
        )

    def _check_prepared(self, prepared):
        if type(prepared) is not PreparedGeminiRequest:
            raise unavailable()
        try:
            inputs = json.loads(prepared.inputs_json)
            rebuilt = self.prepare(inputs["source"], inputs["conditions"])
            if prepared != rebuilt:
                raise unavailable()
            return inputs
        except Exception:
            raise unavailable() from None

    def parse(
        self, prepared: PreparedGeminiRequest, raw: bytes
    ) -> GeminiObservation:
        """Validate actual returned facts without repairing provider output."""
        inputs = self._check_prepared(prepared)
        try:
            envelope = strict_provider_json(
                raw, max_bytes=MAX_RESPONSE_BYTES, max_depth=32
            )
            if envelope.get("error") is not None:
                raise unavailable()
            usage = _usage(envelope, self.config)
            if (
                envelope.get("modelVersion")
                != self.config.expected_model_version
            ):
                raise unavailable("INVALID_PROPOSAL")
            response_id = envelope.get("responseId")
            if (
                type(response_id) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", response_id) is None
            ):
                raise unavailable("INVALID_PROPOSAL")
            feedback = envelope.get("promptFeedback", {})
            if type(feedback) is not dict or feedback.get(
                "blockReason"
            ) not in (None, "BLOCK_REASON_UNSPECIFIED"):
                raise unavailable("MODEL_REFUSED")
            candidates = envelope.get("candidates")
            if (
                type(candidates) is not list
                or len(candidates) != 1
                or type(candidates[0]) is not dict
            ):
                raise unavailable("MODEL_INCOMPLETE")
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                raise unavailable("MODEL_INCOMPLETE")
            if "index" in candidate and (
                type(candidate["index"]) is not int or candidate["index"] != 0
            ):
                raise unavailable("INVALID_PROPOSAL")
            ratings = candidate.get("safetyRatings", [])
            if type(ratings) is not list or any(
                type(item) is not dict
                or item.get("blocked", False) is not False
                for item in ratings
            ):
                raise unavailable("MODEL_REFUSED")
            content = candidate.get("content")
            if (
                type(content) is not dict
                or set(content) != {"role", "parts"}
                or content["role"] != "model"
            ):
                raise unavailable("INVALID_PROPOSAL")
            parts = content["parts"]
            if (
                type(parts) is not list
                or len(parts) != 1
                or type(parts[0]) is not dict
                or not {"text"}
                <= set(parts[0])
                <= {"text", "thought", "thoughtSignature"}
                or type(parts[0]["text"]) is not str
                or parts[0].get("thought", False) is not False
            ):
                raise unavailable("INVALID_PROPOSAL")
            if "thoughtSignature" in parts[0]:
                signature = parts[0]["thoughtSignature"]
                if (
                    type(signature) is not str
                    or not 1 <= len(signature) <= 65_536
                ):
                    raise unavailable("INVALID_PROPOSAL")
                try:
                    if not base64.b64decode(signature, validate=True):
                        raise unavailable("INVALID_PROPOSAL")
                except (ValueError, binascii.Error):
                    raise unavailable("INVALID_PROPOSAL") from None
                # Single-turn, no-tools contract: signatures are opaque provider
                # continuation data, not authority. Never persist or replay them.
            wire = strict_provider_json(
                parts[0]["text"].encode("utf-8"), max_bytes=65_536, max_depth=8
            )
            results = _validate_results(
                inputs["source"], inputs["conditions"], wire
            )
            return GeminiObservation(
                canonical(results),
                prepared.request_sha256,
                prepared.config_sha256,
                self.config.model,
                envelope["modelVersion"],
                response_id,
                *usage,
            )
        except AppError as error:
            raise unavailable(error.code) from None
        except Exception:
            raise unavailable("INVALID_PROPOSAL") from None

    def exchange(
        self, prepared: PreparedGeminiRequest, *, deadline: Deadline
    ) -> GeminiObservation:
        """Run one explicit exchange; host retains lifetime and UNKNOWN handling."""
        self._check_prepared(prepared)
        if type(deadline) is not Deadline or self.transport is None:
            raise unavailable()
        try:
            deadline.remaining()
            raw = self.transport.send(
                self._metadata["endpoint"], prepared.body, deadline=deadline
            )
            deadline.remaining()
            result = self.parse(prepared, raw)
            deadline.remaining()
            return result
        except AppError as error:
            raise unavailable(error.code) from None
        except Exception:
            raise unavailable() from None
