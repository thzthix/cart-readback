"""Fixed-origin HTTPS mechanics for explicitly injected offline connections.

No network factory, credential loader or runtime enable is selected by default.
The concrete stdlib constructor stays unselected. Injected callbacks and installed
host contexts are trusted Python, not an isolation boundary or billing authority.
"""

import http.client
import math
import re
import ssl
import threading
from dataclasses import asdict, dataclass
from typing import Callable

from cartreadback_app.inference_config import ENDPOINT
from cartreadback_app.responses_adapter import Deadline, WireResponse
from cartreadback_app.validation import AppError, digest

_HOST = "api.openai.com"
_PATH = "/v1/responses"
_MAX_REQUEST = 65_536
_MAX_RESPONSE = 131_072
_CHUNK = 8_192
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")


def valid_request_id(value: object) -> bool:
    """Accept bounded opaque header IDs, without assuming a provider prefix.

    OpenAI documents x-request-id as an opaque debugging identifier, not a req_
    grammar. This local supported subset is shared by transport and accounting;
    future unsupported formats fail closed. It is not proof of provider origin.
    """
    return type(value) is str and _REQUEST_ID.fullmatch(value) is not None


def _failure(timeout: bool = False) -> AppError:
    if timeout:
        return AppError(
            "MODEL_TIMEOUT", "Model deadline exceeded; no retry.", 503
        )
    return AppError("MODEL_UNAVAILABLE", "Model transport unavailable.", 503)


@dataclass(frozen=True)
class HTTPSRoutingConfig:
    """Nonsecret route selection; arbitrary hosts/proxies are not supported."""

    route: str = "direct"

    def __post_init__(self) -> None:
        """Accept only explicit direct or PythonAnywhere CONNECT routing."""
        if type(self.route) is not str or self.route not in {
            "direct",
            "pythonanywhere",
        }:
            raise _failure()

    @property
    def metadata(self) -> dict:
        """Return a host-owned identity for future dispatch/config fencing."""
        identity = {
            **asdict(self),
            "transport_version": "responses-https-injected-v1",
            "endpoint": ENDPOINT,
            "proxy": "http://proxy.server:3128"
            if self.route == "pythonanywhere"
            else None,
            "tls_minimum": "TLSv1.2",
            "tls_hostname_check": True,
            "tls_certificate_check": "CERT_REQUIRED",
            "ambient_proxy": "ignored",
            "max_request_bytes": _MAX_REQUEST,
            "max_response_bytes": _MAX_RESPONSE,
            "max_header_fields": 64,
            "max_header_characters": 16_384,
            "http_parser_version": "strict-status-headers-chunks-v1",
            "retries": 0,
            "redirects": 0,
            "runtime_enable": "not-shipped",
        }
        return {**identity, "transport_config_sha256": digest(identity)}


class _StrictHeadReader:
    """Validate raw bounded status/header lines before stdlib normalization."""

    def __init__(self, reader):
        self._reader = reader
        self._phase = "status"
        self._count = 0
        self._size = 0

    def __getattr__(self, name):
        return getattr(self._reader, name)

    def readline(self, limit=-1):
        if self._phase == "body":
            return self._reader.readline(limit)
        # Bound each raw line before the email-based stdlib header parser sees it.
        amount = 4356 if limit < 0 else min(limit, 4356)
        line = self._reader.readline(amount)
        if type(line) is not bytes or not line.endswith(b"\r\n"):
            raise _failure()
        if self._phase == "status":
            if (
                re.fullmatch(rb"HTTP/1\.1 200 [\x20-\x7e]{0,1024}\r\n", line)
                is None
            ):
                raise _failure()
            self._phase = "headers"
            return line
        self._size += len(line)
        if self._size > 16_384:
            raise _failure()
        if line == b"\r\n":
            self._phase = "body"
            return line
        self._count += 1
        if self._count > 64 or b":" not in line:
            raise _failure()
        name, value = line[:-2].split(b":", 1)
        if (
            not 1 <= len(name) <= 256
            or len(value) > 4096
            or _HEADER_NAME.fullmatch(name.decode("ascii", errors="strict"))
            is None
            or any(char < 32 or char > 126 for char in value)
        ):
            raise _failure()
        return line


class _StrictHTTPResponse(http.client.HTTPResponse):
    """Narrow HTTP/1.1 parser rejecting stdlib's permissive framing cases."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fp = _StrictHeadReader(self.fp)

    def _read_next_chunk_size(self):
        line = self.fp.readline(12)
        if (
            re.fullmatch(rb"(?:0|[1-9a-fA-F][0-9a-fA-F]{0,7})\r\n", line)
            is None
        ):
            raise _failure()
        size = int(line[:-2], 16)
        if size > _MAX_RESPONSE:
            raise _failure()
        return size

    def _get_chunk_left(self):
        left = self.chunk_left
        if left is None or left == 0:
            if left == 0 and self._safe_read(2) != b"\r\n":
                raise _failure()
            left = self._read_next_chunk_size()
            if left == 0:
                # Extensions/trailers are unsupported, never silently discarded.
                if self._safe_read(2) != b"\r\n":
                    raise _failure()
                self._close_conn()
                left = None
            self.chunk_left = left
        return left


def _check_deadline(deadline: object) -> Deadline:
    if type(deadline) is not Deadline:
        raise _failure()
    for value in (
        deadline.expires_at,
        deadline.connect_limit,
        deadline.read_limit,
    ):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise _failure()
    if not 0 < deadline.connect_limit <= 3 or not 0 < deadline.read_limit <= 12:
        raise _failure()
    deadline.remaining()
    return deadline


def _response_headers(
    response: http.client.HTTPResponse,
) -> tuple[str, int | None]:
    """Check framing/encoding after stdlib's separately bounded header parser."""
    raw = response.getheaders()
    if type(raw) is not list or len(raw) > 64:
        raise _failure()
    relevant = {}
    size = 0
    unique = {
        "content-type",
        "content-length",
        "transfer-encoding",
        "content-encoding",
        "x-request-id",
    }
    for pair in raw:
        if type(pair) is not tuple or len(pair) != 2:
            raise _failure()
        name, value = pair
        if (
            type(name) is not str
            or type(value) is not str
            or len(name) > 256
            or len(value) > 4096
            or _HEADER_NAME.fullmatch(name) is None
            or any(ord(char) < 32 or ord(char) > 126 for char in value)
        ):
            raise _failure()
        size += len(name) + len(value)
        if size > 16_384:
            raise _failure()
        lower = name.lower()
        if lower in unique:
            if lower in relevant:
                raise _failure()
            if lower == "transfer-encoding" and value != value.strip():
                # stdlib does not trim this value when selecting chunk decoding.
                raise _failure()
            relevant[lower] = value.strip()
    content_type = relevant.get("content-type", "").lower()
    if (
        re.fullmatch(
            r'application/json(?:;\s*charset=(?:utf-8|"utf-8"))?', content_type
        )
        is None
    ):
        raise _failure()
    if relevant.get("content-encoding", "identity").lower() != "identity":
        raise _failure()
    transfer = relevant.get("transfer-encoding")
    length = relevant.get("content-length")
    if transfer is not None and (
        transfer.lower() != "chunked" or length is not None
    ):
        raise _failure()
    if type(response) is _StrictHTTPResponse and response.chunked != (
        transfer is not None
    ):
        raise _failure()
    expected = None
    if length is not None:
        if re.fullmatch(r"0|[1-9][0-9]{0,5}", length) is None:
            raise _failure()
        expected = int(length)
        if expected > _MAX_RESPONSE:
            raise _failure()
    request_id = relevant.get("x-request-id", "")
    if not valid_request_id(request_id):
        raise _failure()
    return request_id, expected


class InjectedHTTPSTransport:
    """One fixed-origin exchange with explicit trusted connection/credential seams.

    The factory must obey the stdlib HTTPSConnection contract, including TLS/SNI,
    header-parser bounds and no implicit I/O before connect. There is no default
    factory. The caller must consume or close the returned WireResponse, even if
    iteration never starts. A failure blocks this instance; no automatic retry,
    credential refresh, alternate route or ambient proxy discovery occurs.
    """

    def __init__(
        self,
        connection_factory: Callable[..., http.client.HTTPSConnection],
        credential_provider: Callable[[], str],
        config: HTTPSRoutingConfig | None = None,
    ) -> None:
        """Retain callbacks without calling them or loading credentials/network."""
        if not callable(connection_factory) or not callable(
            credential_provider
        ):
            raise _failure()
        self._config = config if config is not None else HTTPSRoutingConfig()
        if type(self._config) is not HTTPSRoutingConfig:
            raise _failure()
        self._factory = connection_factory
        self._credentials = credential_provider
        self._flight = threading.Lock()
        self._blocked = False

    @property
    def metadata(self) -> dict:
        """Expose only nonsecret routing facts, never callbacks or credentials."""
        return self._config.metadata

    def _borrow_credentials(self, deadline):
        deadline.remaining()
        return self._credentials()

    def _scope_headers(self):
        return {}

    def _before_io(self, deadline):
        deadline.remaining()

    def _before_post(self, deadline):
        deadline.remaining()

    def send(
        self, endpoint: str, body: bytes, *, deadline: Deadline
    ) -> WireResponse:
        """Prepare one TLS-verified fixed POST; stream a bounded response once."""
        if (
            type(endpoint) is not str
            or endpoint != ENDPOINT
            or type(body) is not bytes
            or not 0 < len(body) <= _MAX_REQUEST
        ):
            raise _failure()
        deadline = _check_deadline(deadline)
        if not self._flight.acquire(blocking=False):
            raise _failure()
        connection = None
        response = None
        established_socket = None
        closed = False
        finished = False
        close_lock = threading.Lock()

        def close() -> None:
            nonlocal closed
            with close_lock:
                if closed:
                    return
                closed = True
                if not finished:
                    self._blocked = True
                interrupted = None
                for resource in (response, connection):
                    if resource is not None:
                        try:
                            resource.close()
                        except BaseException as error:
                            # Closing is best effort, never proof of cancellation.
                            self._blocked = True
                            if (
                                not isinstance(error, Exception)
                                and interrupted is None
                            ):
                                interrupted = error
                self._flight.release()
                if interrupted is not None:
                    raise interrupted

        def socket_timeout() -> None:
            if closed or established_socket is None:
                raise _failure()
            self._before_io(deadline)
            # getresponse() may clear connection.sock for Connection: close.
            # HTTPResponse's file object retains the established descriptor.
            established_socket.settimeout(deadline.read_timeout())

        try:
            if self._blocked:
                raise _failure()
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            host, port = (
                ("proxy.server", 3128)
                if self._config.route == "pythonanywhere"
                else (_HOST, 443)
            )
            connection = self._factory(
                host, port, timeout=deadline.connect_timeout(), context=context
            )
            connection.set_debuglevel(0)
            connection.response_class = _StrictHTTPResponse
            # Explicit connect only: http.client must not reconnect while sending.
            connection.auto_open = 0
            if self._config.route == "pythonanywhere":
                connection.set_tunnel(_HOST, 443, headers={})
            self._before_io(deadline)
            connection.connect()
            established_socket = connection.sock
            socket_timeout()
            token = self._borrow_credentials(deadline)
            if (
                type(token) is not str
                or not 1 <= len(token) <= 4096
                or _TOKEN.fullmatch(token) is None
            ):
                raise _failure()
            headers = {
                **self._scope_headers(),
                "Host": _HOST,
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Content-Length": str(len(body)),
                "Connection": "close",
            }
            try:
                socket_timeout()
                self._before_post(deadline)
                connection.request(
                    "POST",
                    _PATH,
                    body=body,
                    headers=headers,
                    encode_chunked=False,
                )
            finally:
                token = None
                headers.clear()
            socket_timeout()
            response = connection.getresponse()
            deadline.remaining()
            if (
                isinstance(response, http.client.HTTPResponse)
                and type(response) is not _StrictHTTPResponse
            ):
                # A real stdlib connection must honor the supplied strict parser.
                raise _failure()
            if type(response.status) is not int or response.status != 200:
                raise _failure()
            if type(response.version) is not int or response.version != 11:
                raise _failure()
            request_id, expected = _response_headers(response)
            deadline.remaining()

            def chunks():
                nonlocal finished
                total = 0

                def finish() -> None:
                    nonlocal finished
                    deadline.remaining()
                    with close_lock:
                        if closed or (
                            expected is not None and expected != total
                        ):
                            raise _failure()
                        finished = True

                try:
                    while True:
                        # A final Content-Length read can close fp and release
                        # its last socket reference. Never settimeout on that fd.
                        if (
                            type(response) is _StrictHTTPResponse
                            and response.isclosed()
                        ):
                            finish()
                            break
                        socket_timeout()
                        amount = min(_CHUNK, _MAX_RESPONSE - total + 1)
                        chunk = response.read1(amount)
                        deadline.remaining()
                        if (
                            closed
                            or type(chunk) is not bytes
                            or len(chunk) > amount
                        ):
                            raise _failure()
                        if not chunk:
                            finish()
                            break
                        total += len(chunk)
                        if total > _MAX_RESPONSE or (
                            expected is not None and total > expected
                        ):
                            raise _failure()
                        yield chunk
                except Exception as error:
                    self._blocked = True
                    raise _failure(
                        isinstance(error, TimeoutError)
                        or isinstance(error, AppError)
                        and error.code == "MODEL_TIMEOUT"
                    ) from None
                finally:
                    close()

            return WireResponse(200, request_id, chunks(), close)
        except BaseException as error:
            self._blocked = True
            close()
            if not isinstance(error, Exception):
                # Honor process/user interruption, but never leak resources.
                raise
            raise _failure(
                isinstance(error, TimeoutError)
                or isinstance(error, AppError)
                and error.code == "MODEL_TIMEOUT"
            ) from None


class ScopedHTTPSTransport(InjectedHTTPSTransport):
    """Host-bound transport, distinct from the unscoped offline callback seam.

    A trusted provisioner supplies the complete installed context and opaque
    handle. No resolver, credential source or network factory is selected here.
    """

    def __init__(self, connection_factory, installed, clock, claim_expires_at):
        """Retain the host context without constructing connections or secrets."""
        from cartreadback_app.context_runtime import InstalledProviderContext

        if (
            type(installed) is not InstalledProviderContext
            or type(claim_expires_at) is not int
            or claim_expires_at <= 0
        ):
            raise _failure()
        self._installed = installed
        self._clock = clock
        self._claim_expires_at = claim_expires_at
        super().__init__(connection_factory, self._denied, installed.route)

    @staticmethod
    def _denied():
        raise _failure()

    def _validate_window(self):
        now = self._clock()
        self._installed.validate(now)
        if now >= self._claim_expires_at:
            raise _failure(timeout=True)

    def _borrow_credentials(self, deadline):
        self._validate_window()
        deadline.remaining()
        return self._installed.credential_handle.borrow(
            expected_binding=self._installed.binding, deadline=deadline
        )

    def _scope_headers(self):
        self._validate_window()
        binding = self._installed.binding
        return {
            "OpenAI-Organization": binding.organization,
            "OpenAI-Project": binding.project,
        }

    def _before_io(self, deadline):
        self._validate_window()
        deadline.remaining()

    def _before_post(self, deadline):
        self._validate_window()
        deadline.remaining()

    def send(self, endpoint, body, *, deadline):
        """Check approval and claim wall expiry before all sensitive transitions."""
        self._validate_window()
        return super().send(endpoint, body, deadline=deadline)


def unselected_stdlib_connection(host, port, *, timeout, context):
    """Construct stdlib HTTPS mechanics; never selected by default or tests."""
    return http.client.HTTPSConnection(
        host, port, timeout=timeout, context=context
    )
