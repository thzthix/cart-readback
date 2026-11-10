"""Bounded public-fixture rendering on an authorized GitHub-hosted runner.

This module never imports application services or accepts a remote target.
The CLI is not intended for local browser execution during source preparation.
"""

import base64
import hashlib
import http.client
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import zlib
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SOURCE_REVISION = "4f74a95c5103fddf8b7d881cd69401ad4cb86076"
SOURCE_HASHES = {
    "viewer.html": "c1bec3b9a5c7aa58c1cbb169ff13d3f64baa9141fbe5f8123c358f04eae9b265",
    "viewer.mjs": "d65efc79097d1982f577e69a4dd9d50d5e98ef0889709fcbd89dc5c1811f1b15",
    "viewer-core.mjs": "1be101c87184dcb831223921b97c9001877542fb000517c29b4847c8f11be5a3",
    "core.mjs": "be0bdf05874935f6c4d3c7c0c9e6cd510d30351364aa6e5c85440a05dd119c8a",
}
MAX_BODY = 8 * 1024 * 1024
MARKER = b"cartreadback-public-render-fixture-v1"
ARTIFACT_NAMES = {
    "review-wide.png",
    "review-narrow.png",
    "blocked-wide.png",
    "blocked-narrow.png",
    "receipt.json",
}


CHECK_CODES = frozenset(
    {
        "binary",
        "cleanup-forced-or-unknown",
        "diagnostic-enum",
        "endpoint",
        "envelope",
        "geometry",
        "hosted-only",
        "http",
        "inline",
        "json",
        "layout",
        "png",
        "provenance",
        "readiness",
        "render",
        "server-cleanup",
        "session",
        "source",
        "state",
        "version",
        "viewport-containment",
        "webdriver",
    }
)


OPERATIONS = frozenset({"session_create", "session_timeouts", "version"})
HTTP_KINDS = frozenset({"non_200", "oversize"})
WEBDRIVER_ERRORS = {
    "session not created": "session_not_created",
    "invalid argument": "invalid_argument",
    "timeout": "timeout",
    "unknown error": "unknown_error",
    "invalid session id": "invalid_session_id",
    "unknown command": "unknown_command",
    "unsupported operation": "unsupported_operation",
    "javascript error": "javascript_error",
    "script timeout": "script_timeout",
    "no such window": "no_such_window",
}


class SmokeFailure(Exception):
    """A bounded check with a sanitized, closed-set internal reason code."""

    def __init__(
        self,
        code,
        *,
        operation=None,
        http_kind=None,
        http_status=None,
        webdriver_error=None,
    ):
        """Discard unknown/non-string inputs without converting them to text."""
        self.code = code if type(code) is str and code in CHECK_CODES else None
        self.operation = (
            operation
            if type(operation) is str and operation in OPERATIONS
            else "unavailable"
        )
        self.http_kind = (
            http_kind
            if self.code == "http"
            and type(http_kind) is str
            and http_kind in HTTP_KINDS
            else "unavailable"
        )
        self.http_status = (
            http_status
            if self.code == "http"
            and type(http_status) is int
            and 100 <= http_status <= 599
            else "unavailable"
        )
        self.webdriver_error = (
            webdriver_error
            if type(webdriver_error) is str
            and webdriver_error in WEBDRIVER_ERRORS.values()
            else "unavailable"
        )
        super().__init__(self.code or "check_failed")


@contextmanager
def failure_operation(operation: str):
    """Tag only owned check failures; never inspect arbitrary error objects."""
    if operation not in OPERATIONS:
        raise SmokeFailure("diagnostic-enum")
    try:
        yield
    except SmokeFailure as error:
        if type(error) is SmokeFailure:
            error.operation = operation
        raise


def safe_failure_metadata(
    operation=None, http_kind=None, http_status=None, webdriver_error=None
):
    """Return only known labels and a plain bounded HTTP integer."""
    return {
        "webdriver_error": webdriver_error
        if type(webdriver_error) is str
        and webdriver_error in WEBDRIVER_ERRORS.values()
        else "unavailable",
        "operation": operation
        if type(operation) is str and operation in OPERATIONS
        else "unavailable",
        "http_kind": http_kind
        if type(http_kind) is str and http_kind in HTTP_KINDS
        else "unavailable",
        "http_status": http_status
        if type(http_status) is int and 100 <= http_status <= 599
        else "unavailable",
    }


def bounded_webdriver_error(data: bytes) -> str:
    """Classify only a standard error label, never message or other fields."""
    try:
        root = json.loads(data)
    except (ValueError, UnicodeError):
        return "unavailable"
    if not isinstance(root, dict) or not isinstance(root.get("value"), dict):
        return "unavailable"
    label = root["value"].get("error")
    return (
        WEBDRIVER_ERRORS.get(label, "unavailable")
        if type(label) is str
        else "unavailable"
    )


def checked_sources(directory: Path) -> dict[str, bytes]:
    """Read only four pinned files and reject any changed source bytes."""
    result = {}
    for name, digest in SOURCE_HASHES.items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 65536
        ):
            raise SmokeFailure("source")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SmokeFailure("source")
        result[name] = data
    return result


def policy(html: bytes) -> str:
    """Authorize the exact verified inline script/style, never unsafe-inline."""
    parts = []
    for tag in (b"script", b"style"):
        matches = re.findall(b"<" + tag + b">(.*?)</" + tag + b">", html, re.S)
        if len(matches) != 1:
            raise SmokeFailure("inline")
        digest = base64.b64encode(hashlib.sha256(matches[0]).digest()).decode()
        parts.append("'sha256-" + digest + "'")
    return (
        "default-src 'none'; script-src 'self' "
        + parts[0]
        + "; style-src "
        + parts[1]
        + "; connect-src 'self'; img-src 'none'; font-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )


def fixture(blocked: bool) -> dict:
    """Return wholly invented public data, not an observed model response."""
    source = {
        "source_id": "public-fixture:KB-UK",
        "revision": 1,
        "text": "PUBLIC SYNTHETIC FIXTURE. UK QWERTY. Cable not stated.",
    }
    source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    conditions = [
        {"condition_id": "layout", "kind": "layout", "value": "UK_QWERTY"},
        {
            "condition_id": "cable",
            "kind": "included_cable",
            "value": "USB-C to USB-C",
        },
    ]
    start = source["text"].index("UK QWERTY")
    results = [
        {
            "condition_id": "layout",
            "status": "match",
            "explanation": "Invented fixture match, not model inference.",
            "evidence": [
                {
                    "source_id": source["source_id"],
                    "start": start,
                    "end": start + 9,
                    "quote": "UK QWERTY",
                }
            ],
        },
        {
            "condition_id": "cable",
            "status": "unknown",
            "explanation": "Invented UNKNOWN. No cable inclusion assertion.",
            "evidence": [],
        },
    ]
    return {
        "api_version": "1",
        "mode": "mixed",
        "revision": 1,
        "notice": "PUBLIC SYNTHETIC RENDER FIXTURE; no provider or payment.",
        "viewer": {
            "version": "gemini-host-result-viewer-v1",
            "review_only": True,
            "configured_model": "gemini-2.5-flash-lite",
            "expected_model_version": "gemini-2.5-flash-lite-001",
        },
        "providers": {
            "analysis": {
                "mode": "genuine-gemini-capacity",
                "is_fixture": False,
                "dispatch_available": False,
                "execution_kind": "fabricated-offline",
            },
            "payment": {"mode": "fixture", "is_fixture": True},
            "network_enabled": False,
        },
        "catalog": [
            {
                "sku_id": "KB-UK",
                "name": "PUBLIC SYNTHETIC keyboard",
                "price_minor": 7900,
                "currency": "USD",
                "quantity": 1,
                "catalog_revision": 1,
                "source": source,
                "baseline": {
                    "layout": "UK_QWERTY",
                    "included_cable": "unknown",
                },
            }
        ],
        "checkout": {
            "review_id": "public-fixture",
            "state": "ANALYSIS_BLOCKED" if blocked else "REVIEW_REQUIRED",
            "sku_id": "KB-UK",
            "source": source,
            "amount": {"minor": 7900, "currency": "USD"},
            "snapshot_hash": None if blocked else "b" * 64,
            "confirmation_id": None,
            "order": None,
            "conditions": conditions,
            "results": [] if blocked else results,
            "model": {
                "provider": "google-gemini-generate-content",
                "model_version": "gemini-2.5-flash-lite",
                "prompt_version": "cartreadback-prompt-v2-wire",
                "adapter_version": "genuine-gemini-generation-v1",
                "validator_version": "strict-spans-v1+ordered-results-v1",
                "is_fixture": False,
                "execution_mode": "genuine-gemini-capacity",
                "execution_kind": "fabricated-offline",
            },
            "analysis": {
                "strategy": "gemini-capacity-v1",
                "dispatch_state": "attempted",
                "accounting_state": "unknown" if blocked else "known",
                "usage_observed": False if blocked else True,
                "evidence_kind": "none" if blocked else "fabricated-offline",
            },
        },
    }


class FixtureServer(HTTPServer):
    """Single-threaded loopback server with finite requests and strict routes."""

    def __init__(self, sources: dict[str, bytes]):
        """Bind one ephemeral loopback port for pinned public sources."""
        self.sources = sources
        self.csp = policy(sources["viewer.html"])
        self.blocked = False
        self.requests = 0
        super().__init__(("127.0.0.1", 0), FixtureHandler)

    def get_request(self):
        """Bound socket reads, including malformed or incomplete HTTP headers."""
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def handle_error(self, request, client_address):
        """Suppress unsanitized server tracebacks."""


class FixtureHandler(BaseHTTPRequestHandler):
    """Serve exact public fixture paths, without cookies or capabilities."""

    def log_message(self, format, *args):
        """Never persist request URLs or headers."""

    def do_GET(self):
        """Reject queries, unexpected hosts, bodies and all unlisted routes."""
        self.server.requests += 1
        expected_host = "127.0.0.1:" + str(self.server.server_port)
        if (
            self.server.requests > 100
            or self.headers.get_all("Host") != [expected_host]
            or self.headers.get("Transfer-Encoding") is not None
            or self.headers.get("Content-Length", "0") != "0"
        ):
            self.send_error(400)
            return
        if self.path == "/health":
            data, mime = MARKER, "text/plain"
        elif self.path == "/gemini-viewer/api/bootstrap":
            data, mime = (
                json.dumps(fixture(self.server.blocked)).encode(),
                "application/json",
            )
        elif self.path == "/viewer":
            data, mime = (
                self.server.sources["viewer.html"],
                "text/html; charset=utf-8",
            )
        elif self.path in ("/viewer.mjs", "/viewer-core.mjs", "/core.mjs"):
            data, mime = (
                self.server.sources[self.path[1:]],
                "text/javascript; charset=utf-8",
            )
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", self.server.csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


def request(port: int, method: str, path: str, payload=None, limit=MAX_BODY):
    """Make bounded loopback-only HTTP; never honor proxies or redirects."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        body = None if payload is None else json.dumps(payload).encode()
        connection.request(
            method, path, body, {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        data = response.read(limit + 1)
        status = response.status
        if type(status) is not int or status != 200:
            raise SmokeFailure(
                "http",
                http_kind="non_200",
                http_status=status,
                webdriver_error=bounded_webdriver_error(data)
                if len(data) <= limit
                else "unavailable",
            )
        if len(data) > limit:
            raise SmokeFailure("http", http_kind="oversize", http_status=status)
        return data
    finally:
        connection.close()


def wait_ready(probe, clock=time.monotonic, sleep=time.sleep):
    """Require a positive owned readiness response before the deadline."""
    deadline = clock() + 10
    while clock() < deadline:
        try:
            if probe():
                return
        except (OSError, http.client.HTTPException, SmokeFailure, ValueError):
            pass
        sleep(0.1)
    raise SmokeFailure("readiness")


class Driver:
    """Small fixed-endpoint W3C WebDriver client, without arbitrary commands."""

    def __init__(self, port: int, transport=request):
        """Use an injected bounded transport at a loopback-only port."""
        self.port = port
        self.transport = transport
        self.session = None

    def call(self, method: str, suffix: str, payload=None):
        """Issue only this harness's fixed protocol operations."""
        allowed = {("GET", "/status"), ("POST", "/session")}
        if self.session:
            prefix = "/session/" + self.session
            allowed |= {
                (m, prefix + p)
                for m, p in (
                    ("DELETE", ""),
                    ("POST", "/url"),
                    ("POST", "/timeouts"),
                    ("POST", "/execute/sync"),
                    ("GET", "/screenshot"),
                )
            }
        if (method, suffix) not in allowed:
            raise SmokeFailure("endpoint")
        try:
            result = json.loads(
                self.transport(self.port, method, suffix, payload)
            )
        except (ValueError, UnicodeError) as error:
            raise SmokeFailure("json") from error
        if not isinstance(result, dict) or "value" not in result:
            raise SmokeFailure("envelope")
        value = result["value"]
        if isinstance(value, dict) and "error" in value:
            raise SmokeFailure("webdriver")
        return value

    def ready(self) -> bool:
        """Return true only for the protocol ready boolean."""
        value = self.call("GET", "/status")
        return isinstance(value, dict) and value.get("ready") is True

    def create(self, chrome: str, profile: Path, width: int):
        """Create a fresh non-touch emulated viewport, preserving sandboxing."""
        options = {
            "binary": chrome,
            "args": [
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-sync",
                "--user-data-dir=" + str(profile),
            ],
            "mobileEmulation": {
                "deviceMetrics": {
                    "width": width,
                    "height": 2400,
                    "pixelRatio": 1,
                    "touch": False,
                    "mobile": False,
                }
            },
        }
        with failure_operation("session_create"):
            value = self.call(
                "POST",
                "/session",
                {
                    "capabilities": {
                        "alwaysMatch": {
                            "browserName": "chrome",
                            "goog:chromeOptions": options,
                        }
                    }
                },
            )
            if not isinstance(value, dict) or not re.fullmatch(
                r"[a-zA-Z0-9-]{1,128}", str(value.get("sessionId", ""))
            ):
                raise SmokeFailure("session")
            self.session = value["sessionId"]
        with failure_operation("session_timeouts"):
            self.command(
                "POST",
                "/timeouts",
                {"implicit": 0, "pageLoad": 10000, "script": 5000},
            )
        with failure_operation("version"):
            capabilities = value.get("capabilities", {})
            if not isinstance(capabilities, dict) or not isinstance(
                capabilities.get("chrome"), dict
            ):
                raise SmokeFailure("version")
            version = capabilities.get("browserVersion", "")
            driver_version = capabilities["chrome"].get(
                "chromedriverVersion", ""
            )
            if not isinstance(version, str) or not isinstance(
                driver_version, str
            ):
                raise SmokeFailure("version")
            driver_version = driver_version.split(" ")[0]
            if not all(
                re.fullmatch(r"[0-9.]{1,40}", v)
                for v in (version, driver_version)
            ):
                raise SmokeFailure("version")
            if version.split(".")[0] != driver_version.split(".")[0]:
                raise SmokeFailure("version")
            return {"chrome": version, "chromedriver": driver_version}

    def command(self, method: str, suffix: str, payload=None):
        """Call a fixed session endpoint only after session creation."""
        if not self.session:
            raise SmokeFailure("session")
        return self.call(method, "/session/" + self.session + suffix, payload)

    def close(self):
        """Attempt protocol cleanup; caller separately owns process cleanup."""
        if self.session:
            try:
                self.command("DELETE", "")
            finally:
                self.session = None


MEASURE = """
const source = document.querySelector('.source-column');
const result = document.querySelector('.readback-column');
const rect = el => {const r = el.getBoundingClientRect();
 return {x:r.x,y:r.y,width:r.width,height:r.height};};
return {loaded:document.getElementById('viewer-status').textContent ===
 'Read-only result loaded. No analysis or payment action is available.',
 width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
 overflow:document.documentElement.scrollWidth > innerWidth,
 source:source ? rect(source):null,result:result ? rect(result):null,
 sourceLabel:source?.querySelector('h2')?.textContent,
 resultLabel:result?.querySelector('h2')?.textContent,
 synthetic:source?.textContent.includes('PUBLIC SYNTHETIC FIXTURE.'),
 actions:document.querySelectorAll('button,input,select,textarea,a,form,[role="button"],[contenteditable]').length,
 results:document.querySelectorAll('.result').length,
 unknown:document.querySelectorAll('.outcome.unknown').length,
 blocked:result?.textContent.includes('No accepted proposal. Blocked or UNKNOWN analysis remains nonactionable.'),
 accountingUnknown:document.body.textContent.includes('Accounting: UNKNOWN.')};
"""


def check_measure(value: dict, width: int, blocked: bool):
    """Check measured viewport/layout and immutable synthetic-state labels."""
    if not isinstance(value, dict) or not (
        value.get("loaded") is True
        and value.get("width") == width
        and value.get("height") == 2400
        and value.get("dpr") == 1
        and value.get("overflow") is False
        and value.get("actions") == 0
        and value.get("synthetic") is True
        and value.get("sourceLabel") == "Approved original source"
        and value.get("resultLabel") == "Retained review · no action authority"
    ):
        raise SmokeFailure("render")
    first, second = value.get("source"), value.get("result")
    if not all(
        isinstance(r, dict)
        and all(
            isinstance(r.get(k), (int, float))
            for k in ("x", "y", "width", "height")
        )
        for r in (first, second)
    ):
        raise SmokeFailure("geometry")
    if not all(r["width"] > 0 and r["height"] > 0 for r in (first, second)):
        raise SmokeFailure("geometry")
    if not all(
        all(math.isfinite(r[k]) for k in ("x", "y", "width", "height"))
        and r["x"] >= 0
        and r["x"] + r["width"] <= width + 1
        for r in (first, second)
    ):
        raise SmokeFailure("viewport-containment")
    if width == 320:
        layout = second["y"] >= first["y"] + first["height"] - 1
    else:
        layout = (
            second["x"] >= first["x"] + first["width"] - 1
            and abs(second["y"] - first["y"]) <= 1
        )
    if not layout:
        raise SmokeFailure("layout")
    if blocked:
        valid = (
            value.get("results") == 0
            and value.get("blocked") is True
            and value.get("accountingUnknown") is True
        )
    else:
        valid = value.get("results") == 2 and value.get("unknown") == 1
    if not valid:
        raise SmokeFailure("state")


def png_bytes(encoded: str, width: int) -> bytes:
    """Reject invalid/oversized PNGs and wrong actual screenshot dimensions."""
    if not isinstance(encoded, str) or len(encoded) > MAX_BODY:
        raise SmokeFailure("png")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise SmokeFailure("png") from error
    if (
        len(data) < 33
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[8:16] != b"\x00\x00\x00\rIHDR"
        or struct.unpack(">II", data[16:24]) != (width, 2400)
        or not data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    ):
        raise SmokeFailure("png")
    offset, kinds, compressed = 8, [], []
    color = data[25]
    if data[24] != 8 or color not in (2, 6) or data[26:29] != b"\x00\x00\x00":
        raise SmokeFailure("png")
    while offset < len(data):
        if offset + 12 > len(data):
            raise SmokeFailure("png")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise SmokeFailure("png")
        kind = data[offset + 4 : offset + 8]
        checksum = struct.unpack(">I", data[end - 4 : end])[0]
        if zlib.crc32(data[offset + 4 : end - 4]) != checksum:
            raise SmokeFailure("png")
        if kind not in {
            b"IHDR",
            b"IDAT",
            b"IEND",
            b"sRGB",
            b"gAMA",
            b"cHRM",
            b"pHYs",
        }:
            raise SmokeFailure("png")
        if kind == b"IDAT":
            compressed.append(data[offset + 8 : end - 4])
        kinds.append(kind)
        offset = end
    if (
        kinds.count(b"IHDR") != 1
        or kinds.count(b"IEND") != 1
        or b"IDAT" not in kinds
    ):
        raise SmokeFailure("png")
    row_bytes = 1 + width * (3 if color == 2 else 4)
    expected_size = row_bytes * 2400
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(b"".join(compressed), expected_size + 1)
    except zlib.error as error:
        raise SmokeFailure("png") from error
    if (
        len(pixels) != expected_size
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or any(pixels[i] > 4 for i in range(0, len(pixels), row_bytes))
    ):
        raise SmokeFailure("png")
    return data


def clean_env(home: Path) -> dict[str, str]:
    """Construct a whitelist, never copy the parent process environment."""
    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def group_exists(pgid: int) -> bool:
    """Check only the owned process group; permission errors fail cleanup."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_process(
    process,
    signal_group=None,
    exists=None,
    clock=time.monotonic,
    sleep=time.sleep,
):
    """Stop the owned new session; forced or uncertain cleanup never passes.

    A process group cannot prove absence of descendants that detached themselves.
    This bounded ownership check is not a universal OS cleanup guarantee.
    """
    if process is None:
        return
    signal_group = signal_group or os.killpg
    exists = exists or group_exists
    pgid = (
        process.pid
    )  # Popen(start_new_session=True) makes PID the owned PGID.
    forced = False

    def send(kind):
        try:
            signal_group(pgid, kind)
        except ProcessLookupError:
            pass

    try:
        process.terminate()
    finally:
        try:
            send(signal.SIGTERM)
        finally:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                forced = True
                try:
                    send(signal.SIGKILL)
                finally:
                    process.kill()
                    process.wait(timeout=3)
    deadline = clock() + 1
    while exists(pgid) and clock() < deadline:
        sleep(0.05)
    if exists(pgid):
        forced = True
        send(signal.SIGKILL)
    if forced:
        raise SmokeFailure("cleanup-forced-or-unknown")


STAGES = frozenset(
    {
        "setup",
        "server_setup",
        "server_readiness",
        "driver_start",
        "driver_readiness",
        "session",
        "navigation",
        "render",
        "measurement",
        "png",
        "write",
        "session_cleanup",
        "process_cleanup",
        "profile_cleanup",
        "server_shutdown",
        "server_close",
        "server_join",
        "temporary_cleanup",
    }
)
SCENARIOS = frozenset(
    {"setup", "review-wide", "review-narrow", "blocked-wide", "blocked-narrow"}
)
CLEANUP_STAGES = frozenset(
    {
        "session_cleanup",
        "process_cleanup",
        "profile_cleanup",
        "server_shutdown",
        "server_close",
        "server_join",
        "temporary_cleanup",
    }
)


def failure_category(error: BaseException) -> str:
    """Classify without reading exception text, args, names or external data."""
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "cancelled"
    if not isinstance(error, Exception):
        return "unexpected_base_exception"
    if isinstance(error, SmokeFailure):
        # Only our exact class may expose its own plain bounded field. Unknown
        # subclasses and mutated values never invoke arbitrary accessors here.
        if type(error) is SmokeFailure:
            code = error.code
            if type(code) is str and code in CHECK_CODES:
                return "check_" + code.replace("-", "_")
        return "check_failed"
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, http.client.HTTPException):
        return "protocol_error"
    if isinstance(error, ValueError):
        return "invalid_data"
    return "unexpected_exception"


class Diagnostics:
    """Collect only finite stage/scenario/category enums in a public receipt."""

    def __init__(self, receipt: dict):
        """Add a versioned diagnostic record with no exception payloads."""
        self.record = {
            "version": 1,
            "last_stage": "setup",
            "scenario": "setup",
            "primary_failure": None,
            "cleanup": [],
        }
        receipt["diagnostics"] = self.record

    def emit_failure(
        self,
        receipt: dict,
        receipt_write_failed: bool = False,
        invalidation_failed: bool = False,
    ):
        """Print one closed-value summary without requiring artifact access."""
        primary = self.record["primary_failure"] or {}
        categories = {
            "check_failed",
            "timeout",
            "io_error",
            "protocol_error",
            "invalid_data",
            "unexpected_exception",
            "unexpected_base_exception",
            "cancelled",
        }
        categories |= {
            "check_" + code.replace("-", "_") for code in CHECK_CODES
        }
        stage = primary.get("stage")
        scenario = primary.get("scenario")
        category = primary.get("category")
        summary = {
            "primary_stage": stage
            if type(stage) is str and stage in STAGES
            else "unavailable",
            "primary_category": category
            if type(category) is str and category in categories
            else "unavailable",
            "scenario": scenario
            if type(scenario) is str and scenario in SCENARIOS
            else "setup",
            "failed_cleanup_stages": sorted(
                {
                    item["stage"]
                    for item in self.record["cleanup"]
                    if item.get("status") == "failed"
                    and type(item.get("stage")) is str
                    and item["stage"] in CLEANUP_STAGES
                }
            ),
            "saved_png_count": min(4, max(0, len(receipt["checks"]))),
            "receipt_write": "failed" if receipt_write_failed else "not_failed",
            "receipt_invalidation": "failed"
            if invalidation_failed
            else "not_failed",
        }
        summary.update(
            safe_failure_metadata(
                primary.get("operation"),
                primary.get("http_kind"),
                primary.get("http_status"),
                primary.get("webdriver_error"),
            )
        )
        print(
            "PUBLIC_FIXTURE_FAILURE_SUMMARY "
            + json.dumps(summary, sort_keys=True)
        )

    @contextmanager
    def stage(self, stage: str, scenario: str = "setup"):
        """Record failure before later cleanup can replace its exception."""
        if stage not in STAGES or scenario not in SCENARIOS:
            raise SmokeFailure("diagnostic-enum")
        self.record["last_stage"] = stage
        self.record["scenario"] = scenario
        result = {"stage": stage, "scenario": scenario, "status": "passed"}
        try:
            yield
        except BaseException as error:
            result["status"] = "failed"
            result["category"] = failure_category(error)
            if type(error) is SmokeFailure:
                result.update(
                    safe_failure_metadata(
                        error.operation,
                        error.http_kind,
                        error.http_status,
                        error.webdriver_error,
                    )
                )
            if (
                stage not in CLEANUP_STAGES
                and self.record["primary_failure"] is None
            ):
                self.record["primary_failure"] = dict(result)
            raise
        finally:
            if stage in CLEANUP_STAGES:
                self.record["cleanup"].append(result)


def write_receipt_temp(path: Path, data: str):
    """Write and close an exclusively owned staging file outside artifact paths."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data)


def publish_receipt(output: Path, receipt: dict, diagnostics: Diagnostics):
    """Publish atomically; standalone receipts never certify overall success.

    Filesystem operations can fail after taking effect. A residual receipt from
    ambiguous publication remains pending, and must be paired with job success.
    """
    target = output / "receipt.json"
    temporary = output.parent / ("." + output.name + ".receipt.tmp")
    pending = dict(receipt)
    pending["job_conclusion_required"] = True
    pending["checks_status"] = (
        "passed" if receipt["status"] == "passed" else "not_confirmed"
    )
    if pending["status"] == "passed":
        pending["status"] = "pending_job_conclusion"
    try:
        write_receipt_temp(temporary, json.dumps(pending, indent=2) + "\n")
        temporary.replace(target)
    except BaseException:
        receipt["status"] = "failed"
        invalidation_failed = False
        for path in (target, temporary):
            try:
                path.unlink(missing_ok=True)
            except BaseException:
                invalidation_failed = True
        diagnostics.emit_failure(
            receipt,
            receipt_write_failed=True,
            invalidation_failed=invalidation_failed,
        )
        raise
    else:
        if receipt["status"] != "passed":
            diagnostics.emit_failure(receipt)


def run(
    sources: dict[str, bytes],
    output: Path,
    chrome: str,
    driver_binary: str,
    spawn=subprocess.Popen,
    driver_factory=Driver,
    server_factory=FixtureServer,
    provenance=None,
    cleanup=stop_process,
):
    """Own lifecycle and preserve sanitized primary/cleanup failures separately."""
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "scope": "public-synthetic-render-only",
        "status": "failed",
        "source_revision": SOURCE_REVISION,
        "sources": SOURCE_HASHES,
        "viewport_kind": "non-touch deviceMetrics emulation",
        "checks": [],
        "provenance": provenance or {"kind": "injected-offline-test"},
    }
    diagnostics = Diagnostics(receipt)
    temporary = None
    try:
        with diagnostics.stage("setup"):
            temporary = tempfile.TemporaryDirectory(prefix="public-fixture-")
            home = Path(temporary.name)
        try:
            with diagnostics.stage("server_setup"):
                server = server_factory(sources)
            started = False
            try:
                with diagnostics.stage("server_setup"):
                    thread = threading.Thread(
                        target=server.serve_forever, daemon=True
                    )
                    thread.start()
                    started = True
                with diagnostics.stage("server_readiness"):
                    wait_ready(
                        lambda: request(
                            server.server_port, "GET", "/health", limit=128
                        )
                        == MARKER
                    )
                for blocked in (False, True):
                    server.blocked = blocked
                    for width, size in ((1200, "wide"), (320, "narrow")):
                        scenario = (
                            ("blocked" if blocked else "review") + "-" + size
                        )
                        process, driver = None, None
                        profile = home / (str(blocked) + size)
                        try:
                            with diagnostics.stage("driver_start", scenario):
                                with socket.socket() as reservation:
                                    reservation.bind(("127.0.0.1", 0))
                                    port = reservation.getsockname()[1]
                                driver = driver_factory(port)
                                process = spawn(
                                    [driver_binary, "--port=" + str(port)],
                                    start_new_session=True,
                                    env=clean_env(home),
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                            with diagnostics.stage(
                                "driver_readiness", scenario
                            ):
                                wait_ready(driver.ready)
                            with diagnostics.stage("session", scenario):
                                versions = driver.create(chrome, profile, width)
                            with diagnostics.stage("navigation", scenario):
                                driver.command(
                                    "POST",
                                    "/url",
                                    {
                                        "url": "http://127.0.0.1:"
                                        + str(server.server_port)
                                        + "/viewer"
                                    },
                                )
                            observed = None

                            def rendered():
                                nonlocal observed
                                observed = driver.command(
                                    "POST",
                                    "/execute/sync",
                                    {"script": MEASURE, "args": []},
                                )
                                return (
                                    isinstance(observed, dict)
                                    and observed.get("loaded") is True
                                )

                            with diagnostics.stage("render", scenario):
                                wait_ready(rendered)
                            with diagnostics.stage("measurement", scenario):
                                check_measure(observed, width, blocked)
                            with diagnostics.stage("png", scenario):
                                png = png_bytes(
                                    driver.command("GET", "/screenshot"), width
                                )
                            with diagnostics.stage("write", scenario):
                                (output / (scenario + ".png")).write_bytes(png)
                                receipt["checks"].append(
                                    {
                                        "scenario": scenario,
                                        "width": width,
                                        "height": 2400,
                                        "status": "passed",
                                        "runtime": versions,
                                        "png_sha256": hashlib.sha256(
                                            png
                                        ).hexdigest(),
                                    }
                                )
                        finally:
                            try:
                                if driver is not None:
                                    with diagnostics.stage(
                                        "session_cleanup", scenario
                                    ):
                                        driver.close()
                            finally:
                                try:
                                    with diagnostics.stage(
                                        "process_cleanup", scenario
                                    ):
                                        cleanup(process)
                                finally:
                                    with diagnostics.stage(
                                        "profile_cleanup", scenario
                                    ):
                                        if profile.exists():
                                            shutil.rmtree(profile)
            finally:
                try:
                    if started:
                        with diagnostics.stage("server_shutdown"):
                            server.shutdown()
                finally:
                    try:
                        with diagnostics.stage("server_close"):
                            server.server_close()
                    finally:
                        if started:
                            with diagnostics.stage("server_join"):
                                thread.join(timeout=3)
                                if thread.is_alive():
                                    raise SmokeFailure("server-cleanup")
        finally:
            if temporary is not None:
                with diagnostics.stage("temporary_cleanup"):
                    temporary.cleanup()
        receipt["status"] = "passed"
    finally:
        publish_receipt(output, receipt, diagnostics)


def main() -> int:
    """Run only on the intended hosted-job environment; never print raw errors."""
    try:
        if os.environ.get("FIXTURE_HOSTED_RUN") != "1":
            raise SmokeFailure("hosted-only")
        sources = checked_sources(Path("ui"))
        chrome = "/usr/bin/google-chrome"
        driver = "/usr/local/share/chromedriver-linux64/chromedriver"
        if not all(
            Path(p).is_file() and os.access(p, os.X_OK)
            for p in (chrome, driver)
        ):
            raise SmokeFailure("binary")
        workflow_sha = os.environ.get("FIXTURE_WORKFLOW_SHA", "")
        image = os.environ.get("FIXTURE_IMAGE_VERSION", "")
        if not re.fullmatch(r"[a-f0-9]{40}", workflow_sha) or not re.fullmatch(
            r"[0-9.]{1,40}", image
        ):
            raise SmokeFailure("provenance")
        run(
            sources,
            Path("artifacts"),
            chrome,
            driver,
            provenance={"workflow_sha": workflow_sha, "runner_image": image},
        )
        print(
            "PUBLIC_FIXTURE_RENDER_CHECKS_PASSED; manual PNG inspection pending"
        )
        return 0
    except BaseException:
        print(
            "PUBLIC_FIXTURE_RENDER_CHECKS_FAILED; sanitized receipt if initialized"
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    raise SystemExit(main())
