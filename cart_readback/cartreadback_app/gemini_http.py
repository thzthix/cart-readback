"""One-shot fixed-origin Gemini HTTPS, unselected without a host integration.

Callbacks are trusted host code, not an approval system or credential resolver.
A future host must durably reserve authorized call/token/spend capacity before
constructing this transport. Each I/O guard must recheck its committed claim,
request hash, approved data, credential binding and wall-clock authorization.
"""

import http.client
import re
import ssl
import sys
import threading

from cartreadback_app.gemini_client import (
    ENDPOINT_PATHS,
    HOST,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    unavailable,
)
from cartreadback_app.inference import PROPOSAL_RULES
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.responses_http import _check_deadline, _StrictHTTPResponse
from cartreadback_app.validation import AppError

_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
# Opaque header value; 4096 is our defensive bound, not a Google format.
_KEY = re.compile(r"[!-~]{1,4096}")


_DIAGNOSTIC_STAGES = frozenset(
    {
        "preconnect",
        "guard",
        "connect",
        "credential",
        "request",
        "status",
        "body",
        "cleanup",
        "exchange",
        "exchange-validation",
    }
)
_DIAGNOSTIC_CATEGORIES = (
    frozenset(
        {
            "MODEL_TIMEOUT",
            "MODEL_UNAVAILABLE",
            "GEMINI_CAPACITY_BLOCKED",
            "GEMINI_RUN_BLOCKED",
            "UNEXPECTED_FAILURE",
            "MODEL_OUTCOME_UNKNOWN",
            "MODEL_REFUSED",
            "MODEL_INCOMPLETE",
            "INVALID_PROPOSAL",
            "STALE_SNAPSHOT",
        }
    )
    | PROPOSAL_RULES
)


def safe_gemini_diagnostic(value):
    """Rebuild fixed literals only; diagnostics never change accounting."""
    if type(value) is not dict or set(value) != {
        "stage",
        "category",
        "http_status",
    }:
        return None
    stage, category, status = (
        value["stage"],
        value["category"],
        value["http_status"],
    )
    if (
        type(stage) is not str
        or stage not in _DIAGNOSTIC_STAGES
        or type(category) is not str
        or category not in _DIAGNOSTIC_CATEGORIES
        or not (status is None or type(status) is int and 100 <= status <= 599)
    ):
        return None
    return {
        "stage": next(item for item in _DIAGNOSTIC_STAGES if item == stage),
        "category": next(
            item for item in _DIAGNOSTIC_CATEGORIES if item == category
        ),
        "http_status": status,
    }


class GeminiTransportFailure(AppError):
    """Fixed safe diagnostic, never provider text or proof of delivery."""

    def __init__(self, stage, category, status=None):
        """Retain only bounded known observation fields."""
        super().__init__(
            "MODEL_TIMEOUT"
            if category == "MODEL_TIMEOUT"
            else "MODEL_UNAVAILABLE",
            "Gemini transport unavailable.",
            503,
        )
        self.diagnostic = safe_gemini_diagnostic(
            {"stage": stage, "category": category, "http_status": status}
        )


def gemini_failure_diagnostic(error):
    """Project a transport failure or a generic pre-transport exchange failure."""
    if type(error) is GeminiTransportFailure:
        result = safe_gemini_diagnostic(error.diagnostic)
        if result is not None:
            return result
    code = error.code if type(error) is AppError else None
    return {
        "stage": "exchange",
        "category": code
        if type(code) is str and code in _DIAGNOSTIC_CATEGORIES
        else "UNEXPECTED_FAILURE",
        "http_status": None,
    }


def _expected_length(response):
    """Validate bounded JSON framing without assuming an OpenAI request header."""
    raw = response.getheaders()
    if type(raw) is not list or len(raw) > 64:
        raise unavailable()
    relevant = {}
    size = 0
    for pair in raw:
        if type(pair) is not tuple or len(pair) != 2:
            raise unavailable()
        name, value = pair
        if (
            type(name) is not str
            or type(value) is not str
            or not 1 <= len(name) <= 256
            or len(value) > 4096
            or _HEADER_NAME.fullmatch(name) is None
            or any(ord(char) < 32 or ord(char) > 126 for char in value)
        ):
            raise unavailable()
        size += len(name) + len(value)
        if size > 16_384:
            raise unavailable()
        lower = name.lower()
        if lower in {
            "content-type",
            "content-length",
            "transfer-encoding",
            "content-encoding",
        }:
            if lower in relevant:
                raise unavailable()
            if lower == "transfer-encoding" and value != value.strip():
                raise unavailable()
            relevant[lower] = value.strip()
    if (
        re.fullmatch(
            r'application/json(?:;\s*charset=(?:utf-8|"utf-8"))?',
            relevant.get("content-type", "").lower(),
        )
        is None
    ):
        raise unavailable()
    if relevant.get("content-encoding", "identity").lower() != "identity":
        raise unavailable()
    transfer = relevant.get("transfer-encoding")
    length = relevant.get("content-length")
    if transfer is not None and (
        transfer.lower() != "chunked" or length is not None
    ):
        raise unavailable()
    if isinstance(response, _StrictHTTPResponse) and response.chunked != (
        transfer is not None
    ):
        raise unavailable()
    if length is None:
        return None
    if (
        re.fullmatch(r"0|[1-9][0-9]{0,5}", length) is None
        or int(length) > MAX_RESPONSE_BYTES
    ):
        raise unavailable()
    return int(length)


class _DeadlineReader:
    """Refresh the host guard and remaining timeout before every bounded recv."""

    def __init__(self, reader, before_read, status_observer=None):
        self._reader = reader
        self._before_read = before_read
        self._pending = bytearray()
        self._status_observer = status_observer

    def __getattr__(self, name):
        return getattr(self._reader, name)

    def read1(self, amount):
        self._before_read()
        if self._pending:
            chunk = bytes(self._pending[:amount])
            del self._pending[:amount]
            return chunk
        return self._reader.read1(amount)

    def read(self, amount):
        raw = bytearray()
        while len(raw) < amount:
            chunk = self.read1(min(amount - len(raw), 8192))
            if not chunk:
                break
            raw.extend(chunk)
        return bytes(raw)

    def readline(self, limit=-1):
        # Shared strict HTTP parsing always supplies a bounded line size.
        if type(limit) is not int or not 0 < limit <= 4356:
            raise unavailable()
        raw = bytearray()
        while len(raw) < limit:
            chunk = self.read1(limit - len(raw))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                raw.extend(chunk[: newline + 1])
                self._pending[:0] = chunk[newline + 1 :]
                break
            raw.extend(chunk)
        value = bytes(raw)
        if self._status_observer is not None:
            observe, self._status_observer = self._status_observer, None
            match = re.fullmatch(
                rb"HTTP/1\.1 ([1-5][0-9]{2}) [\x20-\x7e]{0,1024}\r\n", value
            )
            if match is not None:
                observe(int(match[1]))
        return value


def unselected_gemini_connection(host, port, *, timeout, context):
    """Construct standard TLS mechanics only when explicitly chosen by a host."""
    return http.client.HTTPSConnection(
        host, port, timeout=timeout, context=context
    )


class GeminiHTTPTransport:
    """A single synchronous attempt with injected credential and admission guard.

    There is no ambient proxy discovery, environment lookup, reconnect, redirect,
    retry, credential cache or hidden thread. Failure or successful consumption
    exhausts this object. Creating another object is not fresh host authority.
    """

    def __init__(self, connection_factory, borrow_credential, claim_guard):
        """Retain explicit host seams, without network or credential activity."""
        if not all(
            callable(item)
            for item in (connection_factory, borrow_credential, claim_guard)
        ):
            raise unavailable()
        self._factory = connection_factory
        self._borrow = borrow_credential
        self._guard = claim_guard
        self._lock = threading.Lock()
        self._used = False

    def send(self, endpoint: str, body: bytes, *, deadline: Deadline) -> bytes:
        """Consume one bounded verified-TLS response without releasing I/O early."""
        if (
            type(endpoint) is not str
            or endpoint not in ENDPOINT_PATHS
            or type(body) is not bytes
            or not 0 < len(body) <= MAX_REQUEST_BYTES
        ):
            raise unavailable()
        deadline = _check_deadline(deadline)
        with self._lock:
            if self._used:
                raise unavailable()
            self._used = True
        connection = response = established_socket = None
        stage, http_status = "preconnect", None

        def check():
            nonlocal stage
            prior, stage = stage, "guard"
            deadline.remaining()
            # No secret or network effect may occur before the host rechecks.
            if (
                self._guard(endpoint=endpoint, body=body, deadline=deadline)
                is not None
            ):
                raise unavailable()
            deadline.remaining()
            stage = prior

        def read_timeout():
            check()
            if established_socket is None:
                raise unavailable()
            established_socket.settimeout(deadline.read_timeout())

        def observe_status(value):
            nonlocal http_status
            http_status = value

        try:
            check()
            # create_default_context honors SSLKEYLOGFILE. Do not let an ambient
            # variable enable session-secret logging or even create that file.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_default_certs(ssl.Purpose.SERVER_AUTH)
            context.keylog_filename = None
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            connection = self._factory(
                HOST, 443, timeout=deadline.connect_timeout(), context=context
            )
            connection.set_debuglevel(0)

            class GuardedResponse(_StrictHTTPResponse):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.fp._reader = _DeadlineReader(
                        self.fp._reader, read_timeout, observe_status
                    )

            connection.response_class = GuardedResponse
            connection.auto_open = 0
            check()
            stage = "connect"
            connection.connect()
            established_socket = connection.sock
            read_timeout()
            stage = "credential"
            token = self._borrow(deadline=deadline)
            headers = {}
            try:
                if type(token) is not str or _KEY.fullmatch(token) is None:
                    raise unavailable()
                headers = {
                    "Host": HOST,
                    "x-goog-api-key": token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Content-Length": str(len(body)),
                    "Connection": "close",
                }
                read_timeout()
                stage = "request"
                connection.request(
                    "POST",
                    ENDPOINT_PATHS[endpoint],
                    body=body,
                    headers=headers,
                    encode_chunked=False,
                )
            finally:
                token = None
                headers.clear()
            read_timeout()
            stage = "status"
            response = connection.getresponse()
            check()
            if (
                isinstance(response, http.client.HTTPResponse)
                and type(response) is not GuardedResponse
            ):
                raise unavailable()
            if (
                type(response.status) is not int
                or response.status != 200
                or type(response.version) is not int
                or response.version != 11
            ):
                raise unavailable()
            stage = "body"
            expected = _expected_length(response)
            raw = bytearray()
            while True:
                check()
                if type(response) is GuardedResponse and response.isclosed():
                    break
                read_timeout()
                amount = min(8192, MAX_RESPONSE_BYTES - len(raw) + 1)
                chunk = response.read1(amount)
                check()
                if type(chunk) is not bytes or len(chunk) > amount:
                    raise unavailable()
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES or (
                    expected is not None and len(raw) > expected
                ):
                    raise unavailable()
            if expected is not None and len(raw) != expected:
                raise unavailable()
            check()
            return bytes(raw)
        except Exception as error:
            timeout = (
                isinstance(error, TimeoutError)
                or isinstance(error, AppError)
                and error.code == "MODEL_TIMEOUT"
            )
            category = (
                "MODEL_TIMEOUT"
                if timeout
                else (
                    error.code
                    if type(error) is AppError
                    and error.code in _DIAGNOSTIC_CATEGORIES
                    else "UNEXPECTED_FAILURE"
                )
            )
            raise GeminiTransportFailure(stage, category, http_status) from None
        finally:
            # Keep connection lifetime synchronous, including cleanup after a
            # deadline. Closing cannot prove that remote billing was cancelled.
            primary = sys.exc_info()[1]
            interruption = None
            cleanup_fault = False
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except BaseException as error:
                        cleanup_fault = True
                        if (
                            not isinstance(error, Exception)
                            and interruption is None
                        ):
                            interruption = error
            if primary is None and interruption is not None:
                raise interruption
            if primary is None and cleanup_fault:
                raise GeminiTransportFailure(
                    "cleanup", "MODEL_UNAVAILABLE", http_status
                ) from None
