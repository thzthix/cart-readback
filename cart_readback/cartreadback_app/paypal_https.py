"""Disabled-by-default sandbox HTTPS/OAuth groundwork; tested with fake I/O.

No credential loader, provider runner or live-enable setting is shipped. A caller
must inject both a credential source and a connection factory. The network-marked
core cannot be injected directly into the existing offline payment adapter. Real
use needs a separate authorized capability and TLS/proxy/provider acceptance pass.
"""

import base64
import http.client
import os
import queue
import re
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.request import getproxies
from uuid import UUID

from cartreadback_app.payments import PaymentRequest, ProviderAmbiguity
from cartreadback_app.paypal_sandbox import (
    MAX_BODY_BYTES,
    MAX_BODY_DEPTH,
    ORDER_PATH,
    SANDBOX_ENDPOINT,
    SandboxWireResponse,
)
from cartreadback_app.provider_json import strict_provider_json
from cartreadback_app.validation import canonical, digest

HOST = "api-m.sandbox.paypal.com"
PORT = 443
OAUTH_PATH = "/v1/oauth2/token"
OAUTH_BODY = b"grant_type=client_credentials"
OAUTH_LIMIT = 8192
HEADER_LIMIT = 8192
HEADER_COUNT = 32
TOKEN_LIMIT = 4096
TOKEN_LIFETIME_LIMIT = 86400
VERSION = "paypal-https-groundwork-v1"


def _unavailable() -> ProviderAmbiguity:
    return ProviderAmbiguity("Sandbox exchange unavailable")


def _matches(value: object, pattern: str) -> str:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise _unavailable()
    return value


def _positive_timeout(value: object) -> float:
    if type(value) not in (int, float) or not 0 < value <= 30:
        raise _unavailable()
    return float(value)


def _reject_proxy_or_trust_override() -> None:
    # Do not silently bypass a configured proxy, even HTTP_PROXY in CGI mode or
    # NO_PROXY. Do not expose its value: a proxy URL may itself contain a secret.
    if any(
        value
        for name, value in os.environ.items()
        if name.lower().endswith("_proxy")
        or name.upper() in {"SSL_CERT_FILE", "SSL_CERT_DIR"}
    ):
        raise _unavailable()
    proxies = getproxies()
    if (
        type(proxies) is not dict
        or any(
            type(k) is not str or type(v) is not str for k, v in proxies.items()
        )
        or any(proxies.values())
    ):
        raise _unavailable()


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    _check_context(context)
    return context


def _check_context(context: object) -> None:
    if (
        type(context) is not ssl.SSLContext
        or context.verify_mode != ssl.CERT_REQUIRED
        or context.check_hostname is not True
        or context.minimum_version < ssl.TLSVersion.TLSv1_2
    ):
        raise _unavailable()


@dataclass(frozen=True, repr=False)
class SandboxClientCredentials:
    """In-memory credential value; examples/tests contain synthetic values only.

    Construction does not obtain permission, retrieve secrets or prove sandbox
    account identity. Python strings cannot be claimed securely zeroized.
    """

    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        """Reject ambiguous Basic-auth input without echoing secret values."""
        _matches(self.client_id, r"[A-Za-z0-9._~-]{1,256}")
        _matches(self.client_secret, r"[A-Za-z0-9._~-]{1,256}")

    def __repr__(self) -> str:
        """Hide both values from ordinary object inspection and diagnostics."""
        return "SandboxClientCredentials(<redacted>)"


@dataclass(frozen=True)
class HttpsPolicy:
    """Conservative local timeout policy, not proven remote cancellation."""

    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        """Require finite, bounded per-operation waits."""
        _positive_timeout(self.connect_timeout_seconds)
        _positive_timeout(self.read_timeout_seconds)


class ConnectionFactory(Protocol):
    """Trusted injected connection seam; tests never open a socket."""

    def __call__(
        self, host: str, port: int, *, timeout: float, context: ssl.SSLContext
    ) -> http.client.HTTPSConnection:
        """Construct one fixed-target connection without retries or tunnels."""
        ...


class DirectSandboxConnectionFactory:
    """Unselected stdlib factory; constructing a connection does not connect.

    Never used by defaults or executed by tests without HTTPSConnection mocked.
    Passing this factory to a future runner is a separately authorized live gate.
    """

    def __call__(
        self, host: str, port: int, *, timeout: float, context: ssl.SSLContext
    ) -> http.client.HTTPSConnection:
        """Fix the target and retain verified TLS without proxy/tunnel knobs."""
        _reject_proxy_or_trust_override()
        if host != HOST or type(port) is not int or port != PORT:
            raise _unavailable()
        _positive_timeout(timeout)
        _check_context(context)
        connection = http.client.HTTPSConnection(
            HOST, PORT, timeout=timeout, context=context
        )
        connection.set_debuglevel(0)
        return connection


@dataclass(frozen=True, repr=False)
class _Token:
    value: str = field(repr=False)
    expires_at: float


@dataclass(frozen=True)
class _Deadline:
    expires_at: float

    def remaining(self, limit: float = 30.0) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise _unavailable()
        return min(remaining, limit)


def _checked_request(request: object, headers: object) -> dict[str, str]:
    if type(request) is not PaymentRequest or type(headers) is not dict:
        raise _unavailable()
    if type(request.path) is not str or type(request.body) is not str:
        raise _unavailable()
    base_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if request.method == "GET":
        _matches(request.path, re.escape(ORDER_PATH) + r"/[A-Z0-9]{1,36}")
        if request.body != "" or headers != base_headers:
            raise _unavailable()
    elif request.method == "POST":
        if request.path != ORDER_PATH:
            _matches(
                request.path, re.escape(ORDER_PATH) + r"/[A-Z0-9]{1,36}/capture"
            )
            if request.body != "{}":
                raise _unavailable()
        if set(headers) != set(base_headers) | {"Prefer", "PayPal-Request-Id"}:
            raise _unavailable()
        if any(headers[key] != value for key, value in base_headers.items()):
            raise _unavailable()
        if headers["Prefer"] != "return=representation":
            raise _unavailable()
        operation = headers["PayPal-Request-Id"]
        if type(operation) is not str:
            raise _unavailable()
        parsed = UUID(operation)
        if str(parsed) != operation or parsed.version != 4:
            raise _unavailable()
        body = request.body.encode("utf-8")
        raw = strict_provider_json(
            body, max_bytes=MAX_BODY_BYTES, max_depth=MAX_BODY_DEPTH
        )
        if canonical(raw) != request.body:
            raise _unavailable()
    else:
        raise _unavailable()
    return dict(headers)


def _response_length(response: http.client.HTTPResponse, maximum: int) -> int:
    headers = response.getheaders()
    if type(headers) is not list or len(headers) > HEADER_COUNT:
        raise _unavailable()
    total, values = 0, {}
    for pair in headers:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise _unavailable()
        name, value = pair
        _matches(name, r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,80}")
        _matches(value, r"[\x20-\x7e]{0,4096}")
        total += len(name) + len(value) + 4
        key = name.lower()
        if total > HEADER_LIMIT or key in values:
            raise _unavailable()
        values[key] = value.strip()
    if (
        "transfer-encoding" in values
        or values.get("content-encoding", "identity").lower() != "identity"
    ):
        raise _unavailable()
    media = [
        part.strip().lower()
        for part in values.get("content-type", "").split(";")
    ]
    if media not in (
        ["application/json"],
        ["application/json", "charset=utf-8"],
    ):
        raise _unavailable()
    length = _matches(values.get("content-length"), r"(?:0|[1-9][0-9]{0,5})")
    if int(length) > maximum:
        raise _unavailable()
    return int(length)


@dataclass(frozen=True, repr=False)
class SandboxHttpsTransport:
    """One OAuth plus one Orders attempt; neither source/factory has a default.

    This marked network-capable groundwork is not an offline provider or enabled
    runtime. Caller timeout poisons this instance; a daemon may still finish its
    I/O. No socket/DNS/header cancellation or Python secret zeroization is claimed.
    """

    credential_source: Callable[[], SandboxClientCredentials] | None = field(
        default=None, repr=False
    )
    connection_factory: ConnectionFactory | None = field(
        default=None, repr=False
    )
    credential_reference: str = "unconfigured"
    policy: HttpsPolicy = HttpsPolicy()
    requires_live_authorization = True

    def __post_init__(self) -> None:
        """Validate non-secret configuration without loading credentials or I/O."""
        _matches(self.credential_reference, r"[A-Za-z0-9._:/-]{1,160}")
        if type(self.policy) is not HttpsPolicy:
            raise _unavailable()
        object.__setattr__(self, "_flight", threading.Lock())
        object.__setattr__(self, "_blocked", False)

    def __repr__(self) -> str:
        """Do not render callable captures, credentials or tokens."""
        return "SandboxHttpsTransport(<redacted>, network-groundwork)"

    @property
    def configuration_sha256(self) -> str:
        """Bind public route/limit/reference settings for a future genuine gate."""
        return digest(
            {
                "version": VERSION,
                "endpoint": SANDBOX_ENDPOINT,
                "credential_reference": self.credential_reference,
                "connect_timeout_seconds": self.policy.connect_timeout_seconds,
                "read_timeout_seconds": self.policy.read_timeout_seconds,
                "proxy": "deny-configured",
                "tls_minimum": "TLS1.2",
                "header_bytes": HEADER_LIMIT,
                "header_count": HEADER_COUNT,
                "oauth_bytes": OAUTH_LIMIT,
                "order_bytes": MAX_BODY_BYTES,
                "token_bytes": TOKEN_LIMIT,
                "token_lifetime": TOKEN_LIFETIME_LIMIT,
            }
        )

    def send(
        self,
        endpoint: str,
        request: PaymentRequest,
        headers: dict[str, str],
        *,
        timeout_seconds: float,
    ) -> SandboxWireResponse:
        """Return one bounded response or sanitized ambiguity, never retry."""
        if not self._flight.acquire(blocking=False):
            raise _unavailable()
        try:
            if (
                self._blocked
                or endpoint != SANDBOX_ENDPOINT
                or self.credential_source is None
                or self.connection_factory is None
            ):
                raise _unavailable()
            timeout = _positive_timeout(timeout_seconds)
            owned_headers = _checked_request(request, headers)
            deadline = _Deadline(time.monotonic() + timeout)
            completed = queue.Queue(maxsize=1)

            def run():
                try:
                    result = self._work(request, owned_headers, deadline)
                except Exception:
                    completed.put(None)
                else:
                    completed.put(result)

            try:
                threading.Thread(target=run, daemon=True).start()
                result = completed.get(timeout=deadline.remaining())
            except Exception:
                object.__setattr__(self, "_blocked", True)
                raise _unavailable() from None
            if result is None or time.monotonic() >= deadline.expires_at:
                object.__setattr__(self, "_blocked", True)
                raise _unavailable()
            return result
        except Exception:
            # Never retain an injected raw exception, response body or header.
            raise _unavailable() from None
        finally:
            self._flight.release()

    def _work(
        self, request: PaymentRequest, headers: dict, deadline: _Deadline
    ) -> SandboxWireResponse:
        _reject_proxy_or_trust_override()
        credentials = self.credential_source()
        if type(credentials) is not SandboxClientCredentials:
            raise _unavailable()
        basic = base64.b64encode(
            (credentials.client_id + ":" + credentials.client_secret).encode(
                "ascii"
            )
        ).decode("ascii")
        started = time.monotonic()
        status, body = self._http(
            "POST",
            OAUTH_PATH,
            OAUTH_BODY,
            {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + basic,
            },
            deadline,
            OAUTH_LIMIT,
        )
        if status != 200:
            raise _unavailable()
        raw = strict_provider_json(body, max_bytes=OAUTH_LIMIT, max_depth=8)
        token_type = raw.get("token_type")
        lifetime = raw.get("expires_in")
        if (
            type(token_type) is not str
            or token_type.lower() != "bearer"
            or type(lifetime) is not int
            or not 1 <= lifetime <= TOKEN_LIFETIME_LIMIT
        ):
            raise _unavailable()
        value = _matches(
            raw.get("access_token"), r"[A-Za-z0-9._~+/-]{1,4096}={0,2}"
        )
        if len(value) > TOKEN_LIMIT:
            raise _unavailable()
        _matches(raw.get("scope"), r"[\x20-\x7e]{1,4096}")
        token = _Token(value, started + lifetime - 1.0)
        order_deadline = _Deadline(min(deadline.expires_at, token.expires_at))
        order_deadline.remaining()
        status, body = self._http(
            request.method,
            request.path,
            request.body.encode("utf-8"),
            {**headers, "Authorization": "Bearer " + token.value},
            order_deadline,
            MAX_BODY_BYTES,
        )
        return SandboxWireResponse(status, body)

    def _http(
        self,
        method: str,
        path: str,
        body: bytes,
        headers: dict,
        deadline: _Deadline,
        maximum: int,
    ) -> tuple[int, bytes]:
        _reject_proxy_or_trust_override()
        connection = response = None
        close_failed = False
        try:
            context = _tls_context()
            connection = self.connection_factory(
                HOST,
                PORT,
                timeout=deadline.remaining(self.policy.connect_timeout_seconds),
                context=context,
            )
            connection.set_debuglevel(0)
            connection.connect()
            # getresponse() may detach connection.sock for Connection: close.
            # Retain the original socket while HTTPResponse owns its makefile.
            active_socket = connection.sock
            self._read_timeout(active_socket, deadline)
            connection.request(
                method,
                path,
                body=body,
                headers={
                    **headers,
                    "Host": HOST,
                    "Connection": "close",
                    "Accept-Encoding": "identity",
                    "Content-Length": str(len(body)),
                },
                encode_chunked=False,
            )
            self._read_timeout(active_socket, deadline)
            response = connection.getresponse()
            deadline.remaining()
            status = response.status
            if (
                type(status) is not int
                or not 100 <= status <= 599
                or 300 <= status <= 399
            ):
                raise _unavailable()
            length = _response_length(response, maximum)
            data = bytearray()
            while len(data) < length:
                self._read_timeout(active_socket, deadline)
                chunk = response.read(min(4096, length - len(data)))
                if (
                    type(chunk) is not bytes
                    or not chunk
                    or len(data) + len(chunk) > length
                ):
                    raise _unavailable()
                data.extend(chunk)
            # A fully consumed stdlib frame closes its makefile. With a close
            # response that releases the final socket reference; touching the
            # descriptor again would raise EBADF. Its read(1) is then immediate.
            if not response.isclosed():
                self._read_timeout(active_socket, deadline)
            if response.read(1) != b"":
                raise _unavailable()
            deadline.remaining()
            return status, bytes(data)
        finally:
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        close_failed = True
            if close_failed:
                raise _unavailable() from None

    def _read_timeout(self, active_socket: object, deadline: _Deadline) -> None:
        active_socket.settimeout(
            deadline.remaining(self.policy.read_timeout_seconds)
        )
