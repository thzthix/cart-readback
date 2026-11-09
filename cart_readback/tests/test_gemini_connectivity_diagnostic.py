"""Synthetic diagnostic regressions. No provider, credential or asset reads."""

import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import socket
import ssl
import sys
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cart_readback"))
MODULE = ROOT / "cart_readback/scripts/gemini_connectivity_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("offline_diagnostic", MODULE)
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def fixtures():
    enrollment = {
        "repository_id": 100,
        "workflow_id": 200,
        "actor_id": 300,
        "path": diagnostic.WORKFLOW_PATH,
        "ref": "refs/heads/main",
        "head_sha": "a" * 40,
        "valid_from": 1000,
        "expires_at": 2000,
    }
    current = {
        k: v
        for k, v in enrollment.items()
        if k not in ("valid_from", "expires_at")
    }
    current.update(
        {
            "id": 400,
            "run_number": 1,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "created_at": 1100,
            "status": "in_progress",
            "conclusion": None,
        }
    )
    snapshot = {
        "evidence_kind": "fabricated-offline",
        "http_status": 200,
        "next_page": None,
        "truncated": False,
        "current": current,
        "history": {
            "total_count": 1,
            "workflow_runs": [copy.deepcopy(current)],
        },
    }
    grant = {
        "schema": "fabricated-connectivity-grant-v1",
        "request_sha256": diagnostic.REQUEST_SHA256,
        "endpoint": diagnostic.ENDPOINT,
        "model": diagnostic.MODEL,
        "expected_model_version": diagnostic.MODEL,
        "valid_from": 1000,
        "expires_at": 2000,
        "max_calls": 1,
        "max_total_input_tokens": 1048576,
        "max_total_output_tokens": 2048,
        "max_micro_usd": 0,
        "admission_mode": "externally-verified-free-tier",
        "exact_request_owner_grant_sha256": "b" * 64,
        "credential_transmission_grant_sha256": "c" * 64,
        "free_project_facts_sha256": "d" * 64,
        "zero_cost_compute_facts_sha256": "e" * 64,
    }
    response = {
        "modelVersion": diagnostic.MODEL,
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 2,
            "thoughtsTokenCount": 1,
            "totalTokenCount": 15,
        },
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "PRIVATE_SENTINEL"}],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
    }
    return enrollment, snapshot, grant, response


class FakeTransport:
    evidence_kind = "fabricated-offline"

    def __init__(self, response, status=200):
        self.body = json.dumps(response).encode()
        self.status = status
        self.calls = []
        self.error = None

    def exchange(self, endpoint, payload, timeout_seconds):
        self.calls.append((endpoint, payload, timeout_seconds))
        if self.error:
            raise self.error
        return self.status, self.body


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.socket_guard = mock.patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        )
        self.socket_guard.start()
        self.addCleanup(self.socket_guard.stop)
        self.enrollment, self.snapshot, self.grant, self.response = fixtures()
        self.transport = FakeTransport(self.response)
        self.subject = diagnostic.OfflineDiagnostic()

    def run_fixture(self, clock=lambda: 1200):
        return self.subject.run(
            self.enrollment, self.snapshot, self.grant, self.transport, clock
        )

    def assert_blocked(self):
        self.assertEqual(self.run_fixture()["status"], "NOT_RUN")
        self.assertEqual(self.transport.calls, [])

    def test_one_fixed_call_and_safe_result(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.run_fixture()
        self.assertEqual(
            result,
            {
                "status": "FABRICATED_ACCEPTED",
                "evidence_kind": "fabricated-offline",
                "model": diagnostic.MODEL,
                "input_tokens": 12,
                "output_tokens": 3,
                "total_tokens": 15,
            },
        )
        self.assertEqual(
            self.transport.calls,
            [(diagnostic.ENDPOINT, diagnostic.REQUEST, 20)],
        )
        self.assertNotIn(
            "PRIVATE_SENTINEL", json.dumps(result) + output.getvalue()
        )
        self.assertEqual(self.run_fixture()["status"], "NOT_RUN")
        self.assertEqual(len(self.transport.calls), 1)

    def test_request_is_fixed_public_minimal_surface(self):
        request = json.loads(diagnostic.REQUEST)
        self.assertEqual(set(request), {"contents", "generationConfig"})
        self.assertEqual(
            request["generationConfig"],
            {
                "candidateCount": 1,
                "maxOutputTokens": 32,
                "temperature": 0,
                "thinkingConfig": {"thinkingLevel": "MINIMAL"},
            },
        )
        self.assertEqual(
            diagnostic.REQUEST_SHA256,
            "1d5aeeb73cc4fa2225e99bd1bdccd5a963251e00e1f7cd9f6561489b980f95f8",
        )

    def test_production_is_always_not_run(self):
        with mock.patch.dict(
            "os.environ", {"GEMINI_API_KEY": "SYNTHETIC_ONLY"}
        ):
            self.assertEqual(
                diagnostic.production_status(),
                {
                    "status": "NOT_RUN",
                    "reason": "PRODUCTION_ACTIVATION_UNSUPPORTED",
                },
            )
        self.assertEqual(self.transport.calls, [])

    def test_workflow_is_frozen_and_cannot_activate_through_inputs(self):
        workflow = ROOT / diagnostic.WORKFLOW_PATH
        self.assertEqual(
            diagnostic.hashlib.sha256(workflow.read_bytes()).hexdigest(),
            "e1cbad98fe5a04cf2aa5abaa0a66fb5e512b09365bfd1a7bec314cc71f6af21a",
        )

    def test_concurrent_use_cannot_dispatch_twice(self):
        entered, release = threading.Event(), threading.Event()
        original = self.transport.exchange

        def blocked_exchange(*args):
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
            return original(*args)

        self.transport.exchange = blocked_exchange
        results = []
        worker = threading.Thread(
            target=lambda: results.append(self.run_fixture())
        )
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.run_fixture()["status"], "NOT_RUN")
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["status"], "FABRICATED_ACCEPTED")
        self.assertEqual(len(self.transport.calls), 1)

    def test_changed_records_during_exchange_are_unknown(self):
        original = self.transport.exchange

        def changed_exchange(*args):
            self.enrollment["actor_id"] = 999
            return original(*args)

        self.transport.exchange = changed_exchange
        self.assertEqual(self.run_fixture()["status"], "UNKNOWN")

    def test_interruption_is_unknown_and_consumes_the_attempt(self):
        for error in (
            KeyboardInterrupt(),
            SystemExit("PRIVATE_EXCEPTION_SENTINEL"),
        ):
            with self.subTest(error=type(error)):
                self.setUp_candidate()
                self.transport.error = error
                self.assertEqual(self.run_fixture()["status"], "UNKNOWN")
                self.assertEqual(self.run_fixture()["status"], "NOT_RUN")
                self.assertEqual(len(self.transport.calls), 1)

    def test_optional_response_id_is_validated_and_discarded(self):
        self.response["responseId"] = "SYNTHETIC_RESPONSE_ID"
        self.transport.body = json.dumps(self.response).encode()
        result = self.run_fixture()
        self.assertEqual(result["status"], "FABRICATED_ACCEPTED")
        self.assertNotIn("SYNTHETIC_RESPONSE_ID", json.dumps(result))
        self.setUp_candidate()
        self.response["responseId"] = "invalid\nheader"
        self.transport.body = json.dumps(self.response).encode()
        self.assertEqual(self.run_fixture()["status"], "UNKNOWN")

    def test_counter_types_and_values(self):
        for field in ("run_number", "run_attempt"):
            for value in (0, 2, -1, True, "1", None, 1.0):
                with self.subTest(field=field, value=value):
                    self.setUp_candidate()
                    self.snapshot["current"][field] = value
                    self.assert_blocked()

    def setUp_candidate(self):
        self.enrollment, self.snapshot, self.grant, self.response = fixtures()
        self.transport = FakeTransport(self.response)
        self.subject = diagnostic.OfflineDiagnostic()

    def test_identity_and_revision_mismatches(self):
        for field, value in (
            ("repository_id", 101),
            ("workflow_id", 201),
            ("actor_id", 301),
            ("repository_id", True),
            ("workflow_id", "200"),
            ("actor_id", 0),
            ("path", ".github/workflows/recreated.yml"),
            ("ref", "refs/heads/feature"),
            ("head_sha", "b" * 40),
            ("event", "pull_request"),
            ("status", "queued"),
            ("conclusion", "success"),
            ("id", False),
        ):
            with self.subTest(field=field):
                self.setUp_candidate()
                self.snapshot["current"][field] = value
                self.assert_blocked()

    def test_any_extra_history_record_rejects_all_outcomes(self):
        for outcome in ("failure", "cancelled", "queued", "success", None):
            with self.subTest(outcome=outcome):
                self.setUp_candidate()
                prior = copy.deepcopy(self.snapshot["current"])
                prior.update(id=399, conclusion=outcome)
                self.snapshot["history"]["workflow_runs"].append(prior)
                self.snapshot["history"]["total_count"] = 2
                self.assert_blocked()

    def test_absent_inconsistent_partial_history(self):
        mutations = (
            lambda s: s.update(current=None),
            lambda s: s.update(history={}),
            lambda s: s.update(next_page="page2"),
            lambda s: s.update(truncated=True),
            lambda s: s.update(http_status=403),
            lambda s: s.update(evidence_kind=None),
            lambda s: s.update(evidence_kind="github-authenticated"),
            lambda s: s["history"].update(total_count=2),
            lambda s: s["history"].update(total_count=True),
            lambda s: s["history"].update(workflow_runs=[]),
            lambda s: s["history"]["workflow_runs"][0].update(run_number=True),
            lambda s: s["history"]["workflow_runs"][0].update(
                head_sha="b" * 40
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp_candidate()
                mutate(self.snapshot)
                self.assert_blocked()

    def test_invalid_enrollment_and_nonrenewable_window(self):
        for field, value in (
            ("valid_from", 1201),
            ("expires_at", 1200),
            ("expires_at", 87401),
            ("valid_from", True),
            ("workflow_id", 0),
            ("head_sha", "A" * 40),
        ):
            with self.subTest(field=field, value=value):
                self.setUp_candidate()
                self.enrollment[field] = value
                self.assert_blocked()
        self.setUp_candidate()
        self.snapshot["current"]["created_at"] = 999
        self.assert_blocked()

    def test_grant_never_infers_missing_authority(self):
        for key in self.grant:
            with self.subTest(key=key):
                self.setUp_candidate()
                del self.grant[key]
                self.assert_blocked()
        for key, value in (
            ("request_sha256", "0" * 64),
            ("endpoint", "https://example.org"),
            ("model", "other"),
            ("max_calls", True),
            ("max_calls", 2),
            ("max_micro_usd", 1),
            ("max_total_input_tokens", 100),
            ("max_total_output_tokens", 32),
            ("expires_at", 2001),
            ("admission_mode", "paid"),
        ):
            with self.subTest(key=key, value=value):
                self.setUp_candidate()
                self.grant[key] = value
                self.assert_blocked()

    def test_no_provider_transport_allowed(self):
        self.transport.evidence_kind = "provider-runtime"
        self.assert_blocked()

    def test_http_errors_and_transport_failure_are_terminal_unknown(self):
        for status in (201, 301, 400, 429, 500, True):
            with self.subTest(status=status):
                self.setUp_candidate()
                self.transport.status = status
                self.assertEqual(self.run_fixture()["status"], "UNKNOWN")
                self.assertEqual(self.run_fixture()["status"], "NOT_RUN")
                self.assertEqual(len(self.transport.calls), 1)
        self.setUp_candidate()
        self.transport.error = TimeoutError("PRIVATE_EXCEPTION_SENTINEL")
        self.assertEqual(
            self.run_fixture(),
            {"status": "UNKNOWN", "evidence_kind": "fabricated-offline"},
        )

    def test_timeout_backwards_clock_and_expiry_are_unknown(self):
        for ended in (1199, 1220, 2000, True):
            with self.subTest(ended=ended):
                self.setUp_candidate()
                values = iter((1200, ended))
                self.assertEqual(
                    self.run_fixture(lambda: next(values))["status"], "UNKNOWN"
                )

    def test_invalid_wire_shapes_are_unknown_and_redacted(self):
        for body in (
            b"not-json",
            b"\xff",
            b"{}",
            b"[]",
            b"{" * 2000,
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
            b"x" * 16385,
        ):
            with self.subTest(body=body[:20]):
                self.setUp_candidate()
                self.transport.body = body
                self.assertEqual(self.run_fixture()["status"], "UNKNOWN")

    def test_wrong_model_and_usage_never_produce_observation(self):
        mutations = (
            lambda r: r.update(modelVersion="wrong"),
            lambda r: r["usageMetadata"].update(promptTokenCount=True),
            lambda r: r["usageMetadata"].update(promptTokenCount=0),
            lambda r: r["usageMetadata"].update(candidatesTokenCount=-1),
            lambda r: r["usageMetadata"].update(thoughtsTokenCount=32),
            lambda r: r["usageMetadata"].update(totalTokenCount=14),
            lambda r: r["usageMetadata"].update(cachedContentTokenCount=1),
            lambda r: r["usageMetadata"].pop("thoughtsTokenCount"),
            lambda r: r.update(candidates=[]),
            lambda r: r["candidates"][0].update(finishReason="MAX_TOKENS"),
            lambda r: r["candidates"][0].update(index=False),
            lambda r: r["candidates"][0]["content"]["parts"][0].update(
                functionCall={"name": "not-allowed"}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp_candidate()
                mutate(self.response)
                self.transport.body = json.dumps(self.response).encode()
                self.assertEqual(
                    self.run_fixture(),
                    {
                        "status": "UNKNOWN",
                        "evidence_kind": "fabricated-offline",
                    },
                )


class FakeHTTPSConnection:
    def __init__(self, body=b"{}", status=200):
        self.body = body
        self.status = status
        self.version = 11
        self.sock = self
        self.requests = []
        self.connected = 0
        self.closed = 0
        self.response_closed = 0
        self.failure = None

    def set_debuglevel(self, value):
        self.debuglevel = value

    def settimeout(self, value):
        self.timeout = value

    def connect(self):
        self.connected += 1

    def request(self, method, path, **kwargs):
        self.requests.append(
            (method, path, kwargs["body"], dict(kwargs["headers"]))
        )

    def getresponse(self):
        connection = self

        class Response:
            status = connection.status
            version = 11

            def getheaders(self):
                return [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(connection.body))),
                    ("Location", "https://example.invalid/never-follow"),
                ]

            def read1(self, amount):
                if connection.failure == "read":
                    raise SystemExit("PRIVATE_SENTINEL")
                chunk, connection.body = (
                    connection.body[:amount],
                    connection.body[amount:],
                )
                return chunk

            def close(self):
                connection.response_closed += 1
                if connection.failure == "close":
                    raise SystemExit("PRIVATE_SENTINEL")

        return Response()

    def close(self):
        self.closed += 1


class UnselectedWireTest(unittest.TestCase):
    def setUp(self):
        for target in (
            "socket.socket",
            "socket.create_connection",
            "http.client.HTTPSConnection",
        ):
            patch = mock.patch(
                target, side_effect=AssertionError("real network")
            )
            patch.start()
            self.addCleanup(patch.stop)
        self.connection = FakeHTTPSConnection()
        self.factories = []
        self.borrows = 0
        self.guards = 0

    def make(self, failure=None):
        def factory(host, port, *, timeout, context):
            self.factories.append((host, port, context))
            if failure == "factory":
                raise SystemExit("PRIVATE_SENTINEL")
            return self.connection

        def borrow(**kwargs):
            self.borrows += 1
            if failure == "borrow":
                raise SystemExit("PRIVATE_SENTINEL")
            return "synthetic-only-key"

        def guard(**kwargs):
            self.guards += 1
            self.assertEqual(kwargs["endpoint"], diagnostic.ENDPOINT)
            self.assertEqual(kwargs["body"], diagnostic.REQUEST)
            if failure == "guard":
                raise SystemExit("PRIVATE_SENTINEL")

        return diagnostic.UnselectedHTTPSWire(
            borrow, guard, connection_factory=factory
        )

    def exchange(self, wire):
        return wire.exchange(diagnostic.ENDPOINT, diagnostic.REQUEST, 20)

    def assert_sanitized(self, wire):
        with self.assertRaises(ValueError) as caught:
            self.exchange(wire)
        self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        with self.assertRaises(ValueError):
            self.exchange(wire)

    def test_reuses_real_transport_only_with_fake_connection(self):
        wire = self.make()
        self.assertEqual(self.exchange(wire), (200, b"{}"))
        host, port, context = self.factories[0]
        self.assertEqual(
            (host, port), ("generativelanguage.googleapis.com", 443)
        )
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertIsNone(context.keylog_filename)
        self.assertEqual(self.borrows, 1)
        self.assertGreaterEqual(self.guards, 6)
        method, path, body, headers = self.connection.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path, "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        )
        self.assertEqual(body, diagnostic.REQUEST)
        self.assertEqual(headers["x-goog-api-key"], "synthetic-only-key")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("?", path)
        self.assertEqual(self.connection.auto_open, 0)
        self.assertEqual(self.connection.closed, 1)
        self.assertEqual(self.connection.response_closed, 1)
        self.assert_sanitized(wire)
        self.assertEqual(len(self.factories), 1)

    def test_denied_guard_has_no_connection_or_borrow(self):
        self.assert_sanitized(self.make("guard"))
        self.assertEqual(self.factories, [])
        self.assertEqual(self.borrows, 0)
        self.assertEqual(self.connection.requests, [])

    def test_factory_borrow_read_and_close_failures_are_sanitized(self):
        for failure in ("factory", "borrow", "read", "close"):
            with self.subTest(failure=failure):
                self.connection = FakeHTTPSConnection()
                self.connection.failure = failure
                self.assert_sanitized(self.make(failure))
                if failure != "factory":
                    self.assertEqual(self.connection.closed, 1)

    def test_redirect_and_oversized_response_do_not_retry(self):
        for status, size in ((302, 2), (200, 16385), (200, 131073)):
            with self.subTest(status=status, size=size):
                self.connection = FakeHTTPSConnection(b"x" * size, status)
                before = len(self.factories)
                self.assert_sanitized(self.make())
                self.assertEqual(len(self.factories), before + 1)
                self.assertEqual(len(self.connection.requests), 1)
                self.assertEqual(self.connection.closed, 1)

    def test_wrong_request_burns_before_import_or_effect(self):
        wire = self.make()
        with self.assertRaises(ValueError):
            wire.exchange(
                diagnostic.ENDPOINT + "?x=invalid", diagnostic.REQUEST, 20
            )
        self.assert_sanitized(wire)
        self.assertEqual(self.factories, [])

    def test_no_semantic_asset_reads_on_lazy_import_or_send(self):
        for name in list(sys.modules):
            if name == "cartreadback_app" or name.startswith(
                "cartreadback_app."
            ):
                del sys.modules[name]
        with (
            mock.patch(
                "builtins.open", side_effect=AssertionError("asset read")
            ),
            mock.patch("io.open", side_effect=AssertionError("asset read")),
        ):
            self.assertEqual(self.exchange(self.make()), (200, b"{}"))

    def test_missing_runtime_module_is_sanitized_without_effect(self):
        with mock.patch.dict(
            sys.modules, {"cartreadback_app.gemini_http": None}
        ):
            self.assert_sanitized(self.make())
        self.assertEqual(self.factories, [])


if __name__ == "__main__":
    unittest.main()
