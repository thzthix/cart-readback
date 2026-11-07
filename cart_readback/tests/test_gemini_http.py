"""Synthetic keys and fake/raw in-memory wires; genuine networking is forbidden."""

import http.client
import io
import os
import socket
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from cartreadback_app.gemini_client import CURRENT_MODEL, ENDPOINT, HOST, PATH
from cartreadback_app.gemini_http import GeminiHTTPTransport
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.validation import AppError
from test_responses_http import FakeConnection, FakeResponse

KEY = "fabricated-not-a-real-key"


def deadline(seconds=5):
    return Deadline(time.monotonic() + seconds, 1, 1)


class GeminiHTTPTests(unittest.TestCase):
    def setUp(self):
        network = mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("real network"),
        )
        network.start()
        self.addCleanup(network.stop)
        factory = mock.patch.object(
            http.client,
            "HTTPSConnection",
            side_effect=AssertionError("real TLS factory"),
        )
        factory.start()
        self.addCleanup(factory.stop)
        self.events = []
        self.factories = []
        self.borrows = 0
        self.guards = 0

    def make(
        self,
        *,
        body=b"{}",
        headers=None,
        status=200,
        failure=None,
        credential=KEY,
        guard=None,
    ):
        response = FakeResponse(
            body,
            headers
            or [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ],
            status,
        )
        self.connection = FakeConnection(response, self.events, failure)
        self.response = response

        def factory(host, port, *, timeout, context):
            self.factories.append((host, port, timeout, context))
            return self.connection

        def borrow(*, deadline):
            self.borrows += 1
            self.events.append(("credential",))
            return credential

        def check(**kwargs):
            self.guards += 1
            self.assertEqual(ENDPOINT, kwargs["endpoint"])
            self.assertEqual(b"{}", kwargs["body"])
            if guard is not None:
                guard(self.guards)

        return GeminiHTTPTransport(factory, borrow, check)

    def send(self, transport, *, endpoint=ENDPOINT, body=b"{}", limit=None):
        return transport.send(endpoint, body, deadline=limit or deadline())

    def assert_error(self, function, code="MODEL_UNAVAILABLE"):
        with self.assertRaises(AppError) as caught:
            function()
        self.assertEqual(code, caught.exception.code)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_cleanup_exception_prevents_known_success(self):
        for resource in ("response", "connection"):
            with self.subTest(resource=resource):
                transport = self.make()
                target = getattr(self, resource)
                target.close = mock.Mock(side_effect=OSError("SECRET cleanup"))
                self.assert_error(lambda: self.send(transport))
                target.close.assert_called_once()
                other = (
                    self.connection if resource == "response" else self.response
                )
                self.assertEqual(1, other.closed)

    def test_fixed_tls_header_key_and_single_attempt(self):
        transport = self.make()
        self.assertEqual(b"{}", self.send(transport))
        host, port, timeout, context = self.factories[0]
        self.assertEqual((HOST, 443), (host, port))
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)
        self.assertEqual(ssl.TLSVersion.TLSv1_2, context.minimum_version)
        request = next(item for item in self.events if item[0] == "request")
        self.assertEqual(("POST", PATH, b"{}"), request[1:4])
        self.assertEqual(KEY, request[4]["x-goog-api-key"])
        self.assertNotIn("Authorization", request[4])
        self.assertNotIn("?", request[2])
        self.assertEqual(HOST, request[4]["Host"])
        self.assertEqual(0, self.connection.auto_open)
        self.assertEqual(1, self.borrows)
        self.assertGreaterEqual(self.guards, 6)
        self.assertLess(
            self.events.index(("connect",)), self.events.index(("credential",))
        )
        self.assertEqual(1, self.connection.closed)
        self.assertEqual(1, self.response.closed)
        self.assert_error(lambda: self.send(transport))
        self.assertEqual(1, len(self.factories))

    def test_bad_endpoint_body_and_deadline_do_not_touch_key_or_factory(self):
        transport = self.make()
        for endpoint in (
            ENDPOINT + "?key=SECRET",
            ENDPOINT.replace("https:", "http:"),
            ENDPOINT.replace(HOST, "evil.example"),
            ENDPOINT + "/",
            ENDPOINT.replace(HOST, HOST + ":443"),
        ):
            self.assert_error(lambda: self.send(transport, endpoint=endpoint))
        for body in (b"", b"x" * 65_537, "{}"):
            self.assert_error(lambda: self.send(transport, body=body))
        self.assert_error(
            lambda: self.send(transport, limit=deadline(-1)), "MODEL_TIMEOUT"
        )
        self.assertEqual([], self.factories)
        self.assertEqual(0, self.borrows)

    def test_failed_guard_before_factory_or_borrow_is_terminal(self):
        def fail(_calls):
            raise ValueError("SECRET denied")

        transport = self.make(guard=fail)
        self.assert_error(lambda: self.send(transport))
        self.assert_error(lambda: self.send(transport))
        self.assertEqual([], self.factories)
        self.assertEqual(0, self.borrows)

    def test_false_guard_is_not_authorization(self):
        transport = self.make()
        transport._guard = lambda **_kwargs: False
        self.assert_error(lambda: self.send(transport))
        self.assertEqual([], self.factories)
        self.assertEqual(0, self.borrows)

    def test_current_model_endpoint_is_allowlisted_without_fallback(self):
        endpoint = (
            f"https://{HOST}/v1beta/models/{CURRENT_MODEL}:generateContent"
        )
        transport = self.make()
        transport._guard = lambda **_kwargs: None
        self.assertEqual(b"{}", self.send(transport, endpoint=endpoint))
        request = next(item for item in self.events if item[0] == "request")
        self.assertEqual(
            f"/v1beta/models/{CURRENT_MODEL}:generateContent", request[2]
        )
        self.assert_error(lambda: self.send(transport, endpoint=ENDPOINT))

    def test_ambient_keylog_is_not_enabled_or_created(self):
        with tempfile.TemporaryDirectory() as directory:
            keylog = Path(directory) / "not-a-secret-test.log"
            with mock.patch.dict(os.environ, {"SSLKEYLOGFILE": str(keylog)}):
                transport = self.make()
                self.assertEqual(b"{}", self.send(transport))
            self.assertIsNone(self.factories[0][3].keylog_filename)
            self.assertFalse(keylog.exists())

    def test_cleanup_interruption_still_closes_connection(self):
        transport = self.make()
        self.response.close = mock.Mock(
            side_effect=KeyboardInterrupt("synthetic")
        )
        with self.assertRaises(KeyboardInterrupt):
            self.send(transport)
        self.assertEqual(1, self.connection.closed)

    def test_header_drip_cannot_outlive_absolute_deadline(self):
        now = [0.0]
        read_times = []
        wire = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}"

        class Drip(io.RawIOBase):
            position = 0
            timeout = 1

            def readable(self):
                return True

            def readinto(self, target):
                if self.position == len(wire):
                    return 0
                read_times.append(now[0])
                if self.timeout < 0.01:
                    now[0] += self.timeout
                    raise TimeoutError("synthetic timeout")
                now[0] += 0.01
                target[0] = wire[self.position]
                self.position += 1
                return 1

        drip = Drip()

        class Socket:
            def makefile(self, *_args, **_kwargs):
                return io.BufferedReader(drip)

            def settimeout(self, value):
                drip.timeout = value

        sock = Socket()
        transport = self.make()
        self.connection.sock = sock

        def read_response():
            response = self.connection.response_class(sock, method="POST")
            try:
                response.begin()
                return response
            except BaseException:
                response.close()
                raise

        self.connection.getresponse = read_response
        with mock.patch(
            "cartreadback_app.responses_adapter.time.monotonic",
            side_effect=lambda: now[0],
        ):
            self.assert_error(
                lambda: self.send(transport, limit=Deadline(0.05, 1, 1)),
                "MODEL_TIMEOUT",
            )
        self.assertTrue(read_times)
        self.assertTrue(all(value < 0.05 for value in read_times))
        self.assertEqual(1, self.connection.closed)

    def test_authorization_expiry_after_borrow_prevents_post(self):
        def fail(_calls):
            if self.borrows:
                raise ValueError("SECRET revoked")

        transport = self.make(guard=fail)
        self.assert_error(lambda: self.send(transport))
        self.assertEqual(1, self.borrows)
        self.assertFalse(any(event[0] == "request" for event in self.events))
        self.assertEqual(1, self.connection.closed)

    def test_key_injection_invalid_before_post(self):
        for key in (
            "SECRET\r\nHost: evil.example",
            "a b",
            "",
            None,
            True,
            "x" * 257,
        ):
            with self.subTest(key=key):
                self.events.clear()
                transport = self.make(credential=key)
                self.assert_error(lambda: self.send(transport))
                self.assertFalse(
                    any(event[0] == "request" for event in self.events)
                )
                self.assertEqual(1, self.connection.closed)

    def test_connect_failure_reads_no_key_and_no_retries(self):
        transport = self.make(failure="connect")
        self.assert_error(lambda: self.send(transport))
        self.assertEqual(0, self.borrows)
        self.assertEqual(1, self.connection.closed)
        self.assert_error(lambda: self.send(transport))
        self.assertEqual(1, len(self.factories))

    def test_send_response_status_and_timeout_fail_closed(self):
        for failure in ("request", "response"):
            transport = self.make(failure=failure)
            self.assert_error(
                lambda: self.send(transport),
                "MODEL_TIMEOUT"
                if failure == "response"
                else "MODEL_UNAVAILABLE",
            )
            self.assertEqual(1, self.connection.closed)
        for status in (201, 301, 302, 307, 401, 429, 500, True):
            transport = self.make(status=status)
            self.assert_error(lambda: self.send(transport))
            self.assertEqual(1, self.connection.closed)
            self.assertEqual(1, self.response.closed)

    def test_hostile_ambiguous_framing_and_nonjson_rejected(self):
        variants = (
            [("Content-Type", "text/html")],
            [
                ("Content-Type", "application/json"),
                ("Content-Encoding", "gzip"),
            ],
            [("Content-Type", "application/json"), ("Content-Length", "02")],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Content-Length", "2"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Transfer-Encoding", "chunked"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", " chunked"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Transfer-Encoding", "gzip"),
            ],
            [
                ("Content-Type", "application/json"),
                ("Content-Length", "131073"),
            ],
            [("Content-Type", "application/json"), ("SECRET\n", "x")],
        )
        for headers in variants:
            with self.subTest(headers=headers):
                transport = self.make(headers=headers)
                self.assert_error(lambda: self.send(transport))
                self.assertEqual(1, self.response.closed)

    def test_short_oversized_and_wrong_chunk_type_rejected(self):
        for body, headers in (
            (
                b"x",
                [("Content-Type", "application/json"), ("Content-Length", "2")],
            ),
            (
                b"xxx",
                [("Content-Type", "application/json"), ("Content-Length", "2")],
            ),
            (b"x" * 131_073, [("Content-Type", "application/json")]),
        ):
            transport = self.make(body=body, headers=headers)
            self.assert_error(lambda: self.send(transport))
        transport = self.make()
        self.response.read1 = lambda _amount: "SECRET"
        self.assert_error(lambda: self.send(transport))

    def test_late_read_no_result_and_closed_response(self):
        transport = self.make()
        limit = deadline(0.05)
        self.response.read_hook = lambda: time.sleep(0.06)
        self.assert_error(
            lambda: self.send(transport, limit=limit), "MODEL_TIMEOUT"
        )
        self.assertEqual(1, self.connection.closed)
        self.assertEqual(1, self.response.closed)

    def test_ambient_proxy_variables_ignored(self):
        with mock.patch.dict(
            "os.environ",
            {
                "HTTPS_PROXY": "https://evil.example",
                "HTTP_PROXY": "http://evil.example",
                "GEMINI_API_KEY": "SECRET",
            },
        ):
            transport = self.make()
            self.assertEqual(b"{}", self.send(transport))
        self.assertEqual(HOST, self.factories[0][0])
        self.assertFalse(any(event[0] == "tunnel" for event in self.events))

    def test_real_stdlib_parser_on_fabricated_connection_close_and_chunked_wires(
        self,
    ):
        cases = (
            (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}",
                b"{}",
            ),
            (
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n",
                b"{}",
            ),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                parent = self

                class Socket:
                    def makefile(self, *_args, **_kwargs):
                        return io.BytesIO(raw)

                    def settimeout(self, value):
                        parent.assertGreater(value, 0)

                sock = Socket()
                transport = self.make()
                self.connection.sock = sock
                self.connection.getresponse = (
                    lambda: self.connection.response_class(sock, method="POST")
                )
                original = self.connection.getresponse

                def read_head():
                    result = original()
                    result.begin()
                    return result

                self.connection.getresponse = read_head
                self.assertEqual(expected, self.send(transport))


if __name__ == "__main__":
    unittest.main()
