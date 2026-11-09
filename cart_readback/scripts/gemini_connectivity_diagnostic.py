"""One fixed Google connectivity POST, only in the reviewed hosted branch job.

This script does not verify Free eligibility, billing or user consent. The trusted
operator must establish those facts before the sole manual workflow dispatch.
Tests use invented context, synthetic keys and fake HTTPS connections only.
"""

import base64
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
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + MODEL
    + ":generateContent"
)
WORKFLOW_PATH = ".github/workflows/application-checks.yml"
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
    required_usage = {
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
    }
    allowed_usage = required_usage | {
        "thoughtsTokenCount",
        "promptTokensDetails",
        "candidatesTokensDetails",
    }
    if (
        type(usage) is not dict
        or not required_usage <= usage.keys()
        or not usage.keys() <= allowed_usage
    ):
        return None
    prompt, answer, total = (
        usage[k]
        for k in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")
    )
    thoughts = usage.get("thoughtsTokenCount", 0)
    if not all(_integer(v) for v in (prompt, answer, thoughts, total)):
        return None
    for field, count in (
        ("promptTokensDetails", prompt),
        ("candidatesTokensDetails", answer),
    ):
        if field in usage:
            details = usage[field]
            if (
                type(details) is not list
                or len(details) != 1
                or not _shape(details[0], {"modality", "tokenCount"})
            ):
                return None
            if (
                details[0]["modality"] != "TEXT"
                or not _integer(details[0]["tokenCount"])
                or details[0]["tokenCount"] != count
            ):
                return None
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
        or type(parts[0]) is not dict
        or not {"text"} <= parts[0].keys() <= {"text", "thoughtSignature"}
        or type(parts[0]["text"]) is not str
        or not 0 < len(parts[0]["text"]) <= 1024
    ):
        return None
    if "thoughtSignature" in parts[0]:
        signature = parts[0]["thoughtSignature"]
        if type(signature) is not str or not 1 <= len(signature) <= 8192:
            return None
        try:
            if not 0 < len(base64.b64decode(signature, validate=True)) <= 4096:
                return None
        except ValueError:
            return None
    # Validate text shape but never return, log or interpret it as semantics.
    return {
        "model": MODEL,
        "input_tokens": prompt,
        "output_tokens": answer + thoughts,
        "total_tokens": total,
    }


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
    "GITHUB_RUN_NUMBER": "1",
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
        claim = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        claimed = True
        identity = os.fstat(claim)
        expires = monotonic() + min(TIMEOUT_SECONDS, remaining)

        def guard():
            remaining = min(
                validate_context(env, wall()), expires - monotonic()
            )
            current = path.stat(follow_symlinks=False)
            if remaining <= 0 or (current.st_dev, current.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ):
                raise TimeoutError()
            return remaining

        guard()
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
        token = env.pop("GEMINI_KEY", None)
        if (
            type(token) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", token) is None
        ):
            raise ValueError()
        headers = {
            "Host": "generativelanguage.googleapis.com",
            "x-goog-api-key": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Length": str(len(REQUEST)),
            "Connection": "close",
        }
        established_socket.settimeout(min(12, guard()))
        try:
            connection.request(
                "POST",
                "/v1beta/models/" + MODEL + ":generateContent",
                body=REQUEST,
                headers=headers,
                encode_chunked=False,
            )
        finally:
            token = None
            headers.clear()
        established_socket.settimeout(min(12, guard()))
        response = connection.getresponse()
        guard()
        if (
            type(response.status) is not int
            or response.status != 200
            or response.version != 11
        ):
            raise ValueError()
        expected = _headers(response)
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
        observation = _safe_observation(200, bytes(raw))
        guard()
        if observation is None:
            raise ValueError()
        result = {"status": "RESPONSE_VALIDATED", **observation}
    except BaseException:
        result = {"status": "UNKNOWN" if claimed else "NOT_RUN"}
    finally:
        token = None
        headers.clear()
        for resource in (response, connection):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    result = {"status": "UNKNOWN"}
        if claim is not None:
            try:
                os.close(claim)
            except BaseException:
                result = {"status": "UNKNOWN"}
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
        result = {"status": "UNKNOWN"}
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "RESPONSE_VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
