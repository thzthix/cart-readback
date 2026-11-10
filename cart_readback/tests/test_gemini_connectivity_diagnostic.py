"""Fake-only tests of the actual one-shot client and branch workflow contract."""

import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
import os
import pathlib
import re
import signal
import socket
import ssl
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATH = ROOT / "cart_readback/scripts/gemini_connectivity_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("diagnostic", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = 1700000100


def workflow_parts():
    """Extract only this reviewed literal block, without a YAML dependency."""
    source = (ROOT / probe.WORKFLOW_PATH).read_text()
    marker = "\n  gemini-connectivity:\n"
    if source.count(marker) != 1:
        raise AssertionError("unexpected diagnostic block")
    job = source.split(marker)[1]
    final_marker = "    - name: One guarded Google generation POST; no retry\n"
    if job.count(final_marker) != 1:
        raise AssertionError("unexpected final step")
    fetch, final = job.split(final_marker)
    begin, end = "        python - <<'PYTHON'\n", "        PYTHON\n"
    if fetch.count(begin) != 1 or fetch.count(end) != 1:
        raise AssertionError("unexpected fetch heredoc")
    code = textwrap.dedent(fetch.split(begin)[1].split(end)[0])
    pin = re.findall(
        r"^        PROBE_SOURCE_SHA256: ([0-9a-f]{64})$", final, re.MULTILINE
    )
    if len(pin) != 1:
        raise AssertionError("unexpected source pin")
    return source, job, fetch, final, code, pin[0]


class TrackedEnv(dict):
    def __init__(self, *args):
        super().__init__(*args)
        self.borrowed = 0

    def pop(self, key, *default):
        if key == "GEMINI_KEY":
            self.borrowed += 1
        return super().pop(key, *default)


def envelope():
    return {
        "modelVersion": probe.MODEL,
        "responseId": "synthetic_id",
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
                    "parts": [{"text": "PRIVATE_TEXT"}],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
    }


def observed_envelope():
    return {
        "model_version": probe.MODEL,
        "usage": {
            "input_tokens": 12,
            "answer_tokens": 2,
            "thought_tokens": 1,
            "total_tokens": 15,
        },
        "finish_reason": "STOP",
        "has_text": True,
    }


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
            (method, path, kwargs.get("body"), dict(kwargs["headers"]))
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


class NativeFakeSocket:
    def __init__(self, wire):
        self.wire, self.sent = wire, []

    def makefile(self, *args):
        return io.BytesIO(self.wire)

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.sent.append(bytes(data))

    def close(self):
        pass


class NativeFakeConnection(http.client.HTTPConnection):
    def __init__(self, wire):
        super().__init__("generativelanguage.googleapis.com")
        self.socket = NativeFakeSocket(wire)

    def connect(self):
        self.sock = self.socket


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for target in (
            "socket.socket",
            "socket.create_connection",
            "http.client.HTTPSConnection",
        ):
            patch = mock.patch(
                target, side_effect=AssertionError("real network forbidden")
            )
            patch.start()
            self.addCleanup(patch.stop)
        self.env = self.environment(self.directory.name)
        self.connection = FakeHTTPSConnection(json.dumps(envelope()).encode())
        self.factories = []

    def environment(self, directory):
        return TrackedEnv(
            {
                **probe.EXPECTED_CONTEXT,
                "GITHUB_SHA": "a" * 40,
                "GITHUB_WORKFLOW_SHA": "a" * 40,
                "PROBE_REVIEWED_SHA": "a" * 40,
                "GITHUB_RUN_ID": "12345",
                "PROBE_WINDOW_START": str(NOW - 100),
                "PROBE_WINDOW_END": str(NOW + 100),
                "PROBE_SOURCE_SHA256": hashlib.sha256(
                    PATH.read_bytes()
                ).hexdigest(),
                "RUNNER_TEMP": directory,
                "GEMINI_KEY": "synthetic-only-key",
            }
        )

    def factory(self, host, port, **kwargs):
        self.factories.append((host, port, kwargs))
        return self.connection

    def run_probe(self, **kwargs):
        return probe.execute(
            self.env,
            connection_factory=self.factory,
            wall=lambda: NOW,
            monotonic=lambda: 100,
            **kwargs,
        )

    def test_exact_one_post_claim_and_sanitized_receipt(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.run_probe()
        self.assertEqual(
            result,
            {
                "status": "RESPONSE_VALIDATED",
                "model": probe.MODEL,
                "input_tokens": 12,
                "output_tokens": 3,
                "total_tokens": 15,
                "finish_reason": "STOP",
                "answer_tokens": 2,
                "thought_tokens": 1,
                "has_text": True,
            },
        )
        self.assertNotIn("PRIVATE_TEXT", json.dumps(result) + output.getvalue())
        self.assertNotIn("synthetic-only-key", json.dumps(result))
        self.assertEqual(self.env.borrowed, 1)
        self.assertNotIn("GEMINI_KEY", self.env)
        self.assertEqual(
            self.connection.requests[0][:3],
            (
                "POST",
                "/v1beta/models/gemini-3.5-flash-lite:generateContent",
                probe.REQUEST,
            ),
        )
        self.assertEqual(
            self.connection.requests[0][3]["x-goog-api-key"],
            "synthetic-only-key",
        )
        self.assertNotIn("Authorization", self.connection.requests[0][3])
        self.assertEqual(self.connection.auto_open, 0)
        self.assertEqual(self.connection.closed, 1)
        self.assertEqual(self.connection.response_closed, 1)
        self.assertEqual(
            len(list(pathlib.Path(self.directory.name).glob("*.claim"))), 1
        )
        self.assertEqual(
            self.run_probe(), {"status": "NOT_RUN", "phase": "claim"}
        )
        self.assertEqual(len(self.factories), 1)

    def test_all_context_mismatches_block_before_key_or_factory(self):
        mutations = [(k, "wrong") for k in probe.EXPECTED_CONTEXT]
        mutations += [
            ("GITHUB_RUN_NUMBER", "1"),
            ("GITHUB_RUN_NUMBER", "2"),
            ("GITHUB_RUN_NUMBER", "3"),
            ("GITHUB_RUN_NUMBER", "4"),
            ("GITHUB_RUN_NUMBER", "6"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_SHA", "b" * 40),
            ("GITHUB_WORKFLOW_SHA", "b" * 40),
            ("PROBE_REVIEWED_SHA", "a;bad"),
            ("GITHUB_RUN_ID", "../bad"),
            ("PROBE_WINDOW_START", str(NOW + 1)),
            ("PROBE_WINDOW_END", str(NOW)),
            ("PROBE_WINDOW_END", str(NOW + 1000)),
            ("PROBE_SOURCE_SHA256", "0" * 64),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                self.env = self.environment(self.directory.name)
                self.env[key] = value
                self.assertEqual(
                    self.run_probe(),
                    {"status": "NOT_RUN", "phase": "preflight"},
                )
                self.assertEqual(self.env.borrowed, 0)
                self.assertEqual(self.factories, [])

    def test_only_new_run_five_attempt_one_has_a_local_slot(self):
        self.assertEqual(probe.EXPECTED_CONTEXT["GITHUB_RUN_NUMBER"], "5")
        self.assertEqual(probe.EXPECTED_CONTEXT["GITHUB_RUN_ATTEMPT"], "1")
        job = workflow_parts()[1]
        self.assertIn(
            "&& github.run_number == 5 && github.run_attempt == 1 }}",
            job,
        )
        self.assertNotIn("github.run_number == 1", job)
        self.assertNotIn("github.run_number == 2", job)
        self.assertNotIn("github.run_number == 3", job)
        self.assertNotIn("github.run_number == 4", job)
        config = json.loads(probe.REQUEST)["generationConfig"]
        self.assertEqual(
            config,
            {
                "temperature": 0,
                "maxOutputTokens": 256,
                "thinkingConfig": {"thinkingLevel": "MINIMAL"},
            },
        )

    def test_fetch_rejects_spent_and_other_slots_before_token_or_io(self):
        code = workflow_parts()[4]
        for number, attempt in (
            ("1", "1"),
            ("1", "2"),
            ("2", "1"),
            ("2", "2"),
            ("3", "1"),
            ("3", "2"),
            ("4", "1"),
            ("4", "2"),
            ("5", "2"),
            ("6", "1"),
            ("05", "1"),
            ("5", "01"),
        ):
            with (
                self.subTest(number=number, attempt=attempt),
                tempfile.TemporaryDirectory() as directory,
            ):
                env = self.environment(directory)
                env.pop("GEMINI_KEY")
                env["GITHUB_RUN_NUMBER"] = number
                env["GITHUB_RUN_ATTEMPT"] = attempt
                env["GITHUB_TOKEN"] = "synthetic-github-token"
                conn = FakeHTTPSConnection(PATH.read_bytes())
                with (
                    mock.patch.object(os, "environ", env),
                    mock.patch.object(
                        http.client, "HTTPSConnection", return_value=conn
                    ),
                    mock.patch("time.time", return_value=NOW),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaises(SystemExit):
                        exec(compile(code, "workflow-fetch", "exec"), {})
                self.assertEqual(env["GITHUB_TOKEN"], "synthetic-github-token")
                self.assertEqual(conn.connected, 0)
                self.assertEqual(conn.requests, [])
                self.assertFalse(
                    pathlib.Path(
                        directory, "cartreadback-gemini-probe.py"
                    ).exists()
                )

    def test_fifth_slot_is_new_and_never_replays_old_or_later_attempts(self):
        for number, attempt in (
            ("1", "1"),
            ("2", "1"),
            ("3", "1"),
            ("4", "1"),
            ("5", "1"),
            ("5", "2"),
            ("6", "1"),
        ):
            with (
                self.subTest(number=number, attempt=attempt),
                tempfile.TemporaryDirectory() as directory,
            ):
                env = self.environment(directory)
                env["GITHUB_RUN_NUMBER"] = number
                env["GITHUB_RUN_ATTEMPT"] = attempt
                conn = FakeHTTPSConnection(json.dumps(envelope()).encode())
                factory = mock.Mock(return_value=conn)
                result = probe.execute(
                    env,
                    connection_factory=factory,
                    wall=lambda: NOW,
                    monotonic=lambda: 100,
                )
                admitted = (number, attempt) == ("5", "1")
                self.assertEqual(
                    result["status"],
                    "RESPONSE_VALIDATED" if admitted else "NOT_RUN",
                )
                self.assertEqual(factory.call_count, int(admitted))
                self.assertEqual(env.borrowed, int(admitted))
                self.assertEqual(len(conn.requests), int(admitted))
                if not admitted:
                    self.assertEqual(result["phase"], "preflight")

    def test_identity_constants_and_request_digest(self):
        self.assertEqual(
            probe.EXPECTED_CONTEXT["GITHUB_REPOSITORY_ID"], "1443556432"
        )
        self.assertEqual(
            probe.EXPECTED_CONTEXT["GITHUB_REPOSITORY_OWNER_ID"], "95135403"
        )
        self.assertEqual(
            probe.REQUEST_BODY_SHA256,
            "ab74cc1cff7aa2621c18d24d3827a9ecb465edafe698648a63593101a91eadb9",
        )
        self.assertEqual(probe.METHOD, "POST")
        self.assertEqual(
            probe.REQUEST_PATH,
            "/v1beta/models/gemini-3.5-flash-lite:generateContent",
        )
        self.assertEqual(
            probe.REQUEST_SHA256,
            "25afd36c58e4b28fb79900ec7b5c42bf39c5d893120c03be57b61355b81d84a9",
        )
        self.assertEqual(probe.MAX_INPUT_RESERVATION, 1048576)
        self.assertEqual(probe.MAX_OUTPUT_RESERVATION, 2048)

    def test_fixed_tls_and_no_ambient_proxy_key_or_keylog(self):
        with mock.patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://invalid",
                "SSLKEYLOGFILE": self.directory.name + "/no-keylog",
                "GEMINI_API_KEY": "alternate-not-used",
            },
        ):
            self.assertEqual(self.run_probe()["status"], "RESPONSE_VALIDATED")
        host, port, args = self.factories[0]
        self.assertEqual(
            (host, port), ("generativelanguage.googleapis.com", 443)
        )
        context = args["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertIsNone(context.keylog_filename)
        self.assertFalse(
            pathlib.Path(self.directory.name, "no-keylog").exists()
        )

    def test_falsey_explicit_factory_is_used_without_truthiness(self):
        subject = self

        class Factory:
            def __bool__(self):
                raise SystemExit("PRIVATE_ERROR")

            def __call__(self, *args, **kwargs):
                return subject.factory(*args, **kwargs)

        result = probe.execute(
            self.env,
            connection_factory=Factory(),
            wall=lambda: NOW,
            monotonic=lambda: 100,
        )
        self.assertEqual(result["status"], "RESPONSE_VALIDATED")

    def test_missing_or_malformed_key_burns_without_post(self):
        self.env["GEMINI_KEY"] = "invalid\nkey"
        self.assertEqual(
            self.run_probe(),
            {
                "status": "UNKNOWN",
                "phase": "credential",
                "reason": "CREDENTIAL_REJECTED",
            },
        )
        self.assertEqual(self.connection.requests, [])
        self.assertEqual(self.env.borrowed, 1)
        self.assertEqual(
            self.run_probe(), {"status": "NOT_RUN", "phase": "claim"}
        )

    def test_opaque_dotted_and_long_public_keys_reach_one_fake_post_verbatim(
        self,
    ):
        for public_key in (
            "AQ.synthetic-only-key",
            "AQ." + "synthetic-" * 40,
            "p" * probe.MAX_CREDENTIAL_BYTES,
            "public.!#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
        ):
            with (
                self.subTest(),
                tempfile.TemporaryDirectory() as directory,
            ):
                # This is the old local restriction, not Google's contract.
                self.assertIsNone(
                    re.fullmatch(r"[A-Za-z0-9_-]{1,256}", public_key)
                )
                self.env = self.environment(directory)
                self.env["GEMINI_KEY"] = public_key
                self.connection = FakeHTTPSConnection(
                    json.dumps(envelope()).encode()
                )
                result = self.run_probe()
                self.assertEqual(result["status"], "RESPONSE_VALIDATED")
                self.assertEqual(len(self.connection.requests), 1)
                self.assertEqual(
                    self.connection.requests[0][3]["x-goog-api-key"], public_key
                )
                self.assertNotIn(public_key, json.dumps(result))
                self.assertNotIn("GEMINI_KEY", self.env)

    def test_missing_unsafe_or_overlocalbound_keys_never_reach_post(self):
        for public_key in (
            None,
            "",
            " public",
            "public ",
            "public\tkey",
            "public\r\nInjected: fixture",
            "public\x00key",
            "public\x1fkey",
            "public\x7fkey",
            "public\u00e9key",
            "public\udcffkey",
            "p" * (probe.MAX_CREDENTIAL_BYTES + 1),
        ):
            with (
                self.subTest(),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                if public_key is None:
                    del self.env["GEMINI_KEY"]
                else:
                    self.env["GEMINI_KEY"] = public_key
                self.connection = FakeHTTPSConnection()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = self.run_probe()
                self.assertEqual(
                    result,
                    {
                        "status": "UNKNOWN",
                        "phase": "credential",
                        "reason": "CREDENTIAL_REJECTED",
                    },
                )
                self.assertEqual(self.connection.requests, [])
                self.assertEqual(output.getvalue(), "")

    def test_expiry_after_connect_prevents_borrow_and_post(self):
        now = [NOW]
        self.connection.connect = lambda: now.__setitem__(0, NOW + 101)
        result = probe.execute(
            self.env,
            connection_factory=self.factory,
            wall=lambda: now[0],
            monotonic=lambda: 100,
        )
        self.assertEqual(result, {"status": "UNKNOWN", "phase": "connect"})
        self.assertEqual(self.env.borrowed, 0)
        self.assertEqual(self.connection.requests, [])

    def test_credential_reasons_separate_local_failures_without_private_data(
        self,
    ):
        cases = {
            "lookup": "CREDENTIAL_LOOKUP_FAILED",
            "rejected": "CREDENTIAL_REJECTED",
            "context": "CONTEXT_REJECTED",
            "window": "CONTEXT_REJECTED",
            "deadline": "DEADLINE_EXPIRED",
            "claim-stat": "CLAIM_STAT_FAILED",
            "claim-identity": "CLAIM_CHANGED",
            "socket-timeout": "SOCKET_TIMEOUT_SETUP_FAILED",
            "interrupt": "INTERRUPTED",
            "exit": "INTERRUPTED",
            "unexpected": "UNEXPECTED_LOCAL_ERROR",
        }
        for case, expected_reason in cases.items():
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as directory,
            ):
                clock = [NOW, 100]
                original = self.environment(directory)
                claim = pathlib.Path(
                    directory, "cartreadback-gemini-12345.claim"
                )

                class Env(TrackedEnv):
                    def pop(self, key, *default):
                        if case == "lookup":
                            raise RuntimeError("PRIVATE_ERROR")
                        value = super().pop(key, *default)
                        if case == "context":
                            self["GITHUB_REF"] = "wrong"
                        elif case == "window":
                            clock[0] = NOW + 101
                        elif case == "deadline":
                            clock[1] = 121
                        elif case == "claim-stat":
                            claim.rename(claim.with_suffix(".retained"))
                        elif case == "claim-identity":
                            claim.rename(claim.with_suffix(".retained"))
                            claim.write_bytes(b"public replacement fixture")
                        return value

                env = Env(original)
                if case == "rejected":
                    env["GEMINI_KEY"] = "PRIVATE_ERROR invalid fixture"
                conn = FakeHTTPSConnection(json.dumps(envelope()).encode())
                calls = []

                def settimeout(value):
                    calls.append(value)
                    if len(calls) != 2:
                        return
                    if case == "socket-timeout":
                        raise OSError("PRIVATE_ERROR")
                    if case == "interrupt":
                        raise KeyboardInterrupt("PRIVATE_ERROR")
                    if case == "exit":
                        raise SystemExit("PRIVATE_ERROR")
                    if case == "unexpected":
                        raise RuntimeError("PRIVATE_ERROR")

                conn.settimeout = settimeout
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = probe.execute(
                        env,
                        connection_factory=lambda *a, **k: conn,
                        wall=lambda: clock[0],
                        monotonic=lambda: clock[1],
                    )
                self.assertEqual(
                    result,
                    {
                        "status": "UNKNOWN",
                        "phase": "credential",
                        "reason": expected_reason,
                    },
                )
                self.assertEqual(conn.requests, [])
                self.assertEqual(conn.closed, 1)
                for private in ("PRIVATE_ERROR", "synthetic-only-key"):
                    self.assertNotIn(
                        private, json.dumps(result) + output.getvalue()
                    )

    def test_credential_reason_survives_cleanup_failure(self):
        self.env["GEMINI_KEY"] = "invalid fixture"
        self.connection.close = mock.Mock(side_effect=OSError("PRIVATE_ERROR"))
        self.assertEqual(
            self.run_probe(),
            {
                "status": "UNKNOWN",
                "phase": "credential",
                "reason": "CREDENTIAL_REJECTED",
                "cleanup_failed": True,
            },
        )

    def test_failure_reason_accepts_only_fixed_enum_members(self):
        for unsafe in ("PRIVATE_ERROR", None, object()):
            self.assertEqual(
                probe._failure_receipt("UNKNOWN", "credential", reason=unsafe),
                {"status": "UNKNOWN", "phase": "credential"},
            )

    def test_http_redirect_errors_fail_without_retry(self):
        for status in (201, 301, 302, 307, 308, 400, 429, 500):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(b"PRIVATE_ERROR", status)
                self.assertEqual(
                    self.run_probe(),
                    {
                        "status": "UNKNOWN",
                        "phase": "headers",
                        "http_status": status,
                    },
                )
                self.assertEqual(len(self.connection.requests), 1)
                self.assertEqual(self.connection.closed, 1)

    def test_unvalidated_schema_is_contact_only_and_oversize_stays_unknown(
        self,
    ):
        bodies = [
            (b"PRIVATE_ERROR", "JSON_INVALID", {}),
            (b"x" * 16385, None, {}),
            (b'{"a":1,"a":2}', "JSON_INVALID", {}),
            (b'{"a":NaN}', "JSON_INVALID", {}),
        ]
        for field, value, reason in (
            ("modelVersion", "wrong", "MODEL_VERSION_UNSUPPORTED"),
            ("totalTokenCount", 1, "USAGE_INCONSISTENT"),
            ("promptTokenCount", True, "USAGE_INVALID"),
            ("thoughtsTokenCount", 40, "USAGE_INCONSISTENT"),
        ):
            data, facts = envelope(), observed_envelope()
            if field == "modelVersion":
                data[field] = value
                del facts["model_version"]
                facts["model_category"] = "UNSUPPORTED"
            else:
                data["usageMetadata"][field] = value
                name = {
                    "totalTokenCount": "total_tokens",
                    "promptTokenCount": "input_tokens",
                    "thoughtsTokenCount": "thought_tokens",
                }[field]
                if type(value) is bool:
                    del facts["usage"][name]
                else:
                    facts["usage"][name] = value
            bodies.append((json.dumps(data).encode(), reason, facts))
        for body, reason, facts in bodies:
            with self.subTest(), tempfile.TemporaryDirectory() as directory:
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(body)
                expected = {
                    "status": "UNKNOWN"
                    if reason is None
                    else "HTTP_200_UNVALIDATED",
                    "phase": "headers" if reason is None else "body",
                    "http_status": 200,
                }
                if reason is not None:
                    expected["response_reason"] = reason
                if facts:
                    expected["observed"] = facts
                self.assertEqual(self.run_probe(), expected)

    def test_cancel_read_cleanup_and_factory_failures_are_sanitized(self):
        for failure in ("read", "close", "factory"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(b"{}")
                self.connection.failure = failure

                def factory(*args, **kwargs):
                    if failure == "factory":
                        raise SystemExit("PRIVATE_ERROR")
                    return self.connection

                self.assertEqual(
                    probe.execute(
                        self.env,
                        connection_factory=factory,
                        wall=lambda: NOW,
                        monotonic=lambda: 100,
                    ),
                    (
                        {"status": "UNKNOWN", "phase": "connect"}
                        if failure == "factory"
                        else {
                            "status": "UNKNOWN",
                            "phase": "body",
                            "http_status": 200,
                            **(
                                {
                                    "cleanup_failed": True,
                                    "response_reason": "MODEL_VERSION_UNSUPPORTED",
                                    "observed": {
                                        "model_category": "UNSUPPORTED",
                                        "has_text": False,
                                        "finish_category": "NO_CANDIDATE",
                                    },
                                }
                                if failure == "close"
                                else {}
                            ),
                        }
                    ),
                )

    def test_late_read_never_becomes_success(self):
        ticks = iter((100, 100, 100, 100, 100, 100, 100, 100, 121, 121, 121))
        result = probe.execute(
            self.env,
            connection_factory=self.factory,
            wall=lambda: NOW,
            monotonic=lambda: next(ticks),
        )
        self.assertEqual(result["status"], "UNKNOWN")

    def test_main_sanitizes_signal_and_restores_handler(self):
        before = signal.getsignal(signal.SIGTERM)
        self.connection.getresponse = lambda: os.kill(
            os.getpid(), signal.SIGTERM
        )
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env, clear=True),
            mock.patch.object(
                probe.http.client, "HTTPSConnection", self.factory
            ),
            mock.patch.object(probe.time, "time", lambda: NOW),
            contextlib.redirect_stdout(output),
        ):
            # execute's default wall is bound at definition; inject the test clock.
            original = probe.execute
            with mock.patch.object(
                probe,
                "execute",
                lambda env: original(
                    env,
                    connection_factory=self.factory,
                    wall=lambda: NOW,
                    monotonic=lambda: 100,
                ),
            ):
                self.assertEqual(probe.main(), 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "UNKNOWN", "phase": "headers"},
        )
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_failure_receipts_distinguish_safe_phases_and_cleanup(self):
        def fail(*args, **kwargs):
            raise SystemExit("PRIVATE_TEXT synthetic-only-key PRIVATE_ERROR")

        for phase in (
            "connect",
            "credential",
            "request-attempt",
            "headers",
            "body",
            "cleanup",
        ):
            with (
                self.subTest(phase=phase),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(
                    json.dumps(envelope()).encode()
                )
                if phase == "connect":
                    self.connection.connect = fail
                elif phase == "credential":
                    self.env["GEMINI_KEY"] = "PRIVATE_ERROR invalid key"
                elif phase == "request-attempt":
                    self.connection.request = fail
                elif phase == "headers":
                    self.connection.getresponse = fail
                elif phase == "body":
                    self.connection.failure = "read"
                else:
                    self.connection.failure = "close"
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = self.run_probe()
                expected = {
                    "status": "UNKNOWN",
                    "phase": "body" if phase == "cleanup" else phase,
                }
                if phase == "credential":
                    expected["reason"] = "CREDENTIAL_REJECTED"
                if phase in ("body", "cleanup"):
                    expected["http_status"] = 200
                if phase == "cleanup":
                    expected["cleanup_failed"] = True
                    expected["observed"] = observed_envelope()
                self.assertEqual(result, expected)
                for private in (
                    "PRIVATE_TEXT",
                    "PRIVATE_ERROR",
                    "synthetic-only-key",
                ):
                    self.assertNotIn(
                        private, json.dumps(result) + output.getvalue()
                    )
                self.assertNotIn("model", result)
                self.assertNotIn("input_tokens", result)

    def test_only_exact_received_http_status_survives_failure(self):
        for status in (True, 200.0, "200", 0, 999, 429):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(b"PRIVATE_ERROR", status)
                expected = {"status": "UNKNOWN", "phase": "headers"}
                if status == 429:
                    expected["http_status"] = 429
                self.assertEqual(self.run_probe(), expected)

    def test_main_unavailable_fallback_is_sanitized(self):
        output = io.StringIO()
        with (
            mock.patch.object(
                probe,
                "execute",
                side_effect=SystemExit("PRIVATE_ERROR synthetic-only-key"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(probe.main(), 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "UNKNOWN", "phase": "unavailable"},
        )

    def test_workflow_only_final_step_has_google_key(self):
        source, job, fetch, final, code, pin = workflow_parts()
        self.assertIn("\non:\n  workflow_dispatch:\n", source)
        self.assertNotIn("\n  push:", source)
        self.assertNotIn("\n  pull_request:", source)
        self.assertIn("\npermissions:\n  contents: read\n", source)
        self.assertIn("    timeout-minutes: 2\n", job)
        self.assertIn(
            "      group: cartreadback-gemini-connectivity-one-shot\n      cancel-in-progress: false\n",
            job,
        )
        self.assertEqual(job.count("    - name:"), 2)
        self.assertNotIn("GEMINI_KEY", fetch)
        self.assertNotIn("GITHUB_TOKEN", final)
        self.assertIn("        GEMINI_KEY: ${{ secrets.GEMINI_KEY }}\n", final)
        self.assertEqual(pin, hashlib.sha256(PATH.read_bytes()).hexdigest())
        self.assertNotIn("uses:", job)
        self.assertIn(pin, code)

    def test_pinned_fetch_good_and_fail_closed(self):
        code = workflow_parts()[4]
        cases = [
            (200, PATH.read_bytes(), True),
            (302, b"redirect", False),
            (200, b"wronghash", False),
            (200, b"x" * 65537, False),
        ]
        for status, body, success in cases:
            with (
                self.subTest(status=status, size=len(body)),
                tempfile.TemporaryDirectory() as directory,
            ):
                env = self.environment(directory)
                env.pop("GEMINI_KEY")
                env["GITHUB_TOKEN"] = "synthetic-github-token"
                conn = FakeHTTPSConnection(body, status)
                with (
                    mock.patch.dict(os.environ, env, clear=True),
                    mock.patch.object(
                        http.client, "HTTPSConnection", return_value=conn
                    ),
                    mock.patch("time.time", return_value=NOW),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    if success:
                        exec(compile(code, "workflow-fetch", "exec"), {})
                    else:
                        with self.assertRaises(SystemExit):
                            exec(compile(code, "workflow-fetch", "exec"), {})
                target = pathlib.Path(directory, "cartreadback-gemini-probe.py")
                self.assertEqual(target.exists(), success)
                self.assertEqual(len(conn.requests), 1)
                self.assertEqual(conn.requests[0][0], "GET")
                self.assertNotIn("key", conn.requests[0][1])
                self.assertEqual(conn.closed, 1)
                if success:
                    self.assertEqual(target.read_bytes(), PATH.read_bytes())

    def test_reviewed_optional_usage_and_signature_fields(self):
        value = envelope()
        del value["usageMetadata"]["thoughtsTokenCount"]
        value["usageMetadata"]["totalTokenCount"] = 14
        value["usageMetadata"]["promptTokensDetails"] = [
            {"modality": "TEXT", "tokenCount": 12}
        ]
        value["usageMetadata"]["candidatesTokensDetails"] = [
            {"modality": "TEXT", "tokenCount": 2}
        ]
        value["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = (
            "c3ludGhldGlj"
        )
        accepted = probe._safe_observation(200, json.dumps(value).encode())
        self.assertEqual(accepted["output_tokens"], 2)
        self.assertNotIn("c3ludGhldGlj", json.dumps(accepted))
        mutations = [
            lambda v: v["usageMetadata"].update(totalTokenCount=15),
            lambda v: v["usageMetadata"]["promptTokensDetails"][0].update(
                modality="IMAGE"
            ),
            lambda v: v["usageMetadata"]["candidatesTokensDetails"][0].update(
                tokenCount=True
            ),
            lambda v: v["candidates"][0]["content"]["parts"][0].update(
                thoughtSignature=True
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = json.loads(json.dumps(value))
                mutate(changed)
                self.assertIsNone(
                    probe._safe_observation(200, json.dumps(changed).encode())
                )

    def test_actual_same_family_version_is_reported_without_model_fallback(
        self,
    ):
        for version in (
            probe.MODEL,
            probe.MODEL + "-001",
            probe.MODEL + "-20260721",
            probe.MODEL + "-2026-07-21",
            probe.MODEL + "-1.2",
        ):
            with self.subTest(version=version):
                value = envelope()
                value["modelVersion"] = version
                observed = probe._safe_observation(
                    200, json.dumps(value).encode()
                )
                self.assertEqual(observed["model"], version)
                self.assertEqual(observed["finish_reason"], "STOP")
        for version in (
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            probe.MODEL + "-pro",
            probe.MODEL + "-preview-07-21",
            probe.MODEL + "-exp",
            probe.MODEL + "-001extra",
            probe.MODEL + "-",
            probe.MODEL + "-" + "1" * 9,
            True,
            None,
        ):
            with self.subTest(version=version):
                value = envelope()
                value["modelVersion"] = version
                self.assertIsNone(
                    probe._safe_observation(200, json.dumps(value).encode())
                )

    def test_max_tokens_is_partial_generation_not_an_authentication_failure(
        self,
    ):
        value = envelope()
        value["candidates"][0]["finishReason"] = "MAX_TOKENS"
        self.connection = FakeHTTPSConnection(json.dumps(value).encode())
        result = self.run_probe()
        self.assertEqual(
            result,
            {
                "status": "GENERATION_PARTIAL_VALIDATED",
                "model": probe.MODEL,
                "input_tokens": 12,
                "output_tokens": 3,
                "total_tokens": 15,
                "finish_reason": "MAX_TOKENS",
                "answer_tokens": 2,
                "thought_tokens": 1,
                "has_text": True,
            },
        )
        self.assertEqual(len(self.connection.requests), 1)
        self.assertNotIn("PRIVATE_TEXT", json.dumps(result))
        for reason in ("SAFETY", "", [], None):
            value["candidates"][0]["finishReason"] = reason
            self.assertIsNone(
                probe._safe_observation(200, json.dumps(value).encode())
            )

    def response_fixture(self, value):
        with tempfile.TemporaryDirectory() as directory:
            self.env = self.environment(directory)
            self.connection = FakeHTTPSConnection(json.dumps(value).encode())
            result = self.run_probe()
            self.assertEqual(len(self.connection.requests), 1)
            self.assertNotIn("PRIVATE", json.dumps(result))
            return result

    def test_protojson_defaults_and_documented_optional_metadata(self):
        values = []
        value = envelope()
        del value["candidates"][0]["index"]
        values.append(value)
        value = envelope()
        value["candidates"][0]["avgLogprobs"] = -0.1
        values.append(value)
        value = envelope()
        value["promptFeedback"] = {"safetyRatings": []}
        values.append(value)
        value = envelope()
        value["usageMetadata"]["cachedContentTokenCount"] = 0
        value["usageMetadata"]["toolUsePromptTokenCount"] = 0
        values.append(value)
        value = envelope()
        value["candidates"][0]["content"]["parts"].append(
            {"text": "PRIVATE_MORE"}
        )
        values.append(value)
        value = envelope()
        value["responseId"] = "PRIVATE opaque id / \u2603"
        value["candidates"][0]["content"]["parts"][0].update(
            thought=False, thoughtSignature="PRIVATE opaque signature"
        )
        values.append(value)
        value = envelope()
        del value["usageMetadata"]["thoughtsTokenCount"]
        value["usageMetadata"]["totalTokenCount"] = 14
        del value["candidates"][0]["content"]["role"]
        values.append(value)
        value = envelope()
        value["usageMetadata"].update(
            promptTokenCount="1.2e1",
            candidatesTokenCount="2",
            thoughtsTokenCount=1.0,
        )
        value["candidates"][0]["index"] = None
        value["candidates"][0]["finishReason"] = 1
        values.append(value)
        for value in values:
            with self.subTest():
                result = self.response_fixture(value)
                self.assertEqual(result["status"], "RESPONSE_VALIDATED")
                self.assertEqual(result["model"], probe.MODEL)
                self.assertIs(result["has_text"], True)

    def test_thought_only_token_limit_preserves_default_zero_counts(self):
        value = envelope()
        value["usageMetadata"] = {
            "promptTokenCount": 12,
            "thoughtsTokenCount": 32,
            "totalTokenCount": 44,
            "candidatesTokensDetails": [],
        }
        value["candidates"] = [{"finishReason": "MAX_TOKENS"}]
        result = self.response_fixture(value)
        self.assertEqual(result["status"], "GENERATION_PARTIAL_VALIDATED")
        self.assertEqual(result["answer_tokens"], 0)
        self.assertEqual(result["thought_tokens"], 32)
        self.assertIs(result["has_text"], False)
        value["candidates"][0]["content"] = {
            "parts": [{"thought": True, "text": "PRIVATE_THOUGHT"}]
        }
        self.assertEqual(
            self.response_fixture(value)["status"],
            "GENERATION_PARTIAL_VALIDATED",
        )
        value["candidates"][0]["finishReason"] = "STOP"
        result = self.response_fixture(value)
        self.assertEqual(result["status"], "HTTP_200_UNVALIDATED")
        self.assertEqual(result["response_reason"], "TEXT_MISSING")
        self.assertEqual(result["observed"]["usage"]["answer_tokens"], 0)
        self.assertIs(result["observed"]["has_text"], False)
        value["candidates"] = [{"finishReason": "MAX_TOKENS"}]
        value["usageMetadata"] = {"promptTokenCount": 12, "totalTokenCount": 12}
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "NO_GENERATED_TOKENS")
        self.assertNotIn("model", result)

    def test_parse_failure_facts_are_independent_bounded_and_sanitized(self):
        value = envelope()
        value["usageMetadata"].update(
            candidatesTokenCount=1, thoughtsTokenCount=300, totalTokenCount=313
        )
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "OUTPUT_LIMIT_EXCEEDED")
        self.assertEqual(result["observed"]["usage"]["thought_tokens"], 300)
        self.assertNotIn("model", result)
        value = envelope()
        value["modelVersion"] = "gemini-3.8-flash"
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "MODEL_VERSION_UNSUPPORTED")
        self.assertNotIn("gemini-3.8-flash", json.dumps(result))
        self.assertEqual(
            result["observed"]["usage"], observed_envelope()["usage"]
        )
        value = envelope()
        value["usageMetadata"]["promptTokenCount"] = "PRIVATE_NUMBER"
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "USAGE_INVALID")
        self.assertNotIn("input_tokens", result["observed"]["usage"])
        value = envelope()
        value["candidates"][0]["finishReason"] = "PRIVATE_FINISH"
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "FINISH_REASON_UNSUPPORTED")
        self.assertEqual(result["observed"]["finish_category"], "UNSUPPORTED")
        value = envelope()
        value["candidates"][0]["content"]["parts"] = [
            {"functionCall": {"name": "PRIVATE_TOOL"}}
        ]
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "UNREQUESTED_PART")
        self.assertIs(result["observed"]["has_text"], False)
        value = envelope()
        value["usageMetadata"]["thoughtsTokenCount"] = 65537
        result = self.response_fixture(value)
        self.assertEqual(result["response_reason"], "USAGE_INVALID")
        self.assertNotIn("thought_tokens", result["observed"]["usage"])

    def test_protojson_integer_forms_reject_unbounded_or_noninteger_data(self):
        for value in (None, 0, "0", 0.0):
            self.assertEqual(probe._count(value, 100), 0)
        for value in (12, "12", 12.0, "1.2e1"):
            self.assertEqual(probe._count(value, 100), 12)
        for value in (
            True,
            -1,
            1.5,
            "1.5",
            "1e9999",
            float("inf"),
            "PRIVATE_VALUE",
            "1" * 65,
        ):
            self.assertIsNone(probe._count(value, 100))

    def test_native_stdlib_close_keepalive_chunked_and_partial_framing(self):
        body = json.dumps(envelope()).encode()
        variants = [
            (
                b"Content-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n",
                body,
                True,
            ),
            (
                b"Content-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: keep-alive\r\n",
                body,
                True,
            ),
            (
                b"Transfer-Encoding: chunked\r\nConnection: close\r\n",
                hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n0\r\n\r\n",
                True,
            ),
            (
                b"Content-Length: "
                + str(len(body) + 1).encode()
                + b"\r\nConnection: close\r\n",
                body,
                False,
            ),
            (
                b"Transfer-Encoding: chunked \r\nConnection: close\r\n",
                b"2\r\n{}\r\n0\r\n\r\n",
                False,
            ),
            (
                b"Transfer-Encoding: chunked\r\nConnection: close\r\n",
                b"5\r\nabc",
                False,
            ),
        ]
        for headers, content, valid in variants:
            with (
                self.subTest(headers=headers),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                wire = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + headers
                    + b"\r\n"
                    + content
                )
                conn = NativeFakeConnection(wire)
                result = probe.execute(
                    self.env,
                    connection_factory=lambda *a, **k: conn,
                    wall=lambda: NOW,
                    monotonic=lambda: 100,
                )
                self.assertEqual(
                    result["status"],
                    "RESPONSE_VALIDATED" if valid else "UNKNOWN",
                )
                self.assertEqual(b"".join(conn.socket.sent).count(b"POST "), 1)

    def test_inline_fetch_with_native_close_and_chunked_response(self):
        code = workflow_parts()[4]
        body = PATH.read_bytes()
        for chunked in (False, True):
            with (
                self.subTest(chunked=chunked),
                tempfile.TemporaryDirectory() as directory,
            ):
                headers = (
                    b"Transfer-Encoding: chunked\r\n"
                    if chunked
                    else b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                )
                data = (
                    hex(len(body))[2:].encode()
                    + b"\r\n"
                    + body
                    + b"\r\n0\r\n\r\n"
                    if chunked
                    else body
                )
                conn = NativeFakeConnection(
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                    + headers
                    + b"\r\n"
                    + data
                )
                env = self.environment(directory)
                del env["GEMINI_KEY"]
                env["GITHUB_TOKEN"] = "synthetic-builtin-token"
                with (
                    mock.patch.dict(os.environ, env, clear=True),
                    mock.patch.object(
                        http.client, "HTTPSConnection", return_value=conn
                    ),
                    mock.patch("time.time", return_value=NOW),
                ):
                    exec(compile(code, "workflow-fetch", "exec"), {})
                self.assertEqual(
                    pathlib.Path(
                        directory, "cartreadback-gemini-probe.py"
                    ).read_bytes(),
                    body,
                )
                self.assertEqual(b"".join(conn.socket.sent).count(b"GET "), 1)


class NativeCredentialTest(unittest.TestCase):
    def test_default_native_connect_environ_socket_and_header_boundary(self):
        for public_key in ("AQ.synthetic-only-key", "AQ." + "p" * 300):
            with (
                self.subTest(),
                tempfile.TemporaryDirectory() as directory,
            ):
                values = ProbeTest.environment(None, directory)
                values["GEMINI_KEY"] = public_key

                def encode(value):
                    return value.encode("utf-8", "surrogateescape")

                def decode(value):
                    return value.decode("utf-8", "surrogateescape")

                # Public backing only. Never copy or inspect the process env.
                env = os._Environ(
                    {encode(k): encode(v) for k, v in values.items()},
                    encode,
                    decode,
                    encode,
                    decode,
                )
                left, right = socket.socketpair()
                self.addCleanup(left.close)
                self.addCleanup(right.close)
                native_wrap = ssl.SSLContext.wrap_socket
                seen = []

                def wrap(context, sock, **kwargs):
                    wrapped = native_wrap(
                        context, sock, do_handshake_on_connect=False, **kwargs
                    )
                    seen.append(wrapped)
                    return wrapped

                with (
                    mock.patch("socket.create_connection", return_value=left),
                    mock.patch.object(socket.socket, "setsockopt"),
                    mock.patch.object(ssl.SSLContext, "wrap_socket", wrap),
                    mock.patch.object(
                        socket.socket,
                        "connect",
                        side_effect=AssertionError(
                            "external connect forbidden"
                        ),
                    ),
                    mock.patch.object(
                        socket.socket,
                        "connect_ex",
                        side_effect=AssertionError(
                            "external connect forbidden"
                        ),
                    ),
                    mock.patch.object(os, "unsetenv"),
                    mock.patch.object(
                        http.client.HTTPSConnection,
                        "send",
                        side_effect=RuntimeError("public stop before send"),
                    ) as send,
                ):
                    result = probe.execute(
                        env, wall=lambda: NOW, monotonic=lambda: 100
                    )
                self.assertEqual(
                    result, {"status": "UNKNOWN", "phase": "request-attempt"}
                )
                self.assertEqual(len(seen), 1)
                self.assertIsInstance(seen[0], ssl.SSLSocket)
                # Native request/header encoding completed before this stop.
                self.assertEqual(send.call_count, 1)
                wire = send.call_args.args[0]
                self.assertEqual(wire.count(b"POST "), 1)
                self.assertIn(
                    b"x-goog-api-key: " + public_key.encode() + b"\r\n", wire
                )
                self.assertNotIn("GEMINI_KEY", env)
                self.assertEqual(
                    len(list(pathlib.Path(directory).glob("*.claim"))), 1
                )


if __name__ == "__main__":
    unittest.main()
