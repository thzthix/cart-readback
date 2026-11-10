"""Public synthetic native-wire failures; no external network or credentials."""

import http.client
import socket
import time
import unittest
from unittest.mock import patch

from cartreadback_app.gemini_client import ENDPOINT
from cartreadback_app.gemini_http import (
    GeminiHTTPTransport,
    GeminiTransportFailure,
    gemini_failure_diagnostic,
    safe_gemini_diagnostic,
)
from cartreadback_app.responses_adapter import Deadline
from cartreadback_app.validation import AppError


class NativeConnection(http.client.HTTPSConnection):
    def connect(self):
        self.sock, self.peer = socket.socketpair()
        self.peer.sendall(self.fixture)
        self.peer.shutdown(socket.SHUT_WR)

    def getresponse(self):
        response = super().getresponse()
        self.detached = self.sock is None
        return response


class DiagnosticTests(unittest.TestCase):
    def exercise(self, wire, fault=None):
        instances = []

        def factory(*args, **kwargs):
            if fault == "preconnect":
                raise RuntimeError("PRIVATE_EXCEPTION_MUST_NOT_ESCAPE")
            c = NativeConnection(*args, **kwargs)
            c.fixture = wire
            instances.append(c)
            if fault in ("connect", "request"):

                def fail(*args, **kwargs):
                    raise RuntimeError("PRIVATE_EXCEPTION_MUST_NOT_ESCAPE")

                setattr(c, fault, fail)
            return c

        def borrow(**kwargs):
            if fault == "credential":
                raise AppError("GEMINI_RUN_BLOCKED", "PRIVATE_DESCRIPTION")
            return "PUBLIC_FAKE_TOKEN"

        def guard(**kwargs):
            if fault == "guard":
                raise AppError("GEMINI_CAPACITY_BLOCKED", "PRIVATE_DESCRIPTION")

        transport = GeminiHTTPTransport(factory, borrow, guard)
        with patch.object(
            socket, "create_connection", side_effect=AssertionError("NETWORK")
        ):
            try:
                result = transport.send(
                    ENDPOINT,
                    b"{}",
                    deadline=Deadline(time.monotonic() + 5, 1, 1),
                )
                return result, instances
            except GeminiTransportFailure as error:
                self.assertNotIn("PRIVATE_", str(error))
                self.assertNotIn("PUBLIC_FAKE_TOKEN", repr(error.diagnostic))
                with self.assertRaises(AppError):
                    transport.send(
                        ENDPOINT,
                        b"{}",
                        deadline=Deadline(time.monotonic() + 5, 1, 1),
                    )
                return error.diagnostic, instances
            finally:
                for c in instances:
                    if hasattr(c, "peer"):
                        c.peer.close()

    def test_native_close_framings(self):
        for headers, body in (
            (b"Content-Length: 2\r\nConnection: close\r\n", b"{}"),
            (
                b"Transfer-Encoding: chunked\r\nConnection: close\r\n",
                b"2\r\n{}\r\n0\r\n\r\n",
            ),
            (b"Connection: close\r\n", b"{}"),
            (b"Content-Length: 2\r\n", b"{}"),
        ):
            with self.subTest(headers=headers):
                raw, connections = self.exercise(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + headers
                    + b"\r\n"
                    + body
                )
                self.assertEqual(raw, b"{}")
                self.assertEqual(connections[0].detached, b"close" in headers)

    def test_received_status_never_accepts_error_body(self):
        for status in (400, 401, 403, 429, 500):
            with self.subTest(status=status):
                observed, _ = self.exercise(
                    f"HTTP/1.1 {status} PRIVATE_REASON\r\nContent-Length: 0\r\n\r\n".encode()
                )
                self.assertEqual(observed["stage"], "status")
                self.assertEqual(observed["http_status"], status)
                self.assertNotIn("PRIVATE", repr(observed))

    def test_pre_provider_failures_are_distinct(self):
        for stage in (
            "guard",
            "preconnect",
            "connect",
            "credential",
            "request",
        ):
            with self.subTest(stage=stage):
                observed, _ = self.exercise(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
                    stage,
                )
                self.assertEqual(observed["stage"], stage)
                self.assertIsNone(observed["http_status"])

    def test_body_failure_retains_received_200(self):
        observed, _ = self.exercise(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\n{}"
        )
        self.assertEqual(
            observed,
            {
                "stage": "body",
                "category": "MODEL_UNAVAILABLE",
                "http_status": 200,
            },
        )

    def test_projection_rejects_arbitrary_values(self):
        valid = {
            "stage": "body",
            "category": "MODEL_UNAVAILABLE",
            "http_status": 200,
        }
        for key in valid:
            bad = dict(valid, **{key: "PRIVATE_VALUE"})
            self.assertIsNone(safe_gemini_diagnostic(bad))
        self.assertIsNone(safe_gemini_diagnostic(dict(valid, extra="PRIVATE")))
        self.assertIsNone(safe_gemini_diagnostic(dict(valid, http_status=True)))
        self.assertEqual(
            gemini_failure_diagnostic(RuntimeError("PRIVATE")),
            {
                "stage": "exchange",
                "category": "UNEXPECTED_FAILURE",
                "http_status": None,
            },
        )


if __name__ == "__main__":
    unittest.main()


class ServiceDiagnosticTests(unittest.TestCase):
    def test_failed_exchange_stays_unknown_and_reserved(self):
        from cartreadback_app.genuine_gemini import GenuineGeminiAdapter
        from test_gemini_service import GeminiServiceTests

        fixture = GeminiServiceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        failure = GeminiTransportFailure("status", "MODEL_UNAVAILABLE", 400)
        with patch.object(
            GenuineGeminiAdapter, "exchange", side_effect=failure
        ) as exchange:
            result = fixture.flow.analyze()
        checkout = result["checkout"]
        self.assertEqual(exchange.call_count, 1)
        self.assertEqual(checkout["analysis_error"], "MODEL_OUTCOME_UNKNOWN")
        self.assertEqual(checkout["analysis_diagnostic"], failure.diagnostic)
        self.assertEqual(checkout["analysis"]["accounting_state"], "unknown")
        self.assertFalse(checkout["analysis"]["usage_observed"])
        self.assertEqual(checkout["results"], [])
        capacity = fixture.rows("gemini_capacity_operations")[0]
        self.assertEqual(capacity["status"], "UNKNOWN")
        self.assertIsNotNone(capacity["reservation"])
        self.assertEqual(fixture.state["calls"], 0)
        self.assertEqual(fixture.handle.calls, 0)
        self.assertEqual(
            fixture.service.bootstrap(fixture.sid)["checkout"][
                "analysis_diagnostic"
            ],
            failure.diagnostic,
        )
