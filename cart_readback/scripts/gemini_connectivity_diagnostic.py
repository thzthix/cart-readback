"""Exercise one fixed synthetic diagnostic with fabricated transport only.

The default entry point has no network, credential, database or asset activity.
An unselected wire reuses reviewed HTTPS code via lazy imports only. Injected
metadata and grants are test data, not authenticated evidence or approval. The
production entry point is unconditionally NOT_RUN, never a live launcher or an
alternative application-analysis approval path.
"""

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from typing import Protocol

MODEL = "gemini-3.5-flash-lite"
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + MODEL
    + ":generateContent"
)
WORKFLOW_PATH = ".github/workflows/gemini-connectivity-diagnostic.yml"
MAX_INPUT_RESERVATION = 1048576
MAX_OUTPUT_RESERVATION = 2048
MAX_OUTPUT_TOKENS = 32
TIMEOUT_SECONDS = 20
REQUEST = json.dumps(
    {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "Synthetic connectivity diagnostic. Reply READY."}
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "candidateCount": 1,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
    },
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
REQUEST_SHA256 = hashlib.sha256(REQUEST).hexdigest()

_IDENTITY_KEYS = {
    "repository_id",
    "workflow_id",
    "actor_id",
    "path",
    "ref",
    "head_sha",
}
_WINDOW_KEYS = {"valid_from", "expires_at"}
_RUN_KEYS = _IDENTITY_KEYS | {
    "id",
    "run_number",
    "run_attempt",
    "event",
    "created_at",
    "status",
    "conclusion",
}
_GRANT_KEYS = _WINDOW_KEYS | {
    "schema",
    "request_sha256",
    "endpoint",
    "model",
    "expected_model_version",
    "max_calls",
    "max_total_input_tokens",
    "max_total_output_tokens",
    "max_micro_usd",
    "admission_mode",
    "exact_request_owner_grant_sha256",
    "credential_transmission_grant_sha256",
    "free_project_facts_sha256",
    "zero_cost_compute_facts_sha256",
}


class FabricatedTransport(Protocol):
    """An injected offline fixture, never a production adapter."""

    evidence_kind: str

    def exchange(
        self, endpoint: str, payload: bytes, timeout_seconds: int
    ) -> tuple[int, bytes]:
        """Return fabricated HTTP status and bytes without network access."""


class UnselectedHTTPSWire:
    """Reuse reviewed HTTPS mechanics, never selected by this CLI or workflow.

    Explicit trusted host callbacks must enforce a permanent diagnostic claim,
    exact request grant, credential binding and expiry at every I/O step. Their
    presence is not evidence those external facts exist. OfflineDiagnostic rejects
    this provider-capable object. No new approval or credential resolver exists.
    """

    evidence_kind = "unselected-provider-runtime"

    def __init__(
        self,
        borrow_credential: Callable,
        claim_guard: Callable,
        *,
        connection_factory: Callable | None = None,
    ) -> None:
        """Retain explicit seams without importing app code or doing I/O."""
        if not callable(borrow_credential) or not callable(claim_guard):
            raise ValueError("unsupported diagnostic wire")
        if connection_factory is not None and not callable(connection_factory):
            raise ValueError("unsupported diagnostic wire")
        self._borrow = borrow_credential
        self._guard = claim_guard
        self._factory = connection_factory
        self._lock = threading.Lock()
        self._used = False

    def exchange(
        self, endpoint: str, payload: bytes, timeout_seconds: int
    ) -> tuple[int, bytes]:
        """Consume one fixed request; return bytes only to the private validator.

        Failure is sanitized and permanently consumes this object. A real host
        must persist its burn independently before constructing or using it.
        """
        with self._lock:
            if self._used:
                raise ValueError("diagnostic wire unavailable")
            self._used = True
        try:
            if (
                type(endpoint) is not str
                or endpoint != ENDPOINT
                or type(payload) is not bytes
                or payload != REQUEST
                or type(timeout_seconds) is not int
                or timeout_seconds != TIMEOUT_SECONDS
            ):
                raise ValueError()
            # Exact-main import closure has no top-level semantic-asset reads.
            # Never construct GeminiClient or OfflineResponsesAdapter here.
            from cartreadback_app.gemini_http import (
                GeminiHTTPTransport,
                unselected_gemini_connection,
            )
            from cartreadback_app.responses_adapter import Deadline

            def guard(**kwargs):
                if kwargs["endpoint"] != ENDPOINT or kwargs["body"] != REQUEST:
                    raise ValueError()
                return self._guard(**kwargs)

            transport = GeminiHTTPTransport(
                self._factory or unselected_gemini_connection,
                self._borrow,
                guard,
            )
            deadline = Deadline(time.monotonic() + TIMEOUT_SECONDS, 3.0, 12.0)
            raw = transport.send(ENDPOINT, REQUEST, deadline=deadline)
            if type(raw) is not bytes or not 0 < len(raw) <= 16384:
                raise ValueError()
            return 200, raw
        except BaseException:
            raise ValueError("diagnostic wire outcome unknown") from None


def _shape(value: object, keys: set[str]) -> bool:
    return type(value) is dict and value.keys() == keys


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _digest(value: object, length: int = 64) -> bool:
    return (
        type(value) is str
        and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None
    )


def _window(value: dict, now: int) -> bool:
    return (
        _integer(now)
        and _integer(value["valid_from"])
        and _integer(value["expires_at"])
        and 0 < value["expires_at"] - value["valid_from"] <= 86400
        and value["valid_from"] <= now < value["expires_at"]
    )


def _identity(value: dict) -> bool:
    return (
        all(
            _integer(value[k], 1)
            for k in ("repository_id", "workflow_id", "actor_id")
        )
        and value["path"] == WORKFLOW_PATH
        and value["ref"] == "refs/heads/main"
        and _digest(value["head_sha"], 40)
    )


def fabricated_fence_consistent(
    enrollment: object, snapshot: object, now: int
) -> bool:
    """Check synthetic projections, without authenticating or enrolling them.

    The future authenticated transport, immutable enrollment and permanent
    retirement policy are unsupported. A True result is never an execution grant.
    """
    if not _shape(enrollment, _IDENTITY_KEYS | _WINDOW_KEYS):
        return False
    if not _identity(enrollment) or not _window(enrollment, now):
        return False
    if not _shape(
        snapshot,
        {
            "evidence_kind",
            "http_status",
            "next_page",
            "truncated",
            "current",
            "history",
        },
    ):
        return False
    if (
        snapshot["evidence_kind"] != "fabricated-offline"
        or type(snapshot["http_status"]) is not int
        or snapshot["http_status"] != 200
        or snapshot["next_page"] is not None
        or snapshot["truncated"] is not False
    ):
        return False
    current, history = snapshot["current"], snapshot["history"]
    if not _shape(current, _RUN_KEYS) or not _identity(current):
        return False
    if any(current[k] != enrollment[k] for k in _IDENTITY_KEYS):
        return False
    if (
        not _integer(current["id"], 1)
        or type(current["run_number"]) is not int
        or current["run_number"] != 1
        or type(current["run_attempt"]) is not int
        or current["run_attempt"] != 1
        or current["event"] != "workflow_dispatch"
        or current["status"] != "in_progress"
        or current["conclusion"] is not None
        or not _integer(current["created_at"])
        or not enrollment["valid_from"] <= current["created_at"] <= now
    ):
        return False
    if not _shape(history, {"total_count", "workflow_runs"}):
        return False
    runs = history["workflow_runs"]
    return (
        type(history["total_count"]) is int
        and history["total_count"] == 1
        and type(runs) is list
        and len(runs) == 1
        and _shape(runs[0], _RUN_KEYS)
        and all(
            type(runs[0][k]) is type(v) and runs[0][k] == v
            for k, v in current.items()
        )
    )


def _grant_consistent(grant: object, enrollment: dict, now: int) -> bool:
    if not _shape(grant, _GRANT_KEYS) or not _window(grant, now):
        return False
    fixed = {
        "schema": "fabricated-connectivity-grant-v1",
        "request_sha256": REQUEST_SHA256,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "expected_model_version": MODEL,
        "max_calls": 1,
        "max_total_input_tokens": MAX_INPUT_RESERVATION,
        "max_total_output_tokens": MAX_OUTPUT_RESERVATION,
        "max_micro_usd": 0,
        "admission_mode": "externally-verified-free-tier",
    }
    if any(
        type(grant[k]) is not type(v) or grant[k] != v for k, v in fixed.items()
    ):
        return False
    if not (
        enrollment["valid_from"]
        <= grant["valid_from"]
        < grant["expires_at"]
        <= enrollment["expires_at"]
    ):
        return False
    return all(_digest(grant[k]) for k in _GRANT_KEYS if k.endswith("_sha256"))


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite")


def _safe_observation(status: int, body: bytes) -> dict | None:
    if type(status) is not int or status != 200:
        return None
    if type(body) is not bytes or not 0 < len(body) <= 16384:
        return None
    try:
        data = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        return None
    required = {"modelVersion", "usageMetadata", "candidates"}
    if type(data) is not dict or not required <= data.keys():
        return None
    if not data.keys() <= required | {"responseId"}:
        return None
    if "responseId" in data and (
        type(data["responseId"]) is not str
        or re.fullmatch(r"[A-Za-z0-9._~+/-]{1,256}={0,2}", data["responseId"])
        is None
    ):
        return None
    if data["modelVersion"] != MODEL:
        return None
    usage, candidates = data["usageMetadata"], data["candidates"]
    keys = {
        "promptTokenCount",
        "candidatesTokenCount",
        "thoughtsTokenCount",
        "totalTokenCount",
    }
    if not _shape(usage, keys) or not all(_integer(v) for v in usage.values()):
        return None
    prompt, answer, thoughts, total = (
        usage[k]
        for k in (
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
            "totalTokenCount",
        )
    )
    if not (
        0 < prompt <= MAX_INPUT_RESERVATION
        and 0 < answer
        and answer + thoughts <= MAX_OUTPUT_TOKENS
        and total == prompt + answer + thoughts
    ):
        return None
    if type(candidates) is not list or len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not _shape(candidate, {"content", "finishReason", "index"}):
        return None
    if (
        type(candidate["index"]) is not int
        or candidate["index"] != 0
        or candidate["finishReason"] != "STOP"
        or not _shape(candidate["content"], {"role", "parts"})
    ):
        return None
    content = candidate["content"]
    parts = content["parts"]
    if (
        content["role"] != "model"
        or type(parts) is not list
        or len(parts) != 1
        or not _shape(parts[0], {"text"})
        or type(parts[0]["text"]) is not str
        or not 0 < len(parts[0]["text"]) <= 1024
    ):
        return None
    # Validate text shape but never return, log or interpret it as semantics.
    return {
        "model": MODEL,
        "input_tokens": prompt,
        "output_tokens": answer + thoughts,
        "total_tokens": total,
    }


def _result(state: str, observation: dict | None = None) -> dict:
    result = {"status": state, "evidence_kind": "fabricated-offline"}
    if observation is not None:
        result.update(observation)
    return result


class OfflineDiagnostic:
    """One in-memory fabricated attempt, not a durable production burn fence."""

    def __init__(self) -> None:
        """Start a fresh synthetic test object, never a live allowance."""
        self._lock = threading.Lock()
        self._consumed = False

    def run(
        self,
        enrollment: object,
        snapshot: object,
        grant: object,
        transport: FabricatedTransport,
        clock: Callable[[], int],
    ) -> dict:
        """Attempt once through a fabricated transport; ambiguity is terminal.

        A caller-supplied grant or metadata is never externally verified here.
        No exception text or arbitrary transport result escapes this boundary.
        """
        with self._lock:
            if self._consumed:
                return _result("NOT_RUN")
            self._consumed = True
        try:
            started = clock()
            if (
                not fabricated_fence_consistent(enrollment, snapshot, started)
                or not _grant_consistent(grant, enrollment, started)
                or transport.evidence_kind != "fabricated-offline"
            ):
                return _result("NOT_RUN")
            original = json.dumps([enrollment, snapshot, grant], sort_keys=True)
            status, body = transport.exchange(
                ENDPOINT, REQUEST, TIMEOUT_SECONDS
            )
            ended = clock()
            if (
                not _integer(ended)
                or not started <= ended
                or ended - started >= TIMEOUT_SECONDS
                or not _window(enrollment, ended)
                or not _window(grant, ended)
                or json.dumps([enrollment, snapshot, grant], sort_keys=True)
                != original
            ):
                return _result("UNKNOWN")
            observation = _safe_observation(status, body)
            if observation is None:
                return _result("UNKNOWN")
            return _result("FABRICATED_ACCEPTED", observation)
        except BaseException:
            # Sanitize untrusted fixture failures; never retry after ambiguity.
            return _result("UNKNOWN")


def production_status() -> dict:
    """Return terminal NOT_RUN without reading inputs, metadata or credentials."""
    return {"status": "NOT_RUN", "reason": "PRODUCTION_ACTIVATION_UNSUPPORTED"}


if __name__ == "__main__":
    print(json.dumps(production_status(), sort_keys=True))
    raise SystemExit(2)
