"""Fabricated HTTPS mechanics only: these tests prohibit real network calls."""

import dataclasses
import http.client
import io
import json
import ssl
import time
import unittest
from unittest import mock

from cartreadback_app.inference_config import ENDPOINT
from cartreadback_app.responses_adapter import Deadline, OfflineResponsesAdapter
from cartreadback_app.responses_http import (
    HTTPSRoutingConfig,
    InjectedHTTPSTransport,
)
from cartreadback_app.validation import AppError
from test_responses_adapter import domain, encode, envelope

SYNTHETIC_TOKEN = "test-only-not-a-real-credential"


def deadline(seconds=10):
    return Deadline(time.monotonic() + seconds, 1, 1)


class FakeSocket:
    def __init__(self, events):
        self.events = events

    def settimeout(self, value):
        self.events.append(("timeout", value))


class FakeResponse:
    def __init__(self, body=b"{}", headers=None, status=200, version=11):
        self.status = status
        self.version = version
        self.body = body
        self.headers = headers or [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            ("X-Request-Id", "req_fabricated"),
        ]
        self.closed = 0
        self.reads = []
        self.read_hook = None

    def getheaders(self):
        return self.headers

    def read1(self, amount):
        self.reads.append(amount)
        if self.read_hook is not None:
            self.read_hook()
        value, self.body = self.body[:amount], self.body[amount:]
        return value

    def close(self):
        self.closed += 1


class FakeConnection:
    def __init__(self, response, events, failure=None):
        self.response = response
        self.events = events
        self.failure = failure
        self.sock = FakeSocket(events)
        self.closed = 0
        self.auto_open = True

    def set_debuglevel(self, value):
        self.events.append(("debuglevel", value))

    def set_tunnel(self, host, port, headers):
        self.events.append(("tunnel", host, port, dict(headers)))

    def connect(self):
        self.events.append(("connect",))
        if self.failure == "connect":
            raise ssl.SSLCertVerificationError("SECRET raw TLS error")
        if self.failure == "proxy":
            raise OSError("SECRET raw proxy refusal")

    def request(self, method, path, *, body, headers, encode_chunked):
        self.events.append(
            ("request", method, path, body, dict(headers), encode_chunked)
        )
        if self.failure == "request":
            raise OSError("SECRET raw send error")

    def getresponse(self):
        self.events.append(("getresponse",))
        if self.failure == "response":
            raise TimeoutError("SECRET raw read error")
        return self.response

    def close(self):
        self.closed += 1


class HTTPSTransportTests(unittest.TestCase):
    def setUp(self):
        # Every focused test fails if a real socket or default HTTPS factory runs.
        self.network = mock.patch(
            "socket.create_connection",
            side_effect=AssertionError("real network"),
        )
        self.network.start()
        self.addCleanup(self.network.stop)
        self.https = mock.patch(
            "http.client.HTTPSConnection",
            side_effect=AssertionError("real factory"),
        )
        self.https.start()
        self.addCleanup(self.https.stop)
        self.events = []
        self.factory_calls = []
        self.credentials_calls = 0

    def make(
        self, response=None, *, failure=None, route="direct", credential=None
    ):
        self.response = response if response is not None else FakeResponse()
        self.connection = FakeConnection(self.response, self.events, failure)

        def factory(host, port, *, timeout, context):
            self.factory_calls.append((host, port, timeout, context))
            return self.connection

        def credentials():
            self.credentials_calls += 1
            self.events.append(("credentials",))
            return SYNTHETIC_TOKEN if credential is None else credential

        return InjectedHTTPSTransport(
            factory, credentials, HTTPSRoutingConfig(route)
        )

    def send(self, transport, body=b"{}", endpoint=ENDPOINT, limit=None):
        return transport.send(endpoint, body, deadline=limit or deadline())

    def error(self, call, code="MODEL_UNAVAILABLE"):
        with self.assertRaises(AppError) as caught:
            call()
        self.assertEqual(code, caught.exception.code)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn(SYNTHETIC_TOKEN, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_fixed_request_tls_and_cleanup(self):
        transport = self.make()
        wire = self.send(transport, b'{"synthetic":true}')
        self.assertEqual(b"{}", b"".join(wire.body))
        wire.close()
        host, port, timeout, context = self.factory_calls[0]
        self.assertEqual(("api.openai.com", 443), (host, port))
        self.assertLessEqual(timeout, 1)
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        request = [e for e in self.events if e[0] == "request"][0]
        self.assertEqual(("POST", "/v1/responses"), request[1:3])
        self.assertEqual(b'{"synthetic":true}', request[3])
        self.assertEqual(
            "Bearer " + SYNTHETIC_TOKEN, request[4]["Authorization"]
        )
        self.assertEqual("api.openai.com", request[4]["Host"])
        self.assertEqual("identity", request[4]["Accept-Encoding"])
        self.assertEqual("18", request[4]["Content-Length"])
        self.assertFalse(request[5])
        self.assertEqual(0, self.connection.auto_open)
        self.assertEqual(1, self.connection.closed)
        self.assertEqual(1, self.response.closed)
        self.assertEqual(1, self.credentials_calls)
        self.assertLess(
            self.events.index(("connect",)), self.events.index(("credentials",))
        )
        self.assertNotIn(SYNTHETIC_TOKEN, json.dumps(transport.metadata))
        self.assertNotIn(SYNTHETIC_TOKEN, repr(transport))

    def test_proxy_connect_has_no_authorization_and_ambient_proxy_ignored(self):
        for route in ("direct", "pythonanywhere"):
            with (
                self.subTest(route=route),
                mock.patch.dict(
                    "os.environ",
                    {"HTTPS_PROXY": "http://evil.invalid", "NO_PROXY": "*"},
                ),
            ):
                self.events = []
                self.factory_calls = []
                transport = self.make(route=route)
                wire = self.send(transport)
                list(wire.body)
                if route == "pythonanywhere":
                    self.assertEqual(
                        ("proxy.server", 3128), self.factory_calls[0][:2]
                    )
                    self.assertIn(
                        ("tunnel", "api.openai.com", 443, {}), self.events
                    )
                else:
                    self.assertEqual(
                        ("api.openai.com", 443), self.factory_calls[0][:2]
                    )
                    self.assertFalse(any(e[0] == "tunnel" for e in self.events))

    def test_invalid_endpoint_or_body_before_factory_or_credentials(self):
        endpoints = [
            "http://api.openai.com/v1/responses",
            ENDPOINT + "?key=SECRET",
            ENDPOINT + "#fragment",
            ENDPOINT + "/",
            ENDPOINT.upper(),
            "https://api.openai.com:443/v1/responses",
            "https://user@api.openai.com/v1/responses",
            "https://api.openai.com.evil/v1/responses",
            None,
        ]
        transport = self.make()
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.error(lambda: self.send(transport, endpoint=endpoint))
        for body in (b"", b"x" * 65537, "{}", bytearray(b"{}"), None):
            with self.subTest(body_type=type(body)):
                self.error(lambda: self.send(transport, body))
        self.assertEqual([], self.factory_calls)
        self.assertEqual(0, self.credentials_calls)

    def test_invalid_configuration_and_deadline_fail_closed(self):
        for route in (None, "http://proxy.server:3128", "auto", True):
            self.error(lambda: HTTPSRoutingConfig(route))
        config = HTTPSRoutingConfig()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.route = "pythonanywhere"
        self.assertNotEqual(
            config.metadata, HTTPSRoutingConfig("pythonanywhere").metadata
        )
        transport = self.make()
        for limit in (
            None,
            Deadline(float("nan"), 1, 1),
            Deadline(time.monotonic() + 2, 4, 1),
        ):
            self.error(lambda: transport.send(ENDPOINT, b"{}", deadline=limit))
        self.error(
            lambda: self.send(transport, limit=deadline(-1)), "MODEL_TIMEOUT"
        )
        self.assertEqual([], self.factory_calls)

    def test_connect_proxy_write_header_failures_single_attempt_and_redacted(
        self,
    ):
        for failure in ("connect", "proxy", "request", "response"):
            with self.subTest(failure=failure):
                self.factory_calls = []
                self.credentials_calls = 0
                transport = self.make(failure=failure, route="pythonanywhere")
                self.error(
                    lambda: self.send(transport),
                    "MODEL_TIMEOUT"
                    if failure == "response"
                    else "MODEL_UNAVAILABLE",
                )
                self.error(lambda: self.send(transport))
                self.assertEqual(1, len(self.factory_calls))
                self.assertEqual(1, self.connection.closed)
                self.assertEqual(
                    0 if failure in ("connect", "proxy") else 1,
                    self.credentials_calls,
                )

    def test_invalid_credential_never_becomes_http_header(self):
        for token in ("x\r\nX-Evil: yes", "x y", "", "é", 123, "x" * 4097):
            with self.subTest(token_type=type(token)):
                self.events = []
                transport = self.make(credential=token)
                self.error(lambda: self.send(transport))
                self.assertFalse(any(e[0] == "request" for e in self.events))
                self.assertEqual(1, self.connection.closed)

    def test_non200_and_redirect_never_followed_or_read(self):
        for status in (True, 100, 201, 301, 302, 307, 308, 401, 429, 500):
            with self.subTest(status=status):
                self.factory_calls = []
                response = FakeResponse(status=status)
                response.headers.append(("Location", "https://evil.invalid"))
                transport = self.make(response)
                self.error(lambda: self.send(transport))
                self.assertEqual([], response.reads)
                self.assertEqual(1, response.closed)
                self.assertEqual(1, len(self.factory_calls))

    def test_invalid_headers_fail_before_body(self):
        base = [
            ("Content-Type", "application/json"),
            ("X-Request-Id", "req_fake"),
        ]
        cases = [
            base + [("Content-Length", "131073")],
            base + [("Content-Length", "-1")],
            base + [("Content-Length", "01")],
            base + [("Content-Length", "2"), ("content-length", "2")],
            base + [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
            base + [("Transfer-Encoding", "gzip")],
            base + [("Content-Encoding", "gzip")],
            base + [("x-request-id", "other")],
            [("Content-Type", "text/html"), ("X-Request-Id", "req_fake")],
            [("Content-Type", "application/json")],
            [("Content-Type", "application/json"), ("X-Request-Id", "bad id")],
            base + [("X-Test", "secret\nfold")],
            base + [("X-Test", "x" * 4097)],
            base + [("X-Test", "x")] * 63,
            base + [("X-Test", "x" * 4096)] * 4,
        ]
        for headers in cases:
            with self.subTest(headers=headers[:3]):
                response = FakeResponse(headers=headers)
                transport = self.make(response)
                self.error(lambda: self.send(transport))
                self.assertEqual([], response.reads)
                self.assertEqual(1, response.closed)

    def test_chunked_and_close_delimited_response_bounded(self):
        for extra in ([], [("Transfer-Encoding", "chunked")]):
            response = FakeResponse(
                b"x" * 131072,
                headers=[
                    ("Content-Type", "application/json; charset=UTF-8"),
                    ("X-Request-Id", "req_fake"),
                ]
                + extra,
            )
            wire = self.send(self.make(response))
            self.assertEqual(131072, len(b"".join(wire.body)))
            self.assertLessEqual(max(response.reads), 8192)
            self.assertEqual(1, self.connection.closed)

    def test_oversized_truncated_and_wrong_body_type_block_reuse(self):
        for body, length in (
            (b"x" * 131073, None),
            (b"x", "2"),
            (b"xx", "1"),
            ("not bytes", None),
        ):
            with self.subTest(length=length, body_type=type(body)):
                headers = [
                    ("Content-Type", "application/json"),
                    ("X-Request-Id", "req_fake"),
                ]
                if length is not None:
                    headers.append(("Content-Length", length))
                transport = self.make(FakeResponse(body, headers=headers))
                wire = self.send(transport)
                self.error(lambda: list(wire.body))
                self.error(lambda: self.send(transport))
                self.assertEqual(1, self.connection.closed)

    def test_body_timeout_cleanup_and_no_second_attempt(self):
        transport = self.make()
        wire = self.send(transport)
        self.response.read_hook = lambda: (_ for _ in ()).throw(
            TimeoutError("SECRET")
        )
        self.error(lambda: list(wire.body), "MODEL_TIMEOUT")
        self.error(lambda: self.send(transport))
        self.assertEqual(1, self.connection.closed)

    def test_overall_deadline_covers_slow_body_and_credentials(self):
        transport = self.make()
        wire = self.send(transport, limit=deadline(0.05))
        self.response.read_hook = lambda: time.sleep(0.06)
        self.error(lambda: list(wire.body), "MODEL_TIMEOUT")
        self.assertEqual(1, self.connection.closed)
        transport = self.make()

        def slow_credentials():
            time.sleep(0.06)
            return SYNTHETIC_TOKEN

        transport._credentials = slow_credentials
        self.events = self.connection.events = []
        self.error(
            lambda: self.send(transport, limit=deadline(0.05)), "MODEL_TIMEOUT"
        )
        self.assertFalse(any(e[0] == "request" for e in self.events))

    def test_concurrency_early_close_and_never_started_iterator(self):
        transport = self.make(FakeResponse(b"x" * 10000))
        wire = self.send(transport)
        self.error(lambda: self.send(transport))
        iterator = iter(wire.body)
        self.assertEqual(8192, len(next(iterator)))
        iterator.close()
        wire.close()
        self.error(lambda: self.send(transport))
        self.assertEqual(1, self.connection.closed)
        transport = self.make()
        wire = self.send(transport)
        wire.close()
        self.error(lambda: self.send(transport))
        self.assertEqual(1, self.connection.closed)

    def test_adapter_consumes_synthetic_response_and_preserves_frozen_identity(
        self,
    ):
        source, conditions, results = domain()
        transport = self.make(FakeResponse(encode(envelope(results))))
        adapter = OfflineResponsesAdapter(transport)
        self.assertEqual(results, adapter.observe(source, conditions).results)
        self.assertEqual(
            "offline-injected-only", adapter.metadata["execution_mode"]
        )
        self.assertEqual("not-shipped", transport.metadata["runtime_enable"])
        self.assertEqual(1, self.connection.closed)
        self.assertEqual(1, self.credentials_calls)

    def test_real_stdlib_parser_with_close_and_chunked_framing(self):
        # Exercise actual getresponse/read1 behavior without network/TLS claims.
        for framing, body in (
            (b"Content-Length: 2\r\nConnection: close\r\n", b"{}"),
            (b"Content-Length: 0\r\nConnection: close\r\n", b""),
            (b"Connection: close\r\n", b"{}"),
            (b"Transfer-Encoding: chunked\r\n", b"2\r\n{}\r\n0\r\n\r\n"),
        ):
            with self.subTest(framing=framing):
                events = []
                raw = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"X-Request-Id: req_parser\r\n" + framing + b"\r\n" + body
                )

                class SocketFile(io.BytesIO):
                    def __init__(self, owner, data):
                        self.owner = owner
                        super().__init__(data)

                    def close(self):
                        if not self.closed:
                            self.owner.refs -= 1
                        super().close()

                class BufferedFakeSocket:
                    def __init__(self):
                        self.refs = 0
                        self.close_requested = False

                    def sendall(self, data):
                        events.append(("sendall", data))

                    def makefile(self, mode):
                        self.refs += 1
                        return SocketFile(self, raw)

                    def settimeout(self, value):
                        if self.close_requested and self.refs == 0:
                            raise OSError(9, "Synthetic released descriptor")
                        events.append(("timeout", value))

                    def close(self):
                        self.close_requested = True
                        events.append(("socket-close",))

                class ParserConnection(http.client.HTTPConnection):
                    def __init__(self, host, port, *, timeout, context):
                        super().__init__(host, port, timeout=timeout)

                    def connect(self):
                        self.sock = BufferedFakeSocket()

                transport = InjectedHTTPSTransport(
                    ParserConnection, lambda: SYNTHETIC_TOKEN
                )
                wire = self.send(transport)
                expected = b"" if b"Content-Length: 0" in framing else b"{}"
                self.assertEqual(expected, b"".join(wire.body))
                self.assertEqual("req_parser", wire.request_id)
                sent = b"".join(e[1] for e in events if e[0] == "sendall")
                self.assertIn(b"POST /v1/responses HTTP/1.1\r\n", sent)
                self.assertIn(b"Host: api.openai.com\r\n", sent)
                self.assertEqual(1, sent.count(b"Authorization:"))

    def test_real_stdlib_rejects_malformed_wire(self):
        base = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"X-Request-Id: req_parser\r\n"
        )
        cases = [
            base
            + b"Content-Length: 2\r\nMalformed Header: x\r\nContent-Length: 999\r\n\r\n{}",
            base + b"Content-Length: 2\r\ncontent-length: 2\r\n\r\n{}",
            base + b"Content-Length: 2\r\n Folded: no\r\n\r\n{}",
            base + b"Content-Length: 2\n\n{}",
            base + b"Content-Length: 2\r\n",
            base + b"Transfer-Encoding: chunked \r\n\r\n{}",
            base + b"Transfer-Encoding: chunked \r\n\r\n2\r\n{}\r\n0\r\n\r\n",
            base.replace(b"HTTP/1.1", b"HTTP/1.999")
            + b"Content-Length: 2\r\n\r\n{}",
            base.replace(b"200", b"+200") + b"Content-Length: 2\r\n\r\n{}",
            base + b"X-Field: x\r\n" * 63 + b"\r\n{}",
            base + b"X-Field: " + b"x" * 5000 + b"\r\n\r\n{}",
        ]
        for data in (
            b"2\r\n{}XY0\r\n\r\n",
            b"2\r\n{}\r\n0\r\n",
            b"+2\r\n{}\r\n0\r\n\r\n",
            b"2;extension=x\r\n{}\r\n0\r\n\r\n",
            b"2\r\n{}\r\n0\r\nX-Trailer: no\r\n\r\n",
            b"20001\r\n",
            b"0000000000000000002\r\n{}\r\n0\r\n\r\n",
        ):
            cases.append(base + b"Transfer-Encoding: chunked\r\n\r\n" + data)
        for raw in cases:
            with self.subTest(raw=raw[:100]):

                class RawSocket:
                    def sendall(self, data):
                        pass

                    def makefile(self, mode):
                        return io.BytesIO(raw)

                    def settimeout(self, value):
                        pass

                    def close(self):
                        pass

                class ParserConnection(http.client.HTTPConnection):
                    def __init__(self, host, port, *, timeout, context):
                        super().__init__(host, port, timeout=timeout)

                    def connect(self):
                        self.sock = RawSocket()

                transport = InjectedHTTPSTransport(
                    ParserConnection, lambda: SYNTHETIC_TOKEN
                )

                def consume():
                    reply = self.send(transport)
                    return b"".join(reply.body)

                self.error(consume)
                self.assertFalse(transport._flight.locked())
                self.error(lambda: self.send(transport))

    def test_interruptions_cleanup_without_suppressing_cancellation(self):
        for phase in (
            "connect",
            "credentials",
            "request",
            "getresponse",
            "getheaders",
            "read1",
            "close",
        ):
            for interrupt in (KeyboardInterrupt, SystemExit):
                with self.subTest(phase=phase, interrupt=interrupt):
                    transport = self.make()

                    def stop(*args, **kwargs):
                        raise interrupt("synthetic interruption")

                    if phase == "credentials":
                        transport._credentials = stop
                    elif phase in ("getheaders", "read1", "close"):
                        setattr(self.response, phase, stop)
                    else:
                        setattr(self.connection, phase, stop)
                    with self.assertRaises(interrupt):
                        reply = self.send(transport)
                        list(reply.body)
                    self.assertEqual(1, self.connection.closed)
                    self.assertFalse(transport._flight.locked())
                    self.assertTrue(transport._blocked)
                    self.error(lambda: self.send(transport))

    def test_close_during_eof_read_cannot_report_success(self):
        transport = self.make()
        wire = self.send(transport)

        def close_at_eof():
            if not self.response.body:
                wire.close()

        self.response.read_hook = close_at_eof
        self.error(lambda: list(wire.body))
        self.assertEqual(1, self.connection.closed)
        self.assertFalse(transport._flight.locked())
        self.error(lambda: self.send(transport))

    def test_factory_and_credential_exceptions_are_sanitized(self):
        for seam in ("factory", "credentials"):
            transport = self.make()

            def fail(*args, **kwargs):
                raise RuntimeError("SECRET callback value")

            setattr(
                transport,
                "_factory" if seam == "factory" else "_credentials",
                fail,
            )
            self.error(lambda: self.send(transport))
            self.error(lambda: self.send(transport))


if __name__ == "__main__":
    unittest.main()
