"""Fake-only tests of the actual one-shot client and branch workflow contract."""

import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
import os
import pathlib
import signal
import ssl
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATH = ROOT / "cart_readback/scripts/gemini_connectivity_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("diagnostic", PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
NOW = 1700000100


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
        self.assertEqual(self.run_probe(), {"status": "NOT_RUN"})
        self.assertEqual(len(self.factories), 1)

    def test_all_context_mismatches_block_before_key_or_factory(self):
        mutations = [(k, "wrong") for k in probe.EXPECTED_CONTEXT]
        mutations += [
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
                self.assertEqual(self.run_probe(), {"status": "NOT_RUN"})
                self.assertEqual(self.env.borrowed, 0)
                self.assertEqual(self.factories, [])

    def test_identity_constants_and_request_digest(self):
        self.assertEqual(
            probe.EXPECTED_CONTEXT["GITHUB_REPOSITORY_ID"], "1443556432"
        )
        self.assertEqual(
            probe.EXPECTED_CONTEXT["GITHUB_REPOSITORY_OWNER_ID"], "95135403"
        )
        self.assertEqual(
            probe.REQUEST_SHA256,
            "1d5aeeb73cc4fa2225e99bd1bdccd5a963251e00e1f7cd9f6561489b980f95f8",
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
        self.assertEqual(self.run_probe(), {"status": "UNKNOWN"})
        self.assertEqual(self.connection.requests, [])
        self.assertEqual(self.env.borrowed, 1)
        self.assertEqual(self.run_probe(), {"status": "NOT_RUN"})

    def test_expiry_after_connect_prevents_borrow_and_post(self):
        now = [NOW]
        self.connection.connect = lambda: now.__setitem__(0, NOW + 101)
        result = probe.execute(
            self.env,
            connection_factory=self.factory,
            wall=lambda: now[0],
            monotonic=lambda: 100,
        )
        self.assertEqual(result, {"status": "UNKNOWN"})
        self.assertEqual(self.env.borrowed, 0)
        self.assertEqual(self.connection.requests, [])

    def test_http_redirect_errors_fail_without_retry(self):
        for status in (201, 301, 302, 307, 308, 400, 429, 500):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(b"PRIVATE_ERROR", status)
                self.assertEqual(self.run_probe(), {"status": "UNKNOWN"})
                self.assertEqual(len(self.connection.requests), 1)
                self.assertEqual(self.connection.closed, 1)

    def test_unvalidated_schema_is_contact_only_and_oversize_stays_unknown(
        self,
    ):
        bodies = [
            b"PRIVATE_ERROR",
            b"x" * 16385,
            b'{"a":1,"a":2}',
            b'{"a":NaN}',
        ]
        for mutate in (
            lambda x: x.update(modelVersion="wrong"),
            lambda x: x["usageMetadata"].update(totalTokenCount=1),
            lambda x: x["usageMetadata"].update(promptTokenCount=True),
            lambda x: x["usageMetadata"].update(thoughtsTokenCount=40),
        ):
            value = envelope()
            mutate(value)
            bodies.append(json.dumps(value).encode())
        for body in bodies:
            with (
                self.subTest(size=len(body)),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.env = self.environment(directory)
                self.connection = FakeHTTPSConnection(body)
                expected = (
                    {"status": "UNKNOWN"}
                    if len(body) > 16384
                    else {"status": "HTTP_200_UNVALIDATED", "http_status": 200}
                )
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
                    {"status": "UNKNOWN"},
                )

    def test_late_read_never_becomes_success(self):
        ticks = iter((100, 100, 100, 100, 100, 100, 100, 100, 121, 121, 121))
        result = probe.execute(
            self.env,
            connection_factory=self.factory,
            wall=lambda: NOW,
            monotonic=lambda: next(ticks),
        )
        self.assertEqual(result, {"status": "UNKNOWN"})

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
        self.assertEqual(json.loads(output.getvalue()), {"status": "UNKNOWN"})
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_workflow_only_final_step_has_google_key(self):
        workflow = yaml.load(
            (ROOT / probe.WORKFLOW_PATH).read_text(), Loader=yaml.BaseLoader
        )
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["gemini-connectivity"]
        self.assertEqual(job["timeout-minutes"], "2")
        self.assertEqual(
            job["concurrency"],
            {
                "group": "cartreadback-gemini-connectivity-one-shot",
                "cancel-in-progress": "false",
            },
        )
        self.assertEqual(len(job["steps"]), 2)
        fetch, final = job["steps"]
        self.assertNotIn("GEMINI_KEY", fetch["env"])
        self.assertNotIn("GITHUB_TOKEN", final["env"])
        self.assertEqual(
            final["env"]["GEMINI_KEY"], "${{ secrets.GEMINI_KEY }}"
        )
        self.assertEqual(
            final["env"]["PROBE_SOURCE_SHA256"],
            hashlib.sha256(PATH.read_bytes()).hexdigest(),
        )
        self.assertNotIn("uses:", yaml.safe_dump(job))
        self.assertIn(
            hashlib.sha256(PATH.read_bytes()).hexdigest(), fetch["run"]
        )

    def test_pinned_fetch_good_and_fail_closed(self):
        workflow = yaml.load(
            (ROOT / probe.WORKFLOW_PATH).read_text(), Loader=yaml.BaseLoader
        )
        script = workflow["jobs"]["gemini-connectivity"]["steps"][0]["run"]
        code = "\n".join(script.splitlines()[1:-1])
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
                thoughtSignature="invalid!"
            ),
            lambda v: v["usageMetadata"].update(unreviewed=0),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = json.loads(json.dumps(value))
                mutate(changed)
                self.assertIsNone(
                    probe._safe_observation(200, json.dumps(changed).encode())
                )

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
        workflow = yaml.load(
            (ROOT / probe.WORKFLOW_PATH).read_text(), Loader=yaml.BaseLoader
        )
        run = workflow["jobs"]["gemini-connectivity"]["steps"][0]["run"]
        code = "\n".join(run.splitlines()[1:-1])
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


if __name__ == "__main__":
    unittest.main()
