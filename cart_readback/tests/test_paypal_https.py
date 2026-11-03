"""Synthetic credential/fake HTTPS probes; no PayPal call or socket is allowed."""

import http.client
import io
import json
import os
import sqlite3
import ssl
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cartreadback_app.payments import PaymentRequest, ProviderAmbiguity
from cartreadback_app.paypal_https import (
    HOST,
    OAUTH_BODY,
    OAUTH_PATH,
    PORT,
    DirectSandboxConnectionFactory,
    HttpsPolicy,
    SandboxClientCredentials,
    SandboxHttpsTransport,
)
from cartreadback_app.paypal_sandbox import (
    ORDER_PATH,
    SANDBOX_ENDPOINT,
    OfflinePayPalSandboxAdapter,
    SandboxWireResponse,
)
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical
from test_domain import Workflow
from test_paypal_sandbox import CAPTURE_ID, MERCHANT, PROVIDER_ID, expectation

SYNTHETIC_CLIENT = "synthetic-client-not-a-credential"
SYNTHETIC_SECRET = "synthetic-secret-not-a-credential"
SYNTHETIC_TOKEN = "synthetic-token-not-a-credential"
RAW_ERROR = "SYNTHETIC_PRIVATE_ERROR_MUST_NOT_ESCAPE"


def credentials():
    return SandboxClientCredentials(SYNTHETIC_CLIENT, SYNTHETIC_SECRET)


def json_response(document, status=200, **kwargs):
    return FakeResponse(canonical(document).encode(), status, **kwargs)


def token_response(**changes):
    return json_response(
        {
            "access_token": SYNTHETIC_TOKEN,
            "token_type": "Bearer",
            "expires_in": 60,
            "scope": "synthetic-scope-not-permission",
            **changes,
        }
    )


class FakeResponse:
    def __init__(self, body=b"{}", status=200, headers=None, chunk=4096):
        self.body = body
        self.status = status
        self.headers = (
            headers
            if headers is not None
            else [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
        )
        self.chunk = chunk
        self.offset = 0
        self.closed = False
        self.error = None

    def isclosed(self):
        return self.closed

    def getheaders(self):
        if self.error == "headers":
            raise RuntimeError(RAW_ERROR)
        return self.headers

    def read(self, size):
        if self.error == "read":
            raise RuntimeError(RAW_ERROR)
        n = min(size, self.chunk)
        result = self.body[self.offset : self.offset + n]
        self.offset += len(result)
        return result

    def close(self):
        self.closed = True
        if self.error == "close":
            raise RuntimeError(RAW_ERROR)


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeConnection:
    def __init__(self, factory):
        self.factory = factory
        self.sock = FakeSocket()
        self.closed = False
        self.debug = None
        self.requested = None
        self.connected = False
        self.response = None

    def set_debuglevel(self, level):
        self.debug = level

    def connect(self):
        self.connected = True
        if self.factory.barrier:
            entered, release = self.factory.barrier
            entered.set()
            release.wait(5)
        if self.factory.error == "connect":
            raise RuntimeError(RAW_ERROR)

    def request(self, method, path, *, body, headers, encode_chunked):
        if self.factory.path:
            connection = sqlite3.connect(self.factory.path, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
        self.requested = (method, path, body, deepcopy(headers), encode_chunked)
        self.factory.calls.append(self.requested)
        if self.factory.error == "request":
            raise RuntimeError(RAW_ERROR)

    def getresponse(self):
        if self.factory.error == "getresponse":
            raise RuntimeError(RAW_ERROR)
        result = self.factory.reply(self.requested)
        if isinstance(result, Exception):
            raise result
        self.response = result
        return result

    def close(self):
        self.closed = True
        self.factory.closed_signal.set()
        if self.factory.error == "close":
            raise RuntimeError(RAW_ERROR)


class FakeFactory:
    def __init__(self, responses=None, path=None):
        self.responses = list(responses or [token_response(), FakeResponse()])
        self.instances = []
        self.calls = []
        self.arguments = []
        self.error = None
        self.barrier = None
        self.path = path
        self.callback = None
        self.closed_signal = threading.Event()

    def __call__(self, host, port, *, timeout, context):
        self.arguments.append((host, port, timeout, context))
        if self.error == "factory":
            raise RuntimeError(RAW_ERROR)
        connection = FakeConnection(self)
        self.instances.append(connection)
        return connection

    def reply(self, request):
        return (
            self.callback(request) if self.callback else self.responses.pop(0)
        )


class SyntheticOrders:
    def __init__(self):
        self.document = {}
        self.oauth_status = 200
        self.fail_capture_after_effect = False

    def __call__(self, request):
        method, route, body, _headers, _chunked = request
        if route == OAUTH_PATH:
            if self.oauth_status != 200:
                return json_response({"error": RAW_ERROR}, self.oauth_status)
            return token_response()
        if route == ORDER_PATH:
            self.document.update(
                json.loads(body), id=PROVIDER_ID, status="CREATED"
            )
        elif method == "POST":
            self.document["status"] = "COMPLETED"
            self.document["purchase_units"][0]["payments"] = {
                "captures": [
                    {
                        "id": CAPTURE_ID,
                        "status": "COMPLETED",
                        "amount": {"currency_code": "USD", "value": "79.00"},
                        "final_capture": True,
                    }
                ]
            }
            if self.fail_capture_after_effect:
                raise TimeoutError(RAW_ERROR)
        return json_response(self.document, 200 if method == "GET" else 201)


class FramedSocket:
    def __init__(self, raw):
        self.stream = io.BytesIO(raw)
        self.timeouts = []
        self.closed = False

    def makefile(self, *_args):
        return self.stream

    def settimeout(self, value):
        if self.closed and self.stream.closed:
            raise OSError(
                9, "Synthetic descriptor closed after final file reference"
            )
        self.timeouts.append(value)

    def sendall(self, _data):
        pass

    def close(self):
        self.closed = True


class StdlibFramingFactory:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sockets = []

    def __call__(self, host, port, *, timeout, context):
        raw = FramedSocket(self.replies.pop(0))
        self.sockets.append(raw)
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.connect = lambda: setattr(connection, "sock", raw)
        return connection


def framed(body, closing=False):
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + (b"\r\nConnection: close" if closing else b"")
        + b"\r\n\r\n"
        + body
    )


class OfflineBridge:
    """Test-only adapter bridge; the captured factory only creates fake sockets."""

    requires_live_authorization = False

    def __init__(self, core):
        self.core = core

    def send(self, *args, **kwargs):
        return self.core.send(*args, **kwargs)


class _HttpsCase(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.proxy = patch(
            "cartreadback_app.paypal_https.getproxies", return_value={}
        )
        self.proxy.start()
        self.addCleanup(self.proxy.stop)
        socket_patch = patch(
            "socket.create_connection",
            side_effect=AssertionError("No real sockets in offline tests"),
        )
        self.sockets = socket_patch.start()
        self.addCleanup(socket_patch.stop)
        self.request = PaymentRequest("POST", ORDER_PATH, "{}")
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "PayPal-Request-Id": str(uuid4()),
        }

    def core(
        self, factory, source=credentials, reference="synthetic/test-only"
    ):
        return SandboxHttpsTransport(source, factory, reference)

    def send(self, core, request=None, headers=None, timeout=2):
        return core.send(
            SANDBOX_ENDPOINT,
            request or self.request,
            headers or self.headers,
            timeout_seconds=timeout,
        )

    def assert_closed(self, factory):
        for connection in factory.instances:
            self.assertTrue(connection.closed)
            if connection.response:
                self.assertTrue(connection.response.closed)


class HttpsTests(_HttpsCase):
    def test_default_has_no_source_or_factory_and_cannot_connect(self):
        with self.assertRaises(ProviderAmbiguity):
            self.send(SandboxHttpsTransport())
        self.sockets.assert_not_called()

    def test_exact_oauth_and_order_bytes_headers_host_tls_and_no_cache(self):
        factory = FakeFactory(
            [token_response(), FakeResponse(), token_response(), FakeResponse()]
        )
        core = self.core(factory)
        for _ in range(2):
            result = self.send(core)
            self.assertEqual((200, b"{}"), (result.status_code, result.body))
        self.assertEqual(4, len(factory.calls))
        method, path, body, headers, chunked = factory.calls[0]
        self.assertEqual(
            ("POST", OAUTH_PATH, OAUTH_BODY, False),
            (method, path, body, chunked),
        )
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertEqual(
            "application/x-www-form-urlencoded", headers["Content-Type"]
        )
        self.assertNotIn("PayPal-Request-Id", headers)
        sent = factory.calls[1]
        self.assertEqual(("POST", ORDER_PATH, b"{}"), sent[:3])
        self.assertEqual(
            self.headers["PayPal-Request-Id"], sent[3]["PayPal-Request-Id"]
        )
        self.assertEqual("Bearer " + SYNTHETIC_TOKEN, sent[3]["Authorization"])
        for _, _, _, sent_headers, chunked in factory.calls:
            self.assertEqual(HOST, sent_headers["Host"])
            self.assertEqual("close", sent_headers["Connection"])
            self.assertEqual("identity", sent_headers["Accept-Encoding"])
            self.assertFalse(chunked)
        for host, port, timeout, context in factory.arguments:
            self.assertEqual((HOST, PORT), (host, port))
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 2)
            self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
            self.assertTrue(context.check_hostname)
            self.assertGreaterEqual(
                context.minimum_version, ssl.TLSVersion.TLSv1_2
            )
        self.assertTrue(all(c.debug == 0 for c in factory.instances))
        self.assert_closed(factory)
        self.sockets.assert_not_called()

    def test_get_and_capture_never_change_method_path_or_uuid(self):
        for request, headers in [
            (
                PaymentRequest("GET", ORDER_PATH + "/" + PROVIDER_ID, ""),
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            (
                PaymentRequest(
                    "POST", ORDER_PATH + "/" + PROVIDER_ID + "/capture", "{}"
                ),
                self.headers,
            ),
        ]:
            factory = FakeFactory()
            self.send(self.core(factory), request, headers)
            sent = factory.calls[-1]
            self.assertEqual(
                (request.method, request.path, request.body.encode()), sent[:3]
            )
            self.assertEqual(
                headers.get("PayPal-Request-Id"),
                sent[3].get("PayPal-Request-Id"),
            )

    def test_proxy_and_trust_environment_refusal_precedes_credentials(self):
        for name in [
            "HTTP_PROXY",
            "https_proxy",
            "HtTpS_PrOxY",
            "NO_PROXY",
            "ALL_PROXY",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        ]:
            with (
                self.subTest(name=name),
                patch.dict(os.environ, {name: "synthetic-private-config"}),
            ):
                factory = FakeFactory()
                calls = []
                core = self.core(factory, lambda: calls.append(1))
                with self.assertRaises(ProviderAmbiguity) as caught:
                    self.send(core)
                self.assertEqual([], calls)
                self.assertEqual([], factory.instances)
                self.assertNotIn("private", str(caught.exception))

    def test_discovered_proxy_or_discovery_failure_precedes_credentials(self):
        for value in [{"https": "synthetic-private-proxy"}, None]:
            with (
                self.subTest(value=type(value)),
                patch(
                    "cartreadback_app.paypal_https.getproxies",
                    return_value=value,
                ),
            ):
                factory = FakeFactory()
                with self.assertRaises(ProviderAmbiguity):
                    self.send(
                        self.core(
                            factory,
                            lambda: self.fail("Credentials must not load"),
                        )
                    )
                self.assertEqual([], factory.instances)
        with patch(
            "cartreadback_app.paypal_https.getproxies",
            side_effect=RuntimeError(RAW_ERROR),
        ):
            with self.assertRaises(ProviderAmbiguity) as caught:
                self.send(self.core(FakeFactory()))
            self.assertNotIn(RAW_ERROR, str(caught.exception))

    def test_bad_endpoint_route_headers_body_or_identity_never_loads_credentials(
        self,
    ):
        bad_requests = [
            PaymentRequest(
                "POST", "https://api-m.paypal.com/v2/checkout/orders", "{}"
            ),
            PaymentRequest("POST", ORDER_PATH + "/A/capture?x=1", "{}"),
            PaymentRequest("GET", ORDER_PATH + "/../X", ""),
            PaymentRequest("POST", ORDER_PATH, '{"a":1,"a":2}'),
            PaymentRequest("POST", ORDER_PATH, "x" * 65537),
        ]
        for request in bad_requests:
            factory = FakeFactory()
            with (
                self.subTest(path=request.path),
                self.assertRaises(ProviderAmbiguity),
            ):
                self.send(
                    self.core(
                        factory, lambda: self.fail("No credential access")
                    ),
                    request,
                )
            self.assertEqual([], factory.instances)
        for key, value in [
            ("Authorization", "injected"),
            ("Host", "evil.test"),
            ("Prefer", "return=minimal"),
            ("PayPal-Request-Id", "bad\r\nheader"),
        ]:
            headers = {**self.headers, key: value}
            factory = FakeFactory()
            with self.subTest(key=key), self.assertRaises(ProviderAmbiguity):
                self.send(self.core(factory), headers=headers)
            self.assertEqual([], factory.instances)
        factory = FakeFactory()
        with self.assertRaises(ProviderAmbiguity):
            self.core(factory).send(
                "https://api-m.paypal.com",
                self.request,
                self.headers,
                timeout_seconds=2,
            )
        self.assertEqual([], factory.instances)

    def test_oauth_failures_never_send_orders_or_retry(self):
        responses = [
            token_response(access_token=""),
            token_response(token_type="Basic"),
            token_response(expires_in=True),
            token_response(expires_in=0),
            token_response(expires_in=1),
            token_response(expires_in=86401),
            token_response(access_token="bad\r\nheader"),
            token_response(scope=""),
            FakeResponse(b'{"access_token":"A","access_token":"B"}'),
            FakeResponse(b'{"x":NaN}'),
            FakeResponse(b"\xff"),
            FakeResponse(b"{}", 401),
            FakeResponse(b"{}", 302),
        ]
        for reply in responses:
            factory = FakeFactory([reply])
            core = self.core(factory)
            with (
                self.subTest(reply=repr(reply)),
                self.assertRaises(ProviderAmbiguity),
            ):
                self.send(core)
            self.assertEqual(1, len(factory.calls))
            self.assertEqual(OAUTH_PATH, factory.calls[0][1])
            with self.assertRaises(ProviderAmbiguity):
                self.send(core)
            self.assertEqual(1, len(factory.calls))
            self.assert_closed(factory)

    def test_oauth_type_is_case_insensitive_without_scope_as_authority(self):
        factory = FakeFactory(
            [
                token_response(
                    token_type="bEaReR", scope="arbitrary-synthetic-scope"
                ),
                FakeResponse(),
            ]
        )
        self.send(self.core(factory))
        self.assertEqual(2, len(factory.calls))

    def test_response_framing_compression_size_and_type_fail_closed(self):
        cases = [
            [("Content-Type", "application/json")],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("content-length", "2"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Transfer-Encoding", "chunked"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Content-Encoding", "gzip"),
            ],
            [("Content-Type", "text/html"), ("Content-Length", "2")],
            [("Content-Type", "appli cation/json"), ("Content-Length", "2")],
            [
                ("Content-Type", "application/json;charset=latin1"),
                ("Content-Length", "2"),
            ],
            [("Content-Type", "application/json"), ("Content-Length", "02")],
            [("Content-Type", "application/json"), ("Content-Length", "65537")],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("X-Large", "x" * 4097),
            ],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("X-Bad", "bad\r\nvalue"),
            ],
        ]
        for headers in cases:
            reply = FakeResponse(headers=headers)
            factory = FakeFactory([token_response(), reply])
            with (
                self.subTest(headers=[n for n, _ in headers]),
                self.assertRaises(ProviderAmbiguity),
            ):
                self.send(self.core(factory))
            self.assertEqual(2, len(factory.calls))
            self.assert_closed(factory)

    def test_short_extra_and_header_count_body_reads_are_bounded(self):
        for reply in [
            FakeResponse(
                b"{}",
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", "3"),
                ],
            ),
            FakeResponse(
                b"{}x",
                headers=[
                    ("Content-Type", "application/json"),
                    ("Content-Length", "2"),
                ],
            ),
            FakeResponse(headers=[("X-" + str(i), "x") for i in range(33)]),
        ]:
            factory = FakeFactory([token_response(), reply])
            with self.assertRaises(ProviderAmbiguity):
                self.send(self.core(factory))
            self.assert_closed(factory)
        factory = FakeFactory([token_response(), FakeResponse(b"{}", chunk=1)])
        self.assertEqual(b"{}", self.send(self.core(factory)).body)

    def test_401_and_5xx_are_not_refreshed_or_replayed_and_redirect_is_refused(
        self,
    ):
        for status in [401, 403, 429, 500, 503]:
            factory = FakeFactory(
                [token_response(), FakeResponse(status=status)]
            )
            self.assertEqual(status, self.send(self.core(factory)).status_code)
            self.assertEqual(2, len(factory.calls))
            self.assert_closed(factory)
        factory = FakeFactory([token_response(), FakeResponse(status=307)])
        with self.assertRaises(ProviderAmbiguity):
            self.send(self.core(factory))
        self.assertEqual(2, len(factory.calls))

    def test_failures_close_resources_and_never_expose_raw_error_or_credentials(
        self,
    ):
        for stage in ["factory", "connect", "request", "getresponse", "close"]:
            factory = FakeFactory()
            factory.error = stage
            core = self.core(factory)
            with (
                self.subTest(stage=stage),
                self.assertRaises(ProviderAmbiguity) as caught,
            ):
                self.send(core)
            self.assertNotIn(RAW_ERROR, str(caught.exception))
            self.assert_closed(factory)
            for value in [
                repr(core),
                repr(credentials()),
                str(caught.exception),
            ]:
                self.assertNotIn(SYNTHETIC_SECRET, value)
                self.assertNotIn(SYNTHETIC_CLIENT, value)
                self.assertNotIn(SYNTHETIC_TOKEN, value)
        self.assertNotIn(
            SYNTHETIC_TOKEN,
            repr(SandboxWireResponse(200, SYNTHETIC_TOKEN.encode())),
        )

    def test_header_body_and_response_close_errors_are_sanitized(self):
        for error in ["headers", "read", "close"]:
            reply = FakeResponse()
            reply.error = error
            factory = FakeFactory([token_response(), reply])
            with (
                self.subTest(error=error),
                self.assertRaises(ProviderAmbiguity) as caught,
            ):
                self.send(self.core(factory))
            self.assertNotIn(RAW_ERROR, str(caught.exception))
            self.assert_closed(factory)

    def test_timeout_and_overlap_poison_instance_and_never_reuse_late_result(
        self,
    ):
        factory = FakeFactory()
        entered, release = threading.Event(), threading.Event()
        factory.barrier = (entered, release)
        core = self.core(factory)
        try:
            with self.assertRaises(ProviderAmbiguity):
                self.send(core, timeout=0.03)
            self.assertTrue(entered.is_set())
            with self.assertRaises(ProviderAmbiguity):
                self.send(core)
            self.assertEqual(1, len(factory.instances))
        finally:
            release.set()
            self.assertTrue(factory.closed_signal.wait(1))
        self.sockets.assert_not_called()

    def test_stdlib_connection_close_keeps_body_socket_deadlines_without_reconnect(
        self,
    ):
        for oauth_close, order_close in [
            (False, False),
            (True, False),
            (False, True),
            (True, True),
        ]:
            with self.subTest(oauth_close=oauth_close, order_close=order_close):
                factory = StdlibFramingFactory(
                    [
                        framed(token_response().body, oauth_close),
                        framed(b"{}", order_close),
                    ]
                )
                self.assertEqual(b"{}", self.send(self.core(factory)).body)
                self.assertEqual(2, len(factory.sockets))
                self.assertTrue(all(sock.closed for sock in factory.sockets))
                self.assertTrue(
                    all(len(sock.timeouts) >= 3 for sock in factory.sockets)
                )
        self.sockets.assert_not_called()

    def test_stdlib_framing_hides_trailing_bytes_and_connection_is_never_reused(
        self,
    ):
        factory = StdlibFramingFactory(
            [
                framed(token_response().body),
                framed(b"{}") + b"UNOBSERVABLE_TRAILING_BYTES",
            ]
        )
        self.assertEqual(b"{}", self.send(self.core(factory)).body)
        self.assertEqual(2, len(factory.sockets))
        self.assertTrue(all(sock.closed for sock in factory.sockets))

    def test_overlapping_call_cannot_create_a_second_worker_or_token_request(
        self,
    ):
        factory = FakeFactory()
        entered, release = threading.Event(), threading.Event()
        factory.barrier = (entered, release)
        core = self.core(factory)
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(self.send, core)
            self.assertTrue(entered.wait(1))
            try:
                with self.assertRaises(ProviderAmbiguity):
                    self.send(core)
                self.assertEqual(1, len(factory.instances))
            finally:
                release.set()
            self.assertEqual(b"{}", pending.result().body)
        self.assertEqual(2, len(factory.calls))
        self.assert_closed(factory)

    def test_oauth_and_order_share_deadline_and_token_response_limit(self):
        factory = FakeFactory([token_response(), FakeResponse()])
        self.send(self.core(factory), timeout=0.5)
        self.assertTrue(
            all(0 < timeout <= 0.5 for _, _, timeout, _ in factory.arguments)
        )
        large = FakeResponse(b"x" * 8193)
        factory = FakeFactory([large])
        with self.assertRaises(ProviderAmbiguity):
            self.send(self.core(factory))
        self.assertEqual(1, len(factory.calls))
        self.assertEqual(0, large.offset)
        self.assert_closed(factory)

    def test_worker_start_failure_is_sanitized_and_never_loads_credentials(
        self,
    ):
        factory = FakeFactory()
        with patch(
            "cartreadback_app.paypal_https.threading.Thread.start",
            side_effect=RuntimeError(RAW_ERROR),
        ):
            with self.assertRaises(ProviderAmbiguity) as caught:
                self.send(self.core(factory))
        self.assertNotIn(RAW_ERROR, str(caught.exception))
        self.assertEqual([], factory.instances)

    def test_direct_factory_checks_target_and_tls_without_opening_a_socket(
        self,
    ):
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        factory = DirectSandboxConnectionFactory()
        with patch(
            "cartreadback_app.paypal_https.http.client.HTTPSConnection"
        ) as constructor:
            connection = factory(HOST, 443, timeout=1, context=context)
            constructor.assert_called_once_with(
                HOST, 443, timeout=1, context=context
            )
            connection.set_debuglevel.assert_called_once_with(0)
            connection.connect.assert_not_called()
        for host, port in [
            ("api-m.paypal.com", 443),
            (HOST, 80),
            (HOST + ".evil.test", 443),
        ]:
            with self.assertRaises(ProviderAmbiguity):
                factory(host, port, timeout=1, context=context)
        unsafe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        unsafe.check_hostname = False
        unsafe.verify_mode = ssl.CERT_NONE
        with self.assertRaises(ProviderAmbiguity):
            factory(HOST, 443, timeout=1, context=unsafe)
        self.sockets.assert_not_called()

    def test_network_marked_core_is_not_an_offline_adapter_or_runtime_selection(
        self,
    ):
        factory = FakeFactory(
            [
                token_response(),
                json_response({"id": PROVIDER_ID, "status": "CREATED"}),
            ]
        )
        core = self.core(factory)
        with self.assertRaises(AppError):
            OfflinePayPalSandboxAdapter(core, MERCHANT)
        with self.assertRaises(AppError):
            OfflinePayPalSandboxAdapter(
                type(
                    "BadMarker", (), {"requires_live_authorization": "false"}
                )(),
                MERCHANT,
            )
        adapter = OfflinePayPalSandboxAdapter(OfflineBridge(core), MERCHANT)
        result = adapter.dispatch(
            str(uuid4()), adapter.prepare("orders", expectation(), None)
        )
        self.assertEqual(PROVIDER_ID, result["provider_order_id"])
        self.assertEqual("CREATED", result["status"])
        self.assertNotIn("merchant_id", result)

    def test_configuration_and_credential_validation_excludes_secrets(self):
        for timeout in [True, 0, -1, 31, float("nan"), float("inf")]:
            with (
                self.subTest(timeout=timeout),
                self.assertRaises(ProviderAmbiguity),
            ):
                HttpsPolicy(timeout, 1)
        for client, secret in [
            ("bad:client", "ok"),
            ("ok", "bad\r\nsecret"),
            ("", "ok"),
            ("ok", "x" * 257),
        ]:
            with self.assertRaises(ProviderAmbiguity):
                SandboxClientCredentials(client, secret)
        factory = FakeFactory()
        a, b = (
            self.core(factory),
            self.core(factory, reference="synthetic/other"),
        )
        self.assertNotEqual(a.configuration_sha256, b.configuration_sha256)
        self.assertNotIn(SYNTHETIC_SECRET, repr(a))


class HttpsLifecycleTests(_HttpsCase):
    def test_fake_https_oauth_through_adapter_preserves_durable_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            store = Store(path)
            factory = FakeFactory(path=path)
            provider = SyntheticOrders()
            factory.callback = provider
            adapter = OfflinePayPalSandboxAdapter(
                OfflineBridge(self.core(factory)), MERCHANT
            )
            service = Service(store, payments=adapter)
            try:
                flow = Workflow(service)
                flow.analyze()
                flow.confirm()
                flow.create()
                self.assertEqual("ORDER_CREATED", flow.checkout["state"])
                provider.document["status"] = "APPROVED"
                flow.action("verify")
                flow.action("capture")
                self.assertEqual("COMPLETED", flow.checkout["state"])
                self.assertEqual(
                    4, sum(c[1] == OAUTH_PATH for c in factory.calls)
                )
                self.assertEqual(
                    2,
                    sum(
                        c[0] == "POST" and c[1] != OAUTH_PATH
                        for c in factory.calls
                    ),
                )
                with store.connect() as connection:
                    ledger = canonical(
                        [
                            dict(row)
                            for row in connection.execute(
                                "SELECT * FROM operations"
                            )
                        ]
                    )
                for marker in [
                    SYNTHETIC_CLIENT,
                    SYNTHETIC_SECRET,
                    SYNTHETIC_TOKEN,
                ]:
                    self.assertNotIn(marker, ledger)
            finally:
                service.close()
            self.assert_closed(factory)
            self.sockets.assert_not_called()

    def test_oauth_failure_keeps_create_unknown_without_order_post_or_replay(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "app.sqlite3")
            factory = FakeFactory(path=store.path)
            provider = SyntheticOrders()
            provider.oauth_status = 401
            factory.callback = provider
            service = Service(
                store,
                payments=OfflinePayPalSandboxAdapter(
                    OfflineBridge(self.core(factory)), MERCHANT
                ),
            )
            try:
                flow = Workflow(service)
                flow.analyze()
                flow.confirm()
                flow.create()
                self.assertEqual("PAYMENT_UNKNOWN", flow.checkout["state"])
                self.assertIsNone(flow.checkout["order"]["provider_order_id"])
                flow.action("reconcile")
                self.assertEqual(
                    [OAUTH_PATH], [call[1] for call in factory.calls]
                )
                with store.connect() as connection:
                    rows = canonical(
                        [
                            dict(row)
                            for row in connection.execute(
                                "SELECT * FROM operations"
                            )
                        ]
                    )
                for marker in [
                    SYNTHETIC_CLIENT,
                    SYNTHETIC_SECRET,
                    SYNTHETIC_TOKEN,
                    RAW_ERROR,
                ]:
                    self.assertNotIn(marker, rows)
            finally:
                service.close()

    def test_fake_capture_loss_reconciles_same_order_without_capture_replay(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "app.sqlite3")
            factory = FakeFactory(path=store.path)
            provider = SyntheticOrders()
            factory.callback = provider
            service = Service(
                store,
                payments=OfflinePayPalSandboxAdapter(
                    OfflineBridge(self.core(factory)), MERCHANT
                ),
            )
            try:
                flow = Workflow(service)
                flow.analyze()
                flow.confirm()
                flow.create()
                provider.document["status"] = "APPROVED"
                flow.action("verify")
                provider.fail_capture_after_effect = True
                flow.action("capture")
                self.assertEqual("PAYMENT_UNKNOWN", flow.checkout["state"])
                self.assertEqual(
                    PROVIDER_ID, flow.checkout["order"]["provider_order_id"]
                )
                provider.fail_capture_after_effect = False
                service.payments = OfflinePayPalSandboxAdapter(
                    OfflineBridge(self.core(factory)), MERCHANT
                )
                flow.action("reconcile")
                self.assertEqual("COMPLETED", flow.checkout["state"])
                captures = [
                    call
                    for call in factory.calls
                    if call[1].endswith("/capture")
                ]
                self.assertEqual(1, len(captures))
                self.assertEqual("GET", factory.calls[-1][0])
                with store.connect() as connection:
                    rows = canonical(
                        [
                            dict(row)
                            for row in connection.execute(
                                "SELECT * FROM operations"
                            )
                        ]
                    )
                self.assertNotIn(RAW_ERROR, rows)
                self.assertNotIn(SYNTHETIC_TOKEN, rows)
            finally:
                service.close()
