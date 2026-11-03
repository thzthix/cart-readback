"""Loopback-only same-origin HTTP transport for the local fixture demo."""

import json
import re
import secrets
import socket
import sqlite3
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cartreadback_app.service import Service
from cartreadback_app.validation import (
    MAX_BODY_BYTES,
    AppError,
    parse_json,
    text_hash,
    token,
)

ORDER_ROUTE = re.compile(
    r"^/api/orders/([0-9a-f-]{36})/(fixture-approve|verify|capture|reconcile)$"
)
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.mjs": ("app.mjs", "text/javascript; charset=utf-8"),
    "/core.mjs": ("core.mjs", "text/javascript; charset=utf-8"),
}


class LocalServer(ThreadingHTTPServer):
    """Restricted local development server, not a production HTTP stack."""

    daemon_threads = True
    request_queue_size = 32

    def __init__(
        self, address: tuple[str, int], service: Service, ui_root: Path
    ):
        """Accept only literal IPv4 loopback and an explicit static-file root."""
        if address[0] != "127.0.0.1":
            raise ValueError("CartReadback may only bind to 127.0.0.1")
        self.service = service
        self.ui_root = ui_root.resolve()
        super().__init__(address, Handler)
        self.allowed_host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.allowed_host}"


class Handler(BaseHTTPRequestHandler):
    """Validate the transport before handing plain typed data to the service."""

    server: LocalServer
    protocol_version = "HTTP/1.1"
    server_version = "CartReadbackFixture/1"
    sys_version = ""

    def setup(self) -> None:
        """Bound slow or incomplete local requests by socket timeout."""
        super().setup()
        self.connection.settimeout(5)
        self.sid = None

    def log_message(self, _format: str, *_args) -> None:
        """Do not log headers, cookies, bodies, source content or identifiers."""

    def _reply(
        self,
        status: int,
        body: bytes,
        content_type: str,
        cookie: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Connection", "close")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(
        self, status: int, payload: dict, cookie: str | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
        self._reply(status, body, "application/json; charset=utf-8", cookie)

    def _error(self, error: AppError) -> None:
        revision = self.server.service.revision(self.sid) if self.sid else 0
        self._json(
            error.status,
            {
                "api_version": "1",
                "mode": "fixture",
                "revision": revision,
                "error": {"code": error.code, "message": error.message},
            },
        )

    def _host(self) -> None:
        if self.headers.get_all("Host") != [self.server.allowed_host]:
            raise AppError(
                "ORIGIN_REJECTED",
                "Host does not match the configured origin.",
                403,
            )
        if "?" in self.path or "#" in self.path or len(self.path) > 300:
            raise AppError(
                "INVALID_INPUT",
                "Query parameters and fragments are unsupported.",
            )

    def _owner_cookie(self) -> str | None:
        headers = self.headers.get_all("Cookie") or []
        if len(headers) > 1:
            raise AppError("CSRF_REJECTED", "Ambiguous session cookie.", 403)
        try:
            cookie = SimpleCookie()
            cookie.load(headers[0] if headers else "")
            value = (
                cookie["cr_session"].value if "cr_session" in cookie else None
            )
            if value is not None:
                token(value)
            return value
        except (CookieError, AppError) as error:
            raise AppError(
                "CSRF_REJECTED", "Invalid session cookie.", 403
            ) from error

    def _get(self) -> None:
        self._host()
        if self.path == "/api/bootstrap":
            session, created = self.server.service.store.session(
                self._owner_cookie()
            )
            self.sid = session["sid"]
            cookie = (
                f"cr_session={self.sid}; HttpOnly; SameSite=Strict; Path=/"
                if created
                else None
            )
            self._json(200, self.server.service.bootstrap(self.sid), cookie)
        elif self.path in STATIC:
            filename, content_type = STATIC[self.path]
            try:
                body = (self.server.ui_root / filename).read_bytes()
            except FileNotFoundError as error:
                raise AppError(
                    "NOT_FOUND", "UI file is not available yet.", 404
                ) from error
            self._reply(200, body, content_type)
        else:
            raise AppError("NOT_FOUND", "Unknown path.", 404)

    def _post(self) -> None:
        self._host()
        if self.headers.get_all("Origin") != [self.server.origin]:
            raise AppError(
                "ORIGIN_REJECTED", "Exact same-origin request required.", 403
            )
        if self.headers.get("Sec-Fetch-Site") not in {None, "same-origin"}:
            raise AppError(
                "ORIGIN_REJECTED", "Cross-origin request rejected.", 403
            )
        if self.headers.get_all("Content-Type") != ["application/json"]:
            raise AppError(
                "INVALID_INPUT", "Content-Type must be application/json.", 415
            )
        candidate = self._owner_cookie()
        if not candidate:
            raise AppError(
                "CSRF_REJECTED", "An existing owner session is required.", 403
            )
        session, created = self.server.service.store.session(candidate)
        if created:
            # Do not turn an unknown supplied owner into a wildcard owner.
            raise AppError("CSRF_REJECTED", "Unknown owner session.", 403)
        self.sid = session["sid"]
        csrf_values = self.headers.get_all("X-CSRF-Token")
        try:
            csrf = (
                token(csrf_values[0])
                if csrf_values and len(csrf_values) == 1
                else None
            )
        except AppError as error:
            raise AppError(
                "CSRF_REJECTED", "Invalid CSRF token.", 403
            ) from error
        if csrf is None or not secrets.compare_digest(
            text_hash(csrf), session["csrf"]
        ):
            raise AppError("CSRF_REJECTED", "Invalid CSRF token.", 403)
        if self.headers.get("Transfer-Encoding") is not None:
            raise AppError("INVALID_INPUT", "Transfer-Encoding is unsupported.")
        lengths = self.headers.get_all("Content-Length")
        if (
            not lengths
            or len(lengths) != 1
            or not re.fullmatch(r"[0-9]{1,8}", lengths[0])
        ):
            raise AppError(
                "INVALID_INPUT", "Exactly one Content-Length is required."
            )
        length = int(lengths[0])
        if length > MAX_BODY_BYTES:
            raise AppError(
                "PAYLOAD_TOO_LARGE", "Request body exceeds 16 KiB.", 413
            )
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise AppError("INVALID_INPUT", "Incomplete request body.")
        body = parse_json(raw)
        if self.path in {"/api/analyze", "/api/confirm", "/api/orders"}:
            action = self.path.rsplit("/", 1)[-1]
            order_id = None
        else:
            match = ORDER_ROUTE.fullmatch(self.path)
            if not match:
                raise AppError("NOT_FOUND", "Unknown action path.", 404)
            order_id, action = match.groups()
        keys = self.headers.get_all("Idempotency-Key") or []
        if len(keys) > 1:
            raise AppError(
                "INVALID_INPUT", "Duplicate Idempotency-Key headers."
            )
        result = self.server.service.mutate(
            self.sid,
            action,
            body,
            order_id,
            keys[0] if keys else None,
        )
        status = (
            409
            if result.get("error")
            else 422
            if result["checkout"]["state"] == "ANALYSIS_BLOCKED"
            else 200
        )
        self._json(status, result)

    def _handle(self, operation) -> None:
        try:
            operation()
        except AppError as error:
            self._error(error)
        except (socket.timeout, TimeoutError):
            self._error(AppError("INVALID_INPUT", "Request timed out.", 408))
        except sqlite3.OperationalError:
            self._error(
                AppError(
                    "STORAGE_UNAVAILABLE",
                    "Local storage is temporarily unavailable.",
                    503,
                )
            )

    def do_GET(self) -> None:
        """Serve read-only bootstrap or an allowlisted static file."""
        self._handle(self._get)

    def do_HEAD(self) -> None:
        """Read the same resources without a response body."""
        self._handle(self._get)

    def do_POST(self) -> None:
        """Process an explicit same-origin mutation."""
        self._handle(self._post)

    def _unsupported(self) -> None:
        self._error(AppError("INVALID_INPUT", "Unsupported HTTP method.", 405))

    do_PUT = _unsupported
    do_PATCH = _unsupported
    do_DELETE = _unsupported
    do_OPTIONS = _unsupported
    do_TRACE = _unsupported
