"""One fixed Google model-metadata GET in the reviewed hosted branch job.

This script checks model metadata, not inference, Free eligibility or billing.
The trusted operator authorizes the sole manual dispatch and its compute use.
Tests use invented context, synthetic keys and fake HTTPS connections only.
"""

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
METHOD = "GET"
REQUEST_PATH = "/v1beta/models/" + MODEL
ENDPOINT = "https://generativelanguage.googleapis.com" + REQUEST_PATH
WORKFLOW_PATH = ".github/workflows/application-checks.yml"
TIMEOUT_SECONDS = 20
# Local HTTP-header safety bound, not a provider key-format specification.
MAX_CREDENTIAL_BYTES = 4096
REQUEST = b""
REQUEST_BODY_SHA256 = hashlib.sha256(REQUEST).hexdigest()
# Canonical fixed method/path/body digest; the source pin binds these constants.
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
    if type(data) is not dict or data.get("name") != "models/" + MODEL:
        return None
    # Other bounded metadata stays private and grants no generation-access claim.
    return {"model": MODEL}


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
    "GITHUB_RUN_NUMBER": "3",
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
        observation = _safe_observation(200, bytes(raw))
        guard()
        if observation is None:
            result = _failure_receipt(
                "HTTP_200_UNVALIDATED", phase, http_status
            )
        else:
            result = {"status": "MODEL_METADATA_VALIDATED", **observation}
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
    return 0 if result["status"] == "MODEL_METADATA_VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
