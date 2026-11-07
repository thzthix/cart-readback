"""One-shot fixed-origin Gemini HTTPS, unselected without a host integration.

Callbacks are trusted host code, not an approval system or credential resolver.
A future host must durably reserve authorized call/token/spend capacity before
constructing this transport. Each I/O guard must recheck its committed claim,
request hash, approved data, credential binding and wall-clock authorization.
"""

import http.client
import re
import ssl
import threading

from cartreadback_app.gemini_client import (
    ENDPOINT,
    HOST,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PATH,
    unavailable,
)
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.responses_http import _check_deadline, _StrictHTTPResponse
from cartreadback_app.validation import AppError

_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_KEY = re.compile(r"[A-Za-z0-9_-]{1,256}")


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
    if type(response) is _StrictHTTPResponse and response.chunked != (
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
            or endpoint != ENDPOINT
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

        def check():
            deadline.remaining()
            # No secret or network effect may occur before the host rechecks.
            self._guard(endpoint=endpoint, body=body, deadline=deadline)
            deadline.remaining()

        def read_timeout():
            check()
            if established_socket is None:
                raise unavailable()
            established_socket.settimeout(deadline.read_timeout())

        try:
            check()
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            connection = self._factory(
                HOST, 443, timeout=deadline.connect_timeout(), context=context
            )
            connection.set_debuglevel(0)
            connection.response_class = _StrictHTTPResponse
            connection.auto_open = 0
            check()
            connection.connect()
            established_socket = connection.sock
            read_timeout()
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
                connection.request(
                    "POST",
                    PATH,
                    body=body,
                    headers=headers,
                    encode_chunked=False,
                )
            finally:
                token = None
                headers.clear()
            read_timeout()
            response = connection.getresponse()
            check()
            if (
                isinstance(response, http.client.HTTPResponse)
                and type(response) is not _StrictHTTPResponse
            ):
                raise unavailable()
            if (
                type(response.status) is not int
                or response.status != 200
                or type(response.version) is not int
                or response.version != 11
            ):
                raise unavailable()
            expected = _expected_length(response)
            raw = bytearray()
            while True:
                check()
                if (
                    type(response) is _StrictHTTPResponse
                    and response.isclosed()
                ):
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
            raise unavailable(
                "MODEL_TIMEOUT" if timeout else "MODEL_UNAVAILABLE"
            ) from None
        finally:
            # Keep connection lifetime synchronous, including cleanup after a
            # deadline. Closing cannot prove that remote billing was cancelled.
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass
