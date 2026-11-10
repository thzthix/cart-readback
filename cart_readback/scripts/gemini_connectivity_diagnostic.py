"""One fixed synthetic generation POST in the reviewed hosted branch job.

This script does not verify current Free eligibility, invoices or app integration.
The trusted operator authorizes the sole manual dispatch and its compute use.
Tests use invented context, synthetic keys and fake HTTPS connections only.
"""

import decimal
import enum
import hashlib
import http.client
import json
import math
import os
import pathlib
import re
import signal
import ssl
import time

MODEL = "gemini-3.5-flash-lite"
METHOD = "POST"
REQUEST_PATH = "/v1beta/models/" + MODEL + ":generateContent"
ENDPOINT = "https://generativelanguage.googleapis.com" + REQUEST_PATH
WORKFLOW_PATH = ".github/workflows/application-checks.yml"
MAX_INPUT_RESERVATION = 1048576
MAX_OUTPUT_RESERVATION = 2048
MAX_OUTPUT_TOKENS = 256
TIMEOUT_SECONDS = 20
# Local HTTP-header safety bound, not a provider key-format specification.
MAX_CREDENTIAL_BYTES = 4096
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
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
    },
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
REQUEST_BODY_SHA256 = hashlib.sha256(REQUEST).hexdigest()
REQUEST_SHA256 = hashlib.sha256(
    (METHOD + " " + REQUEST_PATH + "\n" + REQUEST_BODY_SHA256).encode("ascii")
).hexdigest()


class _Reason(enum.Enum):
    CREDENTIAL_LOOKUP_FAILED = "CREDENTIAL_LOOKUP_FAILED"
    CREDENTIAL_REJECTED = "CREDENTIAL_REJECTED"
    CONTEXT_REJECTED = "CONTEXT_REJECTED"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    CLAIM_STAT_FAILED = "CLAIM_STAT_FAILED"
    CLAIM_CHANGED = "CLAIM_CHANGED"
    SOCKET_TIMEOUT_SETUP_FAILED = "SOCKET_TIMEOUT_SETUP_FAILED"
    INTERRUPTED = "INTERRUPTED"
    UNEXPECTED_LOCAL_ERROR = "UNEXPECTED_LOCAL_ERROR"


class _LocalFailure(ValueError):
    def __init__(self, reason: _Reason):
        self.reason = reason


def _shape(value: object, keys: set[str]) -> bool:
    return type(value) is dict and value.keys() == keys


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _digest(value: object, length: int = 64) -> bool:
    return (
        type(value) is str
        and re.fullmatch("[0-9a-f]{" + str(length) + "}", value) is not None
    )


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite")


class _ResponseReason(enum.Enum):
    JSON_INVALID = "JSON_INVALID"
    RESPONSE_SHAPE = "RESPONSE_SHAPE"
    MODEL_VERSION_UNSUPPORTED = "MODEL_VERSION_UNSUPPORTED"
    USAGE_MISSING = "USAGE_MISSING"
    USAGE_INVALID = "USAGE_INVALID"
    USAGE_INCONSISTENT = "USAGE_INCONSISTENT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    NO_GENERATED_TOKENS = "NO_GENERATED_TOKENS"
    CANDIDATE_SHAPE = "CANDIDATE_SHAPE"
    FINISH_REASON_UNSUPPORTED = "FINISH_REASON_UNSUPPORTED"
    CONTENT_SHAPE = "CONTENT_SHAPE"
    UNREQUESTED_PART = "UNREQUESTED_PART"
    TEXT_MISSING = "TEXT_MISSING"


# Fixed public protobuf FinishReason values; unknown values are never echoed.
_FINISH_REASONS = {
    0: "FINISH_REASON_UNSPECIFIED",
    1: "STOP",
    2: "MAX_TOKENS",
    3: "SAFETY",
    4: "RECITATION",
    5: "OTHER",
    6: "LANGUAGE",
    7: "BLOCKLIST",
    8: "PROHIBITED_CONTENT",
    9: "SPII",
    10: "MALFORMED_FUNCTION_CALL",
    11: "IMAGE_SAFETY",
    12: "UNEXPECTED_TOOL_CALL",
    13: "TOO_MANY_TOOL_CALLS",
    14: "IMAGE_PROHIBITED_CONTENT",
    15: "IMAGE_OTHER",
    16: "NO_IMAGE",
    17: "IMAGE_RECITATION",
}
_MAX_OBSERVED_OUTPUT = 65536


def _count(value, maximum):
    """Read bounded ProtoJSON integer forms; an unset scalar defaults to zero."""
    if value is None:
        return 0
    if type(value) is int:
        return value if 0 <= value <= maximum else None
    if type(value) not in (str, float, decimal.Decimal):
        return None
    if type(value) is str and (
        len(value) > 64
        or re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value
        )
        is None
    ):
        return None
    try:
        number = decimal.Decimal(str(value))
        if (
            not number.is_finite()
            or not 0 <= number <= maximum
            or number != number.to_integral_value()
        ):
            return None
        return int(number)
    except decimal.InvalidOperation:
        return None


def _model_version(value):
    if type(value) is str and re.fullmatch(
        re.escape(MODEL) + r"(?:-[0-9]{1,8}(?:[.-][0-9]{1,8}){0,3})?", value
    ):
        return value
    return None


def _finish_reason(value):
    if value is None:
        return _FINISH_REASONS[0]
    if type(value) is int:
        return _FINISH_REASONS.get(value)
    if type(value) is str and value in _FINISH_REASONS.values():
        return value
    return None


def _has_text(content):
    if content is None:
        return False
    if type(content) is not dict:
        return None
    parts = content.get("parts")
    if parts is None:
        return False
    if type(parts) is not list or len(parts) > 32:
        return None
    uncertain = False
    for part in parts:
        if type(part) is not dict:
            uncertain = True
            continue
        text, thought = part.get("text"), part.get("thought")
        if type(text) is str and text and (thought is None or thought is False):
            return True
        if (text is not None and type(text) is not str) or (
            thought is not None and type(thought) is not bool
        ):
            uncertain = True
    return None if uncertain else False


def _details_match(value, count, maximum):
    if value is None or value == []:
        return True
    if type(value) is not list or len(value) > 16:
        return False
    total = 0
    for item in value:
        if type(item) is not dict or item.get("modality") != "TEXT":
            return False
        amount = _count(item.get("tokenCount"), maximum)
        if amount is None:
            return False
        total += amount
    return total == count


def _inspect_response(status, body):
    """Separate bounded reported facts from the stricter generation admission."""
    facts = {}

    def reject(reason):
        return None, reason, facts

    if type(status) is not int or status != 200:
        return reject(_ResponseReason.RESPONSE_SHAPE)
    if type(body) is not bytes or not 0 < len(body) <= 16384:
        return reject(_ResponseReason.JSON_INVALID)
    try:
        data = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
            parse_float=decimal.Decimal,
        )
    except (ValueError, UnicodeError, RecursionError, decimal.InvalidOperation):
        return reject(_ResponseReason.JSON_INVALID)
    if type(data) is not dict:
        return reject(_ResponseReason.RESPONSE_SHAPE)

    version = _model_version(data.get("modelVersion"))
    if version is not None:
        facts["model_version"] = version
    else:
        facts["model_category"] = "UNSUPPORTED"
    usage = data.get("usageMetadata")
    counts = {}
    fields = (
        ("promptTokenCount", "input_tokens", MAX_INPUT_RESERVATION),
        ("candidatesTokenCount", "answer_tokens", _MAX_OBSERVED_OUTPUT),
        ("thoughtsTokenCount", "thought_tokens", _MAX_OBSERVED_OUTPUT),
        (
            "totalTokenCount",
            "total_tokens",
            MAX_INPUT_RESERVATION + _MAX_OBSERVED_OUTPUT,
        ),
    )
    if type(usage) is dict:
        counts = {
            name: _count(usage.get(field), limit)
            for field, name, limit in fields
        }
        facts["usage"] = {
            name: value for name, value in counts.items() if value is not None
        }
    candidates = data.get("candidates")
    candidate = (
        candidates[0]
        if type(candidates) is list
        and len(candidates) == 1
        and type(candidates[0]) is dict
        else None
    )
    finish = None
    has_text = None
    if candidate is not None:
        finish = _finish_reason(candidate.get("finishReason"))
        if finish is not None:
            facts["finish_reason"] = finish
        else:
            facts["finish_category"] = "UNSUPPORTED"
        has_text = _has_text(candidate.get("content"))
        if type(has_text) is bool:
            facts["has_text"] = has_text
    elif candidates is None or candidates == []:
        facts["has_text"] = False
        facts["finish_category"] = "NO_CANDIDATE"

    if version is None:
        return reject(_ResponseReason.MODEL_VERSION_UNSUPPORTED)
    if type(usage) is not dict:
        return reject(_ResponseReason.USAGE_MISSING)
    if any(value is None for value in counts.values()):
        return reject(_ResponseReason.USAGE_INVALID)
    prompt, answer, thoughts, total = (
        counts[name]
        for name in (
            "input_tokens",
            "answer_tokens",
            "thought_tokens",
            "total_tokens",
        )
    )
    cached = _count(usage.get("cachedContentTokenCount"), MAX_INPUT_RESERVATION)
    tools = _count(usage.get("toolUsePromptTokenCount"), MAX_INPUT_RESERVATION)
    if (
        prompt <= 0
        or total != prompt + answer + thoughts
        or cached is None
        or cached > prompt
        or tools != 0
        or not _details_match(
            usage.get("promptTokensDetails"), prompt, MAX_INPUT_RESERVATION
        )
        or not _details_match(
            usage.get("candidatesTokensDetails"), answer, _MAX_OBSERVED_OUTPUT
        )
    ):
        return reject(_ResponseReason.USAGE_INCONSISTENT)
    if answer + thoughts > MAX_OUTPUT_TOKENS:
        return reject(_ResponseReason.OUTPUT_LIMIT_EXCEEDED)
    if answer + thoughts == 0:
        return reject(_ResponseReason.NO_GENERATED_TOKENS)
    if candidate is None or _count(candidate.get("index"), 0) != 0:
        return reject(_ResponseReason.CANDIDATE_SHAPE)
    if finish not in {"STOP", "MAX_TOKENS"}:
        return reject(_ResponseReason.FINISH_REASON_UNSUPPORTED)
    content = candidate.get("content")
    if content is None:
        content = {}
    if type(content) is not dict or content.get("role") not in (
        None,
        "",
        "model",
    ):
        return reject(_ResponseReason.CONTENT_SHAPE)
    parts = content.get("parts")
    if parts is None:
        parts = []
    if type(parts) is not list or len(parts) > 32:
        return reject(_ResponseReason.CONTENT_SHAPE)
    for part in parts:
        if type(part) is not dict:
            return reject(_ResponseReason.CONTENT_SHAPE)
        if not part.keys() <= {"text", "thought", "thoughtSignature"}:
            return reject(_ResponseReason.UNREQUESTED_PART)
        if (
            part.get("text") is not None
            and type(part["text"]) is not str
            or part.get("thought") is not None
            and type(part["thought"]) is not bool
            or part.get("thoughtSignature") is not None
            and type(part["thoughtSignature"]) is not str
        ):
            return reject(_ResponseReason.CONTENT_SHAPE)
    if finish == "STOP" and (answer <= 0 or has_text is not True):
        return reject(_ResponseReason.TEXT_MISSING)
    observation = {
        "model": version,
        "input_tokens": prompt,
        "output_tokens": answer + thoughts,
        "total_tokens": total,
        "answer_tokens": answer,
        "thought_tokens": thoughts,
        "finish_reason": finish,
        "has_text": has_text is True,
    }
    return observation, None, facts


def _safe_observation(status, body):
    return _inspect_response(status, body)[0]


REPOSITORY = "thzthix/cart-readback"
REF = "refs/heads/feat/64-disabled-connectivity-diagnostic"
EXPECTED_CONTEXT = {
    "GITHUB_REPOSITORY": REPOSITORY,
    "GITHUB_REPOSITORY_ID": "1443556432",
    "GITHUB_REPOSITORY_OWNER_ID": "95135403",
    "GITHUB_ACTOR_ID": "95135403",
    "GITHUB_TRIGGERING_ACTOR": "thzthix",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": REF,
    "GITHUB_WORKFLOW_REF": REPOSITORY + "/" + WORKFLOW_PATH + "@" + REF,
    "GITHUB_RUN_NUMBER": "5",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_API_URL": "https://api.github.com",
    "PROBE_MODE": "gemini-connectivity",
}


def validate_context(env: dict, now: float) -> float:
    """Validate trusted hosted context, not external approval or account facts."""
    if not math.isfinite(now) or any(
        env.get(k) != v for k, v in EXPECTED_CONTEXT.items()
    ):
        raise ValueError()
    sha = env.get("PROBE_REVIEWED_SHA", "")
    if (
        not _digest(sha, 40)
        or env.get("GITHUB_SHA") != sha
        or env.get("GITHUB_WORKFLOW_SHA") != sha
    ):
        raise ValueError()
    if re.fullmatch(r"[1-9][0-9]{0,19}", env.get("GITHUB_RUN_ID", "")) is None:
        raise ValueError()
    windows = [
        env.get(k, "") for k in ("PROBE_WINDOW_START", "PROBE_WINDOW_END")
    ]
    if any(re.fullmatch(r"[0-9]{10}", v) is None for v in windows):
        raise ValueError()
    start, end = map(int, windows)
    if not 0 < end - start <= 600 or not start <= now < end:
        raise ValueError()
    return end - now


def _headers(response) -> int | None:
    values, size = {}, 0
    raw = response.getheaders()
    if type(raw) is not list or len(raw) > 64:
        raise ValueError()
    for pair in raw:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError()
        name, value = pair
        if type(name) is not str or type(value) is not str:
            raise ValueError()
        if re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", name) is None:
            raise ValueError()
        if len(value) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError()
        size += len(name) + len(value)
        if size > 16384:
            raise ValueError()
        name = name.lower()
        if name in {
            "content-type",
            "content-length",
            "transfer-encoding",
            "content-encoding",
        }:
            if name in values:
                raise ValueError()
            if name == "transfer-encoding" and value != value.strip():
                raise ValueError()
            values[name] = value.strip().lower()
    if (
        re.fullmatch(
            r'application/json(?:;\s*charset=(?:utf-8|"utf-8"))?',
            values.get("content-type", ""),
        )
        is None
    ):
        raise ValueError()
    if values.get("content-encoding", "identity") != "identity":
        raise ValueError()
    transfer, length = (
        values.get("transfer-encoding"),
        values.get("content-length"),
    )
    if isinstance(response, http.client.HTTPResponse) and response.chunked != (
        transfer is not None
    ):
        raise ValueError()
    if transfer is not None and (transfer != "chunked" or length is not None):
        raise ValueError()
    if transfer is None and length is None:
        raise ValueError()
    if length is None:
        return None
    if (
        re.fullmatch(r"0|[1-9][0-9]{0,5}", length) is None
        or not 0 < int(length) <= 16384
    ):
        raise ValueError()
    return int(length)


def _failure_receipt(
    status, phase, http_status=None, *, cleanup_failed=False, reason=None
):
    """Keep only fixed local phase and an already received integer status."""
    result = {"status": status, "phase": phase}
    if http_status is not None:
        result["http_status"] = http_status
    if cleanup_failed:
        result["cleanup_failed"] = True
    if type(reason) is _Reason:
        result["reason"] = reason.value
    return result


def execute(
    env: dict,
    *,
    connection_factory=None,
    wall=time.time,
    monotonic=time.monotonic,
) -> dict:
    """Burn one local attempt before reading the sole key; never retry.

    Callers in tests supply fake context and sockets. The CLI uses only the fixed
    native HTTPS constructor. A missing completion is UNKNOWN, not success.
    """
    claim = connection = response = None
    claimed = False
    token = None
    headers = {}
    phase, http_status = "preflight", None
    reason = None
    response_reason = None
    observed_facts = {}
    result = {"status": "NOT_RUN"}
    try:
        remaining = validate_context(env, wall())
        expected_source = env.get("PROBE_SOURCE_SHA256", "")
        if (
            not _digest(expected_source)
            or hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
            != expected_source
        ):
            raise ValueError()
        directory = pathlib.Path(env.get("RUNNER_TEMP", ""))
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError()
        path = directory / (
            "cartreadback-gemini-" + env["GITHUB_RUN_ID"] + ".claim"
        )
        phase = "claim"
        claim = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        claimed = True
        identity = os.fstat(claim)
        expires = monotonic() + min(TIMEOUT_SECONDS, remaining)

        def guard():
            try:
                context_remaining = validate_context(env, wall())
            except ValueError:
                raise _LocalFailure(_Reason.CONTEXT_REJECTED) from None
            remaining = min(context_remaining, expires - monotonic())
            try:
                current = path.stat(follow_symlinks=False)
            except OSError:
                raise _LocalFailure(_Reason.CLAIM_STAT_FAILED) from None
            if remaining <= 0:
                raise _LocalFailure(_Reason.DEADLINE_EXPIRED)
            if (current.st_dev, current.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ):
                raise _LocalFailure(_Reason.CLAIM_CHANGED)
            return remaining

        guard()
        phase = "connect"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_default_certs(ssl.Purpose.SERVER_AUTH)
        context.keylog_filename = None
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_alpn_protocols(["http/1.1"])
        factory = (
            http.client.HTTPSConnection
            if connection_factory is None
            else connection_factory
        )
        connection = factory(
            "generativelanguage.googleapis.com",
            443,
            timeout=min(3, guard()),
            context=context,
        )
        connection.set_debuglevel(0)
        connection.auto_open = 0
        guard()
        connection.connect()
        established_socket = connection.sock
        established_socket.settimeout(min(12, guard()))
        # The irreversible local claim and all context gates precede key access.
        phase = "credential"
        try:
            token = env.pop("GEMINI_KEY", None)
        except Exception:
            raise _LocalFailure(_Reason.CREDENTIAL_LOOKUP_FAILED) from None
        if (
            type(token) is not str
            or not 1 <= len(token) <= MAX_CREDENTIAL_BYTES
            or any(not 33 <= ord(char) <= 126 for char in token)
        ):
            raise _LocalFailure(_Reason.CREDENTIAL_REJECTED)
        headers = {
            "Host": "generativelanguage.googleapis.com",
            "x-goog-api-key": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Length": str(len(REQUEST)),
            "Connection": "close",
        }
        timeout = min(12, guard())
        try:
            established_socket.settimeout(timeout)
        except OSError:
            raise _LocalFailure(_Reason.SOCKET_TIMEOUT_SETUP_FAILED) from None
        # This is a local call boundary, not proof of network delivery.
        phase = "request-attempt"
        try:
            connection.request(
                METHOD,
                REQUEST_PATH,
                body=REQUEST,
                headers=headers,
                encode_chunked=False,
            )
        finally:
            token = None
            headers.clear()
        phase = "headers"
        established_socket.settimeout(min(12, guard()))
        response = connection.getresponse()
        received_status = response.status
        if type(received_status) is int and 100 <= received_status <= 599:
            http_status = received_status
        guard()
        if (
            type(response.status) is not int
            or response.status != 200
            or response.version != 11
        ):
            raise ValueError()
        expected = _headers(response)
        phase = "body"
        raw = bytearray()
        while True:
            if (
                isinstance(response, http.client.HTTPResponse)
                and response.isclosed()
            ):
                break
            established_socket.settimeout(min(12, guard()))
            chunk = response.read1(min(8192, 16385 - len(raw)))
            guard()
            if type(chunk) is not bytes or len(raw) + len(chunk) > 16384:
                raise ValueError()
            if not chunk:
                break
            raw.extend(chunk)
        if expected is not None and len(raw) != expected:
            raise ValueError()
        observation, response_reason, observed_facts = _inspect_response(
            200, bytes(raw)
        )
        guard()
        if observation is None:
            result = _failure_receipt(
                "HTTP_200_UNVALIDATED", phase, http_status
            )
        else:
            result = {
                "status": (
                    "GENERATION_PARTIAL_VALIDATED"
                    if observation["finish_reason"] == "MAX_TOKENS"
                    else "RESPONSE_VALIDATED"
                ),
                **observation,
            }
    except BaseException as error:
        if phase == "credential":
            reason = _Reason.UNEXPECTED_LOCAL_ERROR
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                reason = _Reason.INTERRUPTED
            elif (
                isinstance(error, _LocalFailure)
                and type(error.reason) is _Reason
            ):
                reason = error.reason
        result = _failure_receipt(
            "UNKNOWN" if claimed else "NOT_RUN",
            phase,
            http_status,
            reason=reason,
        )
    finally:
        token = None
        headers.clear()
        for resource in (response, connection):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    result = _failure_receipt(
                        "UNKNOWN",
                        phase,
                        http_status,
                        cleanup_failed=True,
                        reason=reason,
                    )
        if claim is not None:
            try:
                os.close(claim)
            except BaseException:
                result = _failure_receipt(
                    "UNKNOWN",
                    phase,
                    http_status,
                    cleanup_failed=True,
                    reason=reason,
                )
    if type(response_reason) is _ResponseReason:
        result["response_reason"] = response_reason.value
    if observed_facts and result["status"] in {
        "UNKNOWN",
        "HTTP_200_UNVALIDATED",
    }:
        result["observed"] = observed_facts
    return result


def main() -> int:
    """Emit only the sanitized final receipt, after synchronous cleanup."""
    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(_number, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupted)
    try:
        result = execute(os.environ)
    except BaseException:
        result = _failure_receipt("UNKNOWN", "unavailable")
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "RESPONSE_VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
