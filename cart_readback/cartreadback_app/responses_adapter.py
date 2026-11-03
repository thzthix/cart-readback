"""Offline-tested Responses wire boundary with an explicitly injected transport.

There is no network implementation, credential lookup or live runner here. The
service can explicitly inject this adapter for offline lifecycle tests. Fabricated test envelopes exercise defensive local behavior,
not genuine vendor behavior or provider schema acceptance.
"""

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol

from cartreadback_app.inference import validate_proposal
from cartreadback_app.inference_budget import request_hash
from cartreadback_app.inference_config import (
    ENDPOINT,
    InferenceConfig,
    configuration_metadata,
    load_bundle,
)
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.validation import (
    AppError,
    canonical,
    digest,
    integer,
    object_fields,
    string,
    text_hash,
)
from cartreadback_app.validation import (
    conditions as validate_conditions,
)


def _error(code: str = "INVALID_PROPOSAL") -> AppError:
    messages = {
        "INVALID_PROPOSAL": ("Invalid model proposal.", 422),
        "MODEL_UNAVAILABLE": ("Model transport unavailable.", 503),
        "MODEL_TIMEOUT": ("Model deadline exceeded; no retry.", 503),
        "MODEL_REFUSED": ("Model refused this analysis.", 422),
        "MODEL_INCOMPLETE": ("Model analysis incomplete.", 422),
        "MODEL_BUDGET_EXCEEDED": (
            "Model usage unavailable; further calls blocked.",
            503,
        ),
    }
    if code not in messages:
        code = "MODEL_UNAVAILABLE"
    message, status = messages[code]
    return AppError(code, message, status)


@dataclass(frozen=True)
class Deadline:
    """Absolute monotonic deadline passed through transport and body reading."""

    expires_at: float
    connect_limit: float
    read_limit: float

    def remaining(self) -> float:
        """Return remaining seconds, raising a sanitized error when expired."""
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise _error("MODEL_TIMEOUT")
        return remaining

    def connect_timeout(self) -> float:
        """Limit a future transport's connection wait to the overall deadline."""
        return min(self.connect_limit, self.remaining())

    def read_timeout(self) -> float:
        """Limit each future transport read to the same overall deadline."""
        return min(self.read_limit, self.remaining())


@dataclass(frozen=True)
class WireResponse:
    """HTTP status/request identity and bounded-on-consumption body chunks.

    A future real transport owns TLS, fixed-host routing, no redirects, no retries,
    sanitized request-ID extraction, connection/read deadlines and closing its
    response on generator exit. It must not return headers or credentials.
    """

    status_code: int
    request_id: str
    body: Iterable[bytes]
    close: Callable[[], None] | None = None


class ResponsesTransport(Protocol):
    """Injected offline seam; no production dispatch implementation is shipped."""

    def send(
        self, endpoint: str, body: bytes, *, deadline: Deadline
    ) -> WireResponse:
        """Return a response without retry, fallback or arbitrary redirects."""
        ...


@dataclass(frozen=True)
class InferenceObservation:
    """Validated result and host-recorded non-secret provenance for one call."""

    proposal_json: str
    config_sha256: str
    source_sha256: str
    source_revision: int
    conditions_sha256: str
    model_requested: str
    model_returned: str
    response_id: str
    request_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    request_sha256: str
    service_tier_requested: str
    service_tier_returned: str

    @property
    def results(self) -> list[dict]:
        """Return a fresh result value so observations cannot be mutated."""
        return json.loads(self.proposal_json)


def _validated_input(source: dict, conditions: list[dict]) -> dict:
    """Copy only the exact permitted domain fields before crossing the seam."""
    try:
        object_fields(source, {"source_id", "revision", "sha256", "text"})
        string(source["source_id"], "source_id")
        integer(source["revision"], "source_revision", 1, 2**63 - 1)
        string(source["text"], "source_text", 16000, multiline=True)
        if source["sha256"] != text_hash(source["text"]):
            raise _error()
        if type(conditions) is not list or not 1 <= len(conditions) <= 2:
            raise _error()
        ids = []
        choices = []
        for condition in conditions:
            object_fields(condition, {"condition_id", "kind", "value"})
            ids.append(string(condition["condition_id"], "condition_id"))
            choices.append(
                {"kind": condition["kind"], "value": condition["value"]}
            )
        validate_conditions(choices)
        if len(set(ids)) != len(ids):
            raise _error()
        # Exact serialization also provides an owned snapshot, not a caller alias.
        return json.loads(
            canonical({"source": source, "conditions": conditions})
        )
    except (AppError, UnicodeError, ValueError, TypeError) as error:
        raise _error() from error


def _provider_text(envelope: dict, expected_models: tuple[str, ...]) -> str:
    if envelope.get("error") is not None:
        raise _error("MODEL_UNAVAILABLE")
    if (
        envelope.get("status") != "completed"
        or envelope.get("incomplete_details") is not None
    ):
        raise _error("MODEL_INCOMPLETE")
    if (
        envelope.get("model") not in expected_models
        or envelope.get("object") != "response"
    ):
        raise _error()
    output = envelope.get("output")
    if type(output) is not list or len(output) != 1:
        raise _error()
    message = output[0]
    if type(message) is not dict or (
        message.get("type") != "message" or message.get("role") != "assistant"
    ):
        raise _error()
    if message.get("status") != "completed":
        raise _error("MODEL_INCOMPLETE")
    content = message.get("content")
    if type(content) is not list:
        raise _error("MODEL_INCOMPLETE")
    if any(
        type(item) is dict and item.get("type") == "refusal" for item in content
    ):
        raise _error("MODEL_REFUSED")
    if not content:
        raise _error("MODEL_INCOMPLETE")
    if len(content) != 1 or type(content[0]) is not dict:
        raise _error()
    if content[0].get("type") != "output_text":
        raise _error()
    text = content[0].get("text")
    if type(text) is not str or not text.strip():
        raise _error("MODEL_INCOMPLETE")
    return text


def _validate_results(
    source: dict, conditions: list[dict], wire: dict
) -> list[dict]:
    try:
        object_fields(wire, {"results"})
        results = validate_proposal(source, conditions, wire["results"])
        # Input validation bounds IDs/source fields. The unchanged full local
        # validator enforces all remaining local schema rules and exact spans.
        if [item["condition_id"] for item in results] != [
            item["condition_id"] for item in conditions
        ]:
            raise _error()
        return results
    except AppError as error:
        raise _error() from error


def _usage(envelope: dict, maximum_output: int) -> tuple[int, int, int]:
    usage = envelope.get("usage")
    if type(usage) is not dict:
        raise _error("MODEL_BUDGET_EXCEEDED")
    fields = ("input_tokens", "output_tokens", "total_tokens")
    counts = [usage.get(field) for field in fields]
    if any(type(value) is not int or value < 0 for value in counts):
        raise _error("MODEL_BUDGET_EXCEEDED")
    if counts[0] + counts[1] != counts[2] or counts[1] > maximum_output:
        raise _error("MODEL_BUDGET_EXCEEDED")
    return tuple(counts)


def build_text_request(
    source, conditions, *, config, bundle, metadata
) -> bytes:
    """Build the shared exact text payload without accounting or dispatch."""
    request = _validated_input(source, conditions)
    request["response_language"] = config.response_language
    # Split trusted placeholders before insertion: source placeholders are
    # serialized as inert data and never recursively expanded.
    template = bundle.user_template
    before, rest = template.split("{{request_json}}")
    middle, after = rest.split("{{output_schema_json}}")
    user = (
        before + canonical(request) + middle + bundle.wire_schema_json + after
    )
    payload = {
        "model": config.model,
        "service_tier": config.service_tier,
        "instructions": bundle.system,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user}],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cartreadback_proposal_v1",
                "strict": True,
                "schema": json.loads(bundle.wire_schema_json),
            }
        },
        "reasoning": {"effort": "none"},
        "tools": [],
        "prompt_cache_options": {"mode": "explicit"},
        "store": False,
        "background": False,
        "stream": False,
        "max_output_tokens": metadata["max_output_tokens"],
    }
    raw = canonical(payload).encode("utf-8")
    if len(raw) > metadata["max_request_bytes"]:
        raise AppError("MODEL_BUDGET_EXCEEDED", "Model request too large.", 422)
    return raw


class OfflineResponsesAdapter:
    """One-attempt wire adapter, unavailable to the default fixture service.

    The caller deadline covers request preparation, transport, body consumption,
    parsing and validation. A timed-out worker may still be finishing its injected
    transport. This instance is then permanently blocked and cannot redispatch or
    overlap a second call. Real transport cancellation/accounting remain live gates.
    """

    def __init__(
        self,
        transport: ResponsesTransport,
        config: InferenceConfig | None = None,
    ) -> None:
        """Initialize verified immutable assets/settings without reading secrets."""
        self._config = config if config is not None else InferenceConfig()
        if type(self._config) is not InferenceConfig:
            raise _error("MODEL_UNAVAILABLE")
        self._bundle = load_bundle()
        self._metadata = configuration_metadata(self._config, self._bundle)
        self._transport = transport
        self._flight = threading.Lock()
        self._blocked = False

    @property
    def metadata(self) -> dict:
        """Return stable host metadata without a mutable caller alias."""
        return json.loads(canonical(self._metadata))

    def build_request(self, source: dict, conditions: list[dict]) -> bytes:
        """Build the exact intended payload without dispatching or token counting."""
        return build_text_request(
            source,
            conditions,
            config=self._config,
            bundle=self._bundle,
            metadata=self._metadata,
        )

    def propose(self, source: dict, conditions: list[dict]) -> list[dict]:
        """Return strictly validated results from one injected offline exchange."""
        return self.observe(source, conditions).results

    def observe(
        self,
        source: dict,
        conditions: list[dict],
        *,
        expected_request_sha256: str | None = None,
    ) -> InferenceObservation:
        """Record identity/usage and bound the complete exchange, without retry."""
        if not self._flight.acquire(blocking=False):
            raise _error("MODEL_UNAVAILABLE")
        try:
            if self._blocked:
                raise _error("MODEL_UNAVAILABLE")
            deadline = Deadline(
                time.monotonic() + self._config.overall_timeout_seconds,
                self._config.connect_timeout_seconds,
                self._config.read_timeout_seconds,
            )
            inputs = _validated_input(source, conditions)
            request = self.build_request(inputs["source"], inputs["conditions"])
            if (
                expected_request_sha256 is not None
                and request_hash(request) != expected_request_sha256
            ):
                raise _error("MODEL_BUDGET_EXCEEDED")
            deadline.remaining()
            completed = queue.Queue(maxsize=1)

            def run() -> None:
                try:
                    result = self._exchange(request, inputs, deadline)
                # The injected boundary may raise arbitrary exceptions.
                # Sanitize failures; never convert them into a success.
                except Exception as error:
                    completed.put((False, error))
                else:
                    completed.put((True, result))

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                success, result = completed.get(timeout=deadline.remaining())
                deadline.remaining()
            except (queue.Empty, AppError) as error:
                self._blocked = True
                raise _error("MODEL_TIMEOUT") from error
            if not success:
                if isinstance(result, AppError):
                    if result.code in {
                        "MODEL_TIMEOUT",
                        "MODEL_BUDGET_EXCEEDED",
                    }:
                        self._blocked = True
                    raise _error(result.code) from None
                if isinstance(result, TimeoutError):
                    self._blocked = True
                    raise _error("MODEL_TIMEOUT") from None
                raise _error("MODEL_UNAVAILABLE") from None
            return result
        finally:
            self._flight.release()

    def _exchange(
        self, request: bytes, inputs: dict, deadline: Deadline
    ) -> InferenceObservation:
        response = self._transport.send(ENDPOINT, request, deadline=deadline)
        if type(response) is not WireResponse:
            raise _error("MODEL_UNAVAILABLE")
        try:
            return self._read_response(
                response, inputs, deadline, request_hash(request)
            )
        finally:
            if response.close is not None:
                response.close()

    def _read_response(
        self,
        response: WireResponse,
        inputs: dict,
        deadline: Deadline,
        request_sha256: str,
    ) -> InferenceObservation:
        deadline.remaining()
        if type(response.status_code) is not int:
            raise _error("MODEL_UNAVAILABLE")
        if response.status_code != 200:
            raise _error("MODEL_UNAVAILABLE")
        try:
            string(response.request_id, "request_id", 256)
        except AppError as error:
            raise _error("MODEL_BUDGET_EXCEEDED") from error
        chunks = bytearray()
        iterator = iter(response.body)
        try:
            for chunk in iterator:
                deadline.remaining()
                if type(chunk) is not bytes:
                    raise _error()
                if (
                    len(chunks) + len(chunk)
                    > self._metadata["max_envelope_bytes"]
                ):
                    raise _error()
                chunks.extend(chunk)
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
        deadline.remaining()
        envelope = strict_provider_json(
            bytes(chunks),
            max_bytes=self._metadata["max_envelope_bytes"],
            max_depth=self._metadata["max_envelope_depth"],
        )
        if envelope.get("service_tier") != self._config.service_tier:
            raise _error("MODEL_BUDGET_EXCEEDED")
        text = _provider_text(envelope, self._config.expected_model_ids)
        wire = strict_provider_json(
            text.encode("utf-8", errors="strict"),
            max_bytes=self._metadata["max_wire_bytes"],
            max_depth=self._metadata["max_wire_depth"],
        )
        results = _validate_results(
            inputs["source"], inputs["conditions"], wire
        )
        usage = _usage(envelope, self._metadata["max_output_tokens"])
        try:
            response_id = string(envelope.get("id"), "response_id", 256)
        except AppError as error:
            raise _error("MODEL_BUDGET_EXCEEDED") from error
        deadline.remaining()
        return InferenceObservation(
            canonical(results),
            self._metadata["config_sha256"],
            inputs["source"]["sha256"],
            inputs["source"]["revision"],
            digest(inputs["conditions"]),
            self._config.model,
            envelope["model"],
            response_id,
            response.request_id,
            *usage,
            request_sha256,
            self._config.service_tier,
            envelope["service_tier"],
        )
