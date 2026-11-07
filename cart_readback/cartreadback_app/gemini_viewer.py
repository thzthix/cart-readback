"""Explicit same-lifetime, read-only view of one host-approved Gemini result."""

import base64
import hashlib
import json
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path

from cartreadback_app.gemini_runtime import GeminiAnalysisRuntime
from cartreadback_app.genuine_gemini import GenuineGeminiAdapter
from cartreadback_app.http import Handler
from cartreadback_app.payments import FixturePaymentAdapter
from cartreadback_app.service import Service
from cartreadback_app.validation import AppError, canonical, parse_json, token

VERSION = "gemini-host-result-viewer-v1"
STATIC = {
    "/viewer": ("viewer.html", "text/html; charset=utf-8"),
    "/viewer.mjs": ("viewer.mjs", "text/javascript; charset=utf-8"),
    "/viewer-core.mjs": ("viewer-core.mjs", "text/javascript; charset=utf-8"),
    "/core.mjs": ("core.mjs", "text/javascript; charset=utf-8"),
}


def _denied() -> AppError:
    return AppError("VIEWER_REJECTED", "Private result view unavailable.", 403)


class GeminiResultViewer(ThreadingHTTPServer):
    """Bind one analyzed Service owner without exposing its owner credential.

    Browser cookies are not port-scoped. Therefore the browser receives only a
    distinct expiring viewer capability, never the Service owner/session token.
    This server does not own or close the Service; the host launcher must hold
    that same Service until server_close and synchronous provider cleanup finish.
    """

    daemon_threads = False
    block_on_close = True
    request_queue_size = 16

    def __init__(
        self,
        address: tuple[str, int],
        service: Service,
        owner: str,
        catalog: dict,
        choices: list[dict],
        ui_root: Path,
        *,
        launch_ttl: int = 60,
        session_ttl: int = 600,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Accept only an already analyzed, exactly scoped Gemini Service."""
        token(owner)
        if (
            address[0] != "127.0.0.1"
            or type(service) is not Service
            or type(service.gemini_analysis) is not GeminiAnalysisRuntime
            or type(service.inference) is not GenuineGeminiAdapter
            or service.inference.runtime is not service.gemini_analysis
            or type(service.payments) is not FixturePaymentAdapter
            or type(launch_ttl) is not int
            or not 1 <= launch_ttl <= 60
            or type(session_ttl) is not int
            or not 1 <= session_ttl <= 600
        ):
            raise _denied()
        installed = service.gemini_analysis.installed
        if not installed or not installed.scope.allows(catalog, choices, owner):
            raise _denied()
        current = service.bootstrap(owner)
        checkout = current["checkout"]
        if (
            not checkout
            or checkout["sku_id"] != catalog["sku_id"]
            or canonical(checkout["conditions"]) != canonical(choices)
            or checkout["model"]["execution_mode"] != "genuine-gemini-capacity"
            or checkout["order"] is not None
            or checkout["confirmation_id"] is not None
        ):
            raise _denied()
        self.service = service
        self.ui_root = ui_root.resolve()
        self._owner = owner
        self._catalog = json.loads(canonical(catalog))
        self._review = checkout["review_id"]
        self._descriptor = {
            "version": VERSION,
            "review_only": True,
            "configured_model": installed.config.model,
            "expected_model_version": installed.config.expected_model_version,
        }
        self._clock = monotonic
        self._launch_deadline = monotonic() + launch_ttl
        self._session_ttl = session_ttl
        self._session_deadline = 0.0
        self._lock = threading.Lock()
        self._launch_token = secrets.token_urlsafe(32)
        self._viewer_token = None
        self._launched = False
        self._stopped = False
        self._http_sockets: set[socket.socket] = set()
        self._http_threads: set[threading.Thread] = set()
        # Permit only the shipped inline bootstrap and style, never unsafe-inline.
        html = (self.ui_root / "viewer.html").read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        if len(scripts) != 1:
            raise _denied()
        styles = re.findall(r"<style>(.*?)</style>", html, re.DOTALL)
        if len(styles) != 1:
            raise _denied()
        self._style_hash = base64.b64encode(
            hashlib.sha256(styles[0].encode()).digest()
        ).decode("ascii")
        self._script_hash = base64.b64encode(
            hashlib.sha256(scripts[0].encode()).digest()
        ).decode("ascii")
        super().__init__(address, ViewerHandler)
        self.allowed_host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.allowed_host}"

    def launch(self, opener: Callable[[str], object]) -> None:
        """Give the capability only to an explicitly trusted local opener once.

        The opener must not log/persist the URL or delegate to an untrusted URL
        service. Calling this is a separately authorized browser action, not part
        of constructing the server. No launch URL is returned or printed.
        """
        with self._lock:
            if self._stopped or self._launched or not self._launch_token:
                raise _denied()
            self._launched = True
            capability = self._launch_token
        try:
            if opener(f"{self.origin}/viewer#launch={capability}") is False:
                raise _denied()
        except Exception:
            with self._lock:
                self._launch_token = None
            raise _denied() from None

    def redeem(self, capability: str) -> str:
        """Atomically consume one bounded launch and mint a view-only cookie."""
        with self._lock:
            if (
                self._stopped
                or not self._launch_token
                or self._clock() >= self._launch_deadline
                or not secrets.compare_digest(capability, self._launch_token)
            ):
                raise _denied()
            self._launch_token = None
            self._viewer_token = secrets.token_urlsafe(32)
            self._session_deadline = self._clock() + self._session_ttl
            return self._viewer_token

    def bootstrap(self, cookie: str | None) -> dict:
        """Read only the bound review; never resolve/create a browser owner."""
        with self._lock:
            if (
                self._stopped
                or not cookie
                or not self._viewer_token
                or self._clock() >= self._session_deadline
                or not secrets.compare_digest(cookie, self._viewer_token)
            ):
                raise _denied()
        result = self.service.bootstrap(self._owner)
        if (
            not result["checkout"]
            or result["checkout"]["review_id"] != self._review
        ):
            raise _denied()
        # Explicit public projection, never an owner-derived CSRF token.
        return {
            key: result[key]
            for key in (
                "api_version",
                "mode",
                "providers",
                "revision",
                "checkout",
                "notice",
            )
        } | {
            "catalog": [json.loads(canonical(self._catalog))],
            "viewer": dict(self._descriptor),
        }

    def process_request(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        """Atomically register each accepted socket and started handler worker.

        Registration/start shares the revocation lock, so shutdown either owns
        the socket/worker or this method rejects and closes the new connection.
        Failed starts are removed before any close can attempt to join them.
        """
        try:
            with self._lock:
                if self._stopped:
                    self.shutdown_request(request)
                    return
                # Reap only workers whose actual thread exit is observable.
                self._http_threads = {
                    worker for worker in self._http_threads if worker.is_alive()
                }
                worker = threading.Thread(
                    target=self._serve_request,
                    args=(request, client_address),
                    daemon=False,
                )
                self._http_sockets.add(request)
                self._http_threads.add(worker)
                try:
                    worker.start()
                except BaseException:
                    self._http_sockets.discard(request)
                    self._http_threads.discard(worker)
                    raise
        except BaseException:
            self.shutdown_request(request)
            raise

    def _serve_request(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        try:
            self.finish_request(request, client_address)
        except BaseException:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            with self._lock:
                self._http_sockets.discard(request)
                # Retain the worker until actual exit can be observed/reaped,
                # so close never mistakes a finalizing handler for a dead one.

    def server_close(self) -> None:
        """Revoke access, interrupt active HTTP I/O and join all handler workers.

        Socket idle timeout alone cannot bound a trickling request. Active
        shutdown closes both directions regardless of incoming client progress.
        The host must call this outside the HTTP handler workers.
        """
        with self._lock:
            self._stopped = True
            self._launch_token = self._viewer_token = None
            requests = tuple(self._http_sockets)
            workers = tuple(self._http_threads)
        super().server_close()
        for request in requests:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            request.close()
        for worker in workers:
            worker.join()

    def handle_error(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        """Never log a request, cookie, launch capability or private exception."""


class ViewerHandler(Handler):
    """Closed route set with no access to ordinary Service mutations."""

    server: GeminiResultViewer
    server_version = "CartReadbackResultViewer/1"

    def _error(self, error: AppError) -> None:
        self._json(
            error.status,
            {
                "api_version": "1",
                "error": {"code": error.code, "message": error.message},
            },
        )

    def _reply(self, status, body, content_type, cookie=None) -> None:
        self.send_response(status)
        for name, value in {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"script-src 'self' 'sha256-{self.server._script_hash}'; "
                f"style-src 'sha256-{self.server._style_hash}'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                "form-action 'none'; object-src 'none'"
            ),
            "Connection": "close",
        }.items():
            self.send_header(name, value)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def _host(self) -> None:
        if (
            self.headers.get_all("Host") != [self.server.allowed_host]
            or "?" in self.path
            or "#" in self.path
            or len(self.path) > 100
        ):
            raise _denied()

    def _cookie(self) -> str | None:
        headers = self.headers.get_all("Cookie") or []
        if len(headers) > 1 or (headers and len(headers[0]) > 2048):
            raise _denied()
        values = []
        seen = set()
        for entry in headers[0].split(";") if headers else []:
            name, separator, value = entry.strip().partition("=")
            if (
                not separator
                or re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) is None
                or name in seen
                or re.fullmatch(
                    r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*", value
                )
                is None
            ):
                raise _denied()
            seen.add(name)
            if name == "cr_viewer":
                if not separator or not re.fullmatch(
                    r"[A-Za-z0-9_-]{43}", value
                ):
                    raise _denied()
                values.append(value)
        if len(values) > 1:
            raise _denied()
        return values[0] if values else None

    def _same_origin(self) -> None:
        if self.headers.get_all("Origin") != [
            self.server.origin
        ] or self.headers.get_all("Sec-Fetch-Site") != ["same-origin"]:
            raise _denied()

    def _get(self) -> None:
        self._host()
        if self.path == "/gemini-viewer/api/bootstrap":
            self._same_origin_read()
            self._json(200, self.server.bootstrap(self._cookie()))
        elif self.path in STATIC:
            filename, kind = STATIC[self.path]
            self._reply(
                200, (self.server.ui_root / filename).read_bytes(), kind
            )
        else:
            raise AppError("NOT_FOUND", "Unknown viewer path.", 404)

    def _same_origin_read(self) -> None:
        # Same-origin GET fetch need not carry Origin; Fetch Metadata must exist.
        if self.headers.get_all("Sec-Fetch-Site") != ["same-origin"]:
            raise _denied()
        origins = self.headers.get_all("Origin")
        if origins is not None and origins != [self.server.origin]:
            raise _denied()

    def _post(self) -> None:
        self._host()
        self._same_origin()
        if self.path != "/gemini-viewer/api/redeem":
            raise AppError(
                "VIEWER_READ_ONLY", "This result is review-only.", 403
            )
        if (
            self.headers.get_all("Content-Type") != ["application/json"]
            or self.headers.get("Transfer-Encoding") is not None
        ):
            raise _denied()
        lengths = self.headers.get_all("Content-Length")
        if (
            not lengths
            or len(lengths) != 1
            or re.fullmatch(r"[0-9]{1,3}", lengths[0]) is None
            or not 1 <= int(lengths[0]) <= 256
        ):
            raise _denied()
        raw = self.rfile.read(int(lengths[0]))
        if len(raw) != int(lengths[0]):
            raise _denied()
        body = parse_json(raw)
        if (
            set(body) != {"launch_capability"}
            or type(body["launch_capability"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", body["launch_capability"])
            is None
        ):
            raise _denied()
        # Cookies are not port-scoped. A well-formed prior viewer cookie is
        # inert here: the fresh one-use launch is the sole new grant authority.
        # Still reject malformed/duplicate cookie framing before consuming it.
        self._cookie()
        cookie = self.server.redeem(body["launch_capability"])
        self._json(
            200,
            {"viewer": VERSION, "redeemed": True},
            f"cr_viewer={cookie}; HttpOnly; SameSite=Strict; Path=/gemini-viewer/api; Max-Age={self.server._session_ttl}",
        )

    def _handle(self, operation) -> None:
        try:
            operation()
        except AppError as error:
            self._error(error)
        except Exception:
            # No exception payload or traceback can disclose a private token.
            self._error(
                AppError("VIEWER_UNAVAILABLE", "Result view failed.", 503)
            )
