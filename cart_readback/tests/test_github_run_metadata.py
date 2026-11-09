"""Offline raw-HTTP tests; private seams never establish production evidence."""

import contextlib
import copy
import dataclasses
import http.client
import io
import json
import os
import queue
import socket
import ssl
import tempfile
import threading
import traceback
import unittest
from pathlib import Path
from unittest import mock

from cartreadback_app import github_run_metadata as gm

NOW = 1_800_000_100
TOKEN = "synthetic_token_not_a_credential"
BASE = "/repos/thzthix/cart-readback/actions"


def enrollment(**changes):
    values = {
        "repository_id": 101,
        "workflow_id": 202,
        "actor_id": 303,
        "workflow_path": ".github/workflows/one-off.yml",
        "reviewed_sha": "a" * 40,
        "not_before": NOW - 100,
        "expires_at": NOW + 100,
    }
    return gm.RunEnrollment(**(values | changes))


def timestamp(offset=0):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(NOW + offset, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def run(**changes):
    repository = {
        "id": 101,
        "full_name": "thzthix/cart-readback",
        "fork": False,
    }
    return {
        "id": 404,
        "workflow_id": 202,
        "run_number": 1,
        "run_attempt": 1,
        "path": ".github/workflows/one-off.yml@main",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "event": "workflow_dispatch",
        "status": "in_progress",
        "conclusion": None,
        "pull_requests": [],
        "url": f"https://api.github.com{BASE}/runs/404",
        "workflow_url": f"https://api.github.com{BASE}/workflows/202",
        "repository": repository,
        "head_repository": copy.deepcopy(repository),
        "actor": {"id": 303},
        "triggering_actor": {"id": 303},
        "created_at": timestamp(-10),
        "run_started_at": timestamp(-5),
        "updated_at": timestamp(-1),
    } | changes


def workflow(**changes):
    return {
        "id": 202,
        "path": ".github/workflows/one-off.yml",
        "state": "active",
        "url": f"https://api.github.com{BASE}/workflows/202",
    } | changes


def wire(value, *, headers=(), status="200 OK", chunked=False):
    body = value if type(value) is bytes else json.dumps(value).encode()
    framing = (
        b"Transfer-Encoding: chunked\r\n"
        if chunked
        else f"Content-Length: {len(body)}\r\n".encode()
    )
    if chunked:
        body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    return (
        f"HTTP/1.1 {status}\r\n".encode()
        + b"Content-Type: application/json; charset=utf-8\r\n"
        + framing
        + b"".join(f"{k}: {v}\r\n".encode() for k, v in headers)
        + b"\r\n"
        + body
    )


class FakeSocket:
    def __init__(self, raw, stage, failure):
        self.stream = io.BytesIO(raw)
        self.timeouts = []
        self.stage, self.failure = stage, failure

    def makefile(self, _mode):
        return self

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def read1(self, amount):
        self.stage("read")
        if self.failure == "read":
            raise RuntimeError(TOKEN)
        if self.failure == "cancel":
            raise KeyboardInterrupt()
        return self.stream.read(min(amount, 64))

    def close(self):
        self.stream.close()

    def flush(self):
        pass


class FakeConnection:
    def __init__(self, raw, stage, failure=None):
        self.raw, self.stage, self.failure = raw, stage, failure
        self.sock = FakeSocket(raw, stage, failure)
        self.closed = False
        self.response = None
        self.headers_alias = None
        self.requests = []

    def set_debuglevel(self, level):
        self.debuglevel = level

    def connect(self):
        self.stage("connect")
        if self.failure == "connect":
            raise RuntimeError(TOKEN)

    def request(self, method, path, *, body, headers):
        self.stage("request")
        self.headers_alias = headers
        self.requests.append((method, path, body, dict(headers)))
        if self.failure == "request":
            raise RuntimeError(TOKEN)

    def getresponse(self):
        self.stage("response")
        if self.failure == "response":
            raise RuntimeError(TOKEN)
        self.response = self.response_class(self.sock)
        try:
            self.response.begin()
        except BaseException:
            self.response.close()
            raise
        return self.response

    def close(self):
        self.closed = True
        self.sock.close()
        if self.failure == "close":
            raise RuntimeError(TOKEN)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.events, self.connections, self.contexts = [], [], []
        self.clock, self.mono = NOW, 10
        self.responses = [
            wire(run()),
            wire(workflow()),
            wire({"total_count": 1, "workflow_runs": [run()]}),
        ]
        self.failures = {}
        self.advance = None
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            mock.patch.object(gm, "_wall_clock", lambda: self.clock)
        )
        self.stack.enter_context(
            mock.patch.object(gm, "_monotonic", lambda: self.mono)
        )
        self.factory = self.stack.enter_context(
            mock.patch.object(gm, "_connection", self.connection)
        )
        self.network = self.stack.enter_context(
            mock.patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network"),
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                socket, "getaddrinfo", side_effect=AssertionError("DNS")
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                socket, "socket", side_effect=AssertionError("socket")
            )
        )

    def stage(self, name):
        self.events.append(name)
        if self.advance is not None:
            self.advance(name)

    def connection(self, deadline, context):
        self.stage("factory")
        self.contexts.append(context)
        item = FakeConnection(
            self.responses[len(self.connections)],
            self.stage,
            self.failures.get(len(self.connections)),
        )
        self.connections.append(item)
        return item

    def credential(self):
        self.stage("credential")
        return TOKEN

    def read(self, enrolled=None, credential=None, run_id=404):
        return gm.GitHubRunMetadataReader(
            enrolled or enrollment(), credential or self.credential
        ).read(run_id)

    def assert_failure(self, **kwargs):
        with self.assertRaises(gm.MetadataUnavailable) as error:
            self.read(**kwargs)
        self.assertEqual(
            str(error.exception), "GitHub run metadata unavailable; no retry."
        )
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertTrue(all(item.closed for item in self.connections))
        self.assertLessEqual(len(self.connections), 3)

    def test_success_exercises_raw_http_and_exact_projection(self):
        result = self.read()
        self.assertEqual(
            result,
            gm.GitHubRunMetadata(
                101,
                202,
                303,
                ".github/workflows/one-off.yml",
                "refs/heads/main",
                "a" * 40,
                404,
                NOW - 10,
                NOW - 5,
                NOW - 1,
            ),
        )
        self.assertEqual(len(self.connections), 3)
        expected_paths = [
            f"{BASE}/runs/404",
            f"{BASE}/workflows/202",
            f"{BASE}/workflows/202/runs?per_page=100&page=1",
        ]
        for connection, path, context in zip(
            self.connections, expected_paths, self.contexts, strict=True
        ):
            self.assertTrue(connection.closed)
            self.assertTrue(connection.response.isclosed())
            self.assertEqual(connection.headers_alias, {})
            self.assertEqual(connection.debuglevel, 0)
            self.assertEqual(connection.auto_open, 0)
            method, actual, body, headers = connection.requests[0]
            self.assertEqual((method, actual, body), ("GET", path, None))
            self.assertEqual(headers["Host"], "api.github.com")
            self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
            self.assertEqual(headers["X-GitHub-Api-Version"], "2026-03-10")
            self.assertEqual(headers["Accept-Encoding"], "identity")
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertIsNone(context.keylog_filename)
            self.assertGreaterEqual(
                context.minimum_version, ssl.TLSVersion.TLSv1_2
            )
            self.assertTrue(
                all(0 < value <= 5 for value in connection.sock.timeouts)
            )
        self.assertEqual(self.events.count("credential"), 3)
        self.assertLess(
            self.events.index("connect"), self.events.index("credential")
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.run_id = 405
        self.network.assert_not_called()

    def test_reader_one_shot_after_success_and_failure(self):
        reader = gm.GitHubRunMetadataReader(enrollment(), self.credential)
        reader.read(404)
        with self.assertRaises(gm.MetadataUnavailable):
            reader.read(404)
        self.assertEqual(len(self.connections), 3)

    def test_untrusted_enrollment_or_run_id_before_io(self):
        for bad in (None, {}, "value"):
            with (
                self.subTest(bad=bad),
                self.assertRaises(gm.MetadataUnavailable),
            ):
                gm.GitHubRunMetadataReader(bad, self.credential)
        for bad in (False, True, 0, -1, "404", 2**63):
            with (
                self.subTest(bad=bad),
                self.assertRaises(gm.MetadataUnavailable),
            ):
                self.read(run_id=bad)
        self.assertEqual(self.connections, [])

    def test_identity_and_status_counterexamples_stop_after_first_get(self):
        cases = {
            "id": 405,
            "workflow_id": 203,
            "run_number": 2,
            "run_attempt": 2,
            "path": ".github/workflows/other.yml@main",
            "head_branch": "other",
            "head_sha": "b" * 40,
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [{}],
            "url": "https://evil.example/run/404",
            "workflow_url": "https://evil.example/workflow",
            "actor": {"id": True},
            "triggering_actor": {"id": 304},
            "repository": {
                "id": 101,
                "full_name": "elsewhere/foreign",
                "fork": False,
            },
            "head_repository": {
                "id": 101,
                "full_name": "thzthix/cart-readback",
                "fork": True,
            },
            "created_at": timestamp(-101),
            "run_started_at": timestamp(-20),
            "updated_at": timestamp(1),
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                self.connections.clear()
                self.responses[0] = wire(run(**{key: value}))
                self.assert_failure()
                self.assertEqual(len(self.connections), 1)
        for key in run():
            with self.subTest(missing=key):
                self.connections.clear()
                payload = run()
                del payload[key]
                self.responses[0] = wire(payload)
                self.assert_failure()

    def test_workflow_mismatch_stops_after_second_get(self):
        for key, value in {
            "id": True,
            "path": ".github/workflows/other.yml",
            "state": "disabled_manually",
            "url": "https://elsewhere/workflow",
        }.items():
            with self.subTest(key=key):
                self.connections.clear()
                self.responses[1] = wire(workflow(**{key: value}))
                self.assert_failure()
                self.assertEqual(len(self.connections), 2)

    def test_history_refuses_partial_paginated_and_changed_current(self):
        cases = [
            {},
            {"total_count": True, "workflow_runs": [run()]},
            {"total_count": 0, "workflow_runs": []},
            {"total_count": 2, "workflow_runs": [run()]},
            {"total_count": 1, "workflow_runs": []},
            {"total_count": 1, "workflow_runs": [run(), run(id=403)]},
            {"total_count": 1, "workflow_runs": [run(run_number=2)]},
            {"total_count": 1, "workflow_runs": [run(updated_at=timestamp())]},
            {"total_count": 1, "workflow_runs": [run(conclusion="failure")]},
        ]
        for value in cases:
            with self.subTest(value=value):
                self.connections.clear()
                self.responses[2] = wire(value)
                self.assert_failure()
        self.connections.clear()
        self.responses[2] = wire(
            {"total_count": 1, "workflow_runs": [run()]},
            headers=[("Link", '<https://evil.example/?page=2>; rel="next"')],
        )
        self.assert_failure()

    def test_wire_framing_json_and_redirect_fail_closed(self):
        valid = wire(run())
        cases = [
            wire(
                {},
                status="302 Redirect",
                headers=[("Location", "https://evil.example")],
            ),
            wire({}, headers=[("Location", "https://evil.example")]),
            wire({}, headers=[("Link", "")]),
            wire({}, headers=[("Content-Length", "2")]),
            wire({}, headers=[("Content-Encoding", "gzip")]),
            wire(b'{"id":1,"id":2}'),
            wire(b'{"value":NaN}'),
            wire(b'{"value":Infinity}'),
            wire(b'"not an object"'),
            wire(b"{"),
            wire(b"\xff"),
            wire(b"[" * 14 + b"]" * 14),
            valid[:-1],
            valid.replace(b"HTTP/1.1", b"HTTP/1.0", 1),
            valid.replace(b"Content-Length:", b"Bad Header:", 1),
            valid.replace(b"Content-Length:", b" Content-Length:", 1),
            wire({}, headers=[("X-Test", "x" * 4097)]),
            wire({}, headers=[(f"X-{index}", "v") for index in range(65)]),
            wire(
                {}, headers=[(f"X-{index}", "x" * 4000) for index in range(5)]
            ),
            wire(b"a" * (gm._MAX_BODY + 1)),
            wire({}, chunked=True).replace(
                b"0\r\n\r\n", b"0\r\nTrailer: bad\r\n\r\n"
            ),
        ]
        for index, value in enumerate(cases):
            with self.subTest(index=index):
                self.connections.clear()
                self.responses[0] = value
                self.assert_failure()
                self.assertEqual(len(self.connections), 1)

    def test_chunked_response_is_supported(self):
        self.responses[0] = wire(run(), chunked=True)
        self.assertEqual(self.read().run_id, 404)

    def test_failures_are_sanitized_and_resources_close(self):
        for index in range(3):
            for stage in ("connect", "request", "response", "read", "close"):
                with self.subTest(index=index, stage=stage):
                    self.connections.clear()
                    self.failures = {index: stage}
                    output = io.StringIO()
                    with (
                        contextlib.redirect_stdout(output),
                        contextlib.redirect_stderr(output),
                    ):
                        self.assert_failure()
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(len(self.connections), index + 1)

    def test_cancellation_closes_all_resources(self):
        self.failures = {0: "cancel"}
        reader = gm.GitHubRunMetadataReader(enrollment(), self.credential)
        with self.assertRaises(KeyboardInterrupt):
            reader.read(404)
        self.assertTrue(self.connections[0].closed)
        self.assertTrue(self.connections[0].response.isclosed())
        with self.assertRaises(gm.MetadataUnavailable):
            reader.read(404)
        self.assertEqual(len(self.connections), 1)

    def assert_safe_exception(self, reader, expected):
        with self.assertRaises(expected) as result:
            reader.read(404)
        error = result.exception
        self.assertIs(type(error), expected)
        self.assertNotIn(TOKEN, repr(error.args))
        self.assertNotIn(TOKEN, "".join(traceback.format_exception(error)))
        if expected is SystemExit:
            self.assertEqual(error.code, 1)
            self.assertIs(type(error.code), int)
        elif expected in (KeyboardInterrupt, GeneratorExit):
            self.assertEqual(error.args, ())
        else:
            self.assertEqual(
                str(error), "GitHub run metadata unavailable; no retry."
            )
        count = len(self.connections)
        self.assertTrue(all(item.closed for item in self.connections))
        self.assertLessEqual(count, 3)
        with self.assertRaises(gm.MetadataUnavailable):
            reader.read(404)
        self.assertEqual(len(self.connections), count)

    def test_argument_bearing_cancellation_each_request_and_phase(self):
        original_stage = self.stage
        original_close = FakeConnection.close
        for kind in (KeyboardInterrupt, SystemExit, GeneratorExit):
            for phase in ("credential", "request", "read", "close"):
                for index in range(3):
                    with self.subTest(kind=kind, phase=phase, index=index):
                        self.connections.clear()

                        def stage(name):
                            original_stage(name)
                            if (
                                name == phase
                                and len(self.connections) == index + 1
                            ):
                                raise kind(TOKEN)

                        def close(connection):
                            original_close(connection)
                            if (
                                phase == "close"
                                and len(self.connections) == index + 1
                            ):
                                raise kind(TOKEN)

                        with (
                            mock.patch.object(self, "stage", stage),
                            mock.patch.object(FakeConnection, "close", close),
                        ):
                            reader = gm.GitHubRunMetadataReader(
                                enrollment(), self.credential
                            )
                            self.assert_safe_exception(reader, kind)
                        self.assertEqual(len(self.connections), index + 1)

    def test_primary_and_cleanup_cancellation_precedence(self):
        original_close = FakeConnection.close
        for primary in (
            RuntimeError,
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
        ):
            for cleanup in (
                RuntimeError,
                KeyboardInterrupt,
                SystemExit,
                GeneratorExit,
            ):
                with self.subTest(primary=primary, cleanup=cleanup):
                    self.connections.clear()

                    def credential():
                        raise primary(TOKEN)

                    def close(connection):
                        original_close(connection)
                        raise cleanup(TOKEN)

                    expected = (
                        primary
                        if primary is not RuntimeError
                        else cleanup
                        if cleanup is not RuntimeError
                        else gm.MetadataUnavailable
                    )
                    with mock.patch.object(FakeConnection, "close", close):
                        reader = gm.GitHubRunMetadataReader(
                            enrollment(), credential
                        )
                        self.assert_safe_exception(reader, expected)

    def test_unexpected_and_grouped_base_exceptions_are_unavailable(self):
        values = (
            BaseException(TOKEN),
            BaseExceptionGroup(TOKEN, [KeyboardInterrupt(TOKEN)]),
            BaseExceptionGroup(TOKEN, [SystemExit(TOKEN), ValueError(TOKEN)]),
        )
        original_close = FakeConnection.close
        for value in values:
            for phase in ("credential", "cleanup"):
                with self.subTest(value=type(value), phase=phase):
                    self.connections.clear()

                    def credential():
                        if phase == "credential":
                            raise value
                        return self.credential()

                    def close(connection):
                        original_close(connection)
                        if phase == "cleanup":
                            raise value

                    with mock.patch.object(FakeConnection, "close", close):
                        reader = gm.GitHubRunMetadataReader(
                            enrollment(), credential
                        )
                        self.assert_safe_exception(
                            reader, gm.MetadataUnavailable
                        )

    def test_unrelated_caller_exception_cannot_hide_cleanup_failure(self):
        self.failures = {0: "close"}
        try:
            raise KeyboardInterrupt(TOKEN)
        except KeyboardInterrupt:
            self.assert_failure()
        self.assertEqual(len(self.connections), 1)

    def test_bad_credential_or_callback_does_not_request(self):
        for bad in ("", None, "synthetic\r\nHeader: value", 1, "x" * 4097):
            with self.subTest(bad=bad):
                self.connections.clear()
                self.assert_failure(credential=lambda: bad)
                self.assertEqual(self.connections[0].requests, [])
        self.connections.clear()

        def failed():
            raise RuntimeError(TOKEN)

        self.assert_failure(credential=failed)

    def test_window_and_total_deadlines_rechecked_through_reads(self):
        for now in (NOW - 101, NOW + 100):
            self.clock = now
            self.assert_failure()
            self.assertEqual(self.connections, [])
        self.clock = NOW
        for mode in ("expire", "monotonic", "wallrollback", "monorollback"):
            with self.subTest(mode=mode):
                self.connections.clear()
                self.clock, self.mono = NOW, 10

                def advance(name):
                    if name == "read":
                        if mode == "expire":
                            self.clock = NOW + 100
                        if mode == "monotonic":
                            self.mono += 21
                        if mode == "wallrollback":
                            self.clock = NOW - 1
                        if mode == "monorollback":
                            self.mono = 9

                self.advance = advance
                self.assert_failure()
                self.assertEqual(len(self.connections), 1)

    def test_proxy_and_keylog_environment_not_inherited(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "must-not-exist"
            with mock.patch.dict(
                os.environ,
                {
                    "SSLKEYLOGFILE": str(path),
                    "HTTPS_PROXY": "http://evil.example",
                    "GITHUB_TOKEN": TOKEN,
                    "GH_TOKEN": TOKEN,
                },
            ):
                self.assertEqual(self.read().run_id, 404)
            self.assertFalse(path.exists())


class EnrollmentTests(unittest.TestCase):
    def test_strict_identity_main_and_absolute_window(self):
        for field in (
            "repository_id",
            "workflow_id",
            "actor_id",
            "not_before",
            "expires_at",
        ):
            for bad in (True, False, 0, -1, "1", 2**63):
                with (
                    self.subTest(field=field, bad=bad),
                    self.assertRaises(gm.MetadataUnavailable),
                ):
                    enrollment(**{field: bad})
        for changes in (
            {"ref": "refs/heads/dev"},
            {"ref": "refs/tags/main"},
            {"expires_at": NOW + 86_301},
            {"expires_at": NOW - 100},
            {"workflow_path": "../other.yml"},
            {"workflow_path": ".github/workflows/evil.yml@main"},
            {"reviewed_sha": "A" * 40},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(gm.MetadataUnavailable),
            ):
                enrollment(**changes)
        value = enrollment(expires_at=NOW - 100 + 86_400)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.expires_at += 1


class ProductionConnectionTests(unittest.TestCase):
    def test_actual_cleanup_ignores_unrelated_caller_exception(self):
        try:
            raise KeyboardInterrupt(TOKEN)
        except KeyboardInterrupt:
            self.test_actual_getresponse_preserves_primary_and_cleanup_precedence()

    def test_actual_getresponse_preserves_primary_and_cleanup_precedence(self):
        address = ("192.0.2.1", 443)
        original_close = gm._StrictResponse.close
        for primary in (
            None,
            RuntimeError,
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
        ):
            for response_fault in (
                RuntimeError,
                KeyboardInterrupt,
                SystemExit,
                GeneratorExit,
            ):
                for socket_fault in (
                    RuntimeError,
                    KeyboardInterrupt,
                    SystemExit,
                    GeneratorExit,
                ):
                    with self.subTest(
                        primary=primary,
                        response=response_fault,
                        socket=socket_fault,
                    ):
                        events = []

                        def stage(name):
                            events.append(name)
                            if primary is not None and name == "read":
                                raise primary(TOKEN)

                        class RawSocket:
                            def __init__(self):
                                self.file = FakeSocket(wire(run()), stage, None)
                                self.closed = False

                            def connect(self, target):
                                self.target = target

                            def settimeout(self, _timeout):
                                pass

                            def sendall(self, _data):
                                pass

                            def makefile(self, _mode):
                                return self.file

                            def close(self):
                                self.closed = True
                                events.append("socket_close")
                                raise socket_fault(TOKEN)

                        def response_close(response):
                            try:
                                original_close(response)
                            finally:
                                events.append("response_close")
                            raise response_fault(TOKEN)

                        raw = RawSocket()
                        expected = next(
                            (
                                kind
                                for kind in (
                                    primary,
                                    response_fault,
                                    socket_fault,
                                )
                                if kind
                                in (
                                    KeyboardInterrupt,
                                    SystemExit,
                                    GeneratorExit,
                                )
                            ),
                            gm.MetadataUnavailable,
                        )
                        with (
                            mock.patch.object(
                                gm, "_wall_clock", return_value=NOW
                            ),
                            mock.patch.object(
                                gm, "_monotonic", return_value=10
                            ),
                            mock.patch.object(
                                gm,
                                "_resolve",
                                return_value=(
                                    socket.AF_INET,
                                    socket.SOCK_STREAM,
                                    socket.IPPROTO_TCP,
                                    address,
                                ),
                            ),
                            mock.patch.object(
                                socket, "socket", return_value=raw
                            ) as factory,
                            mock.patch.object(
                                ssl.SSLContext, "wrap_socket", return_value=raw
                            ),
                            mock.patch.object(
                                gm._StrictResponse, "close", response_close
                            ),
                        ):
                            reader = gm.GitHubRunMetadataReader(
                                enrollment(), lambda: TOKEN
                            )
                            try:
                                reader.read(404)
                            except BaseException as error:
                                self.assertIs(type(error), expected)
                                self.assertNotIn(TOKEN, repr(error.args))
                                self.assertNotIn(
                                    TOKEN,
                                    "".join(traceback.format_exception(error)),
                                )
                                if expected is SystemExit:
                                    self.assertEqual(error.code, 1)
                            else:
                                self.fail("fault returned metadata observation")
                            with self.assertRaises(gm.MetadataUnavailable):
                                reader.read(404)
                            factory.assert_called_once()
                        self.assertEqual(raw.target, address)
                        self.assertTrue(raw.closed)
                        self.assertIn("response_close", events)
                        self.assertIn("socket_close", events)

    def test_raw_connect_cleanup_preserves_normalized_public_cancellation(self):
        address = ("192.0.2.1", 443)
        for primary in (
            RuntimeError,
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
        ):
            for cleanup in (
                RuntimeError,
                KeyboardInterrupt,
                SystemExit,
                GeneratorExit,
            ):
                with self.subTest(primary=primary, cleanup=cleanup):
                    raw, credential = mock.Mock(), mock.Mock()
                    raw.connect.side_effect = primary(TOKEN)
                    raw.close.side_effect = cleanup(TOKEN)
                    expected = (
                        primary
                        if primary is not RuntimeError
                        else cleanup
                        if cleanup is not RuntimeError
                        else gm.MetadataUnavailable
                    )
                    with (
                        mock.patch.object(gm, "_wall_clock", return_value=NOW),
                        mock.patch.object(gm, "_monotonic", return_value=10),
                        mock.patch.object(
                            gm,
                            "_resolve",
                            return_value=(
                                socket.AF_INET,
                                socket.SOCK_STREAM,
                                socket.IPPROTO_TCP,
                                address,
                            ),
                        ),
                        mock.patch.object(socket, "socket", return_value=raw),
                    ):
                        reader = gm.GitHubRunMetadataReader(
                            enrollment(), credential
                        )
                        with self.assertRaises(expected) as result:
                            reader.read(404)
                        self.assertIs(type(result.exception), expected)
                        self.assertNotIn(TOKEN, repr(result.exception.args))
                        self.assertNotIn(
                            TOKEN,
                            "".join(
                                traceback.format_exception(result.exception)
                            ),
                        )
                        if expected is SystemExit:
                            self.assertEqual(result.exception.code, 1)
                        with self.assertRaises(gm.MetadataUnavailable):
                            reader.read(404)
                    raw.connect.assert_called_once_with(address)
                    raw.close.assert_called_once()
                    credential.assert_not_called()

    def test_connect_failure_cleans_socket_without_retry(self):
        deadline, context, raw = (mock.Mock() for _ in range(3))
        deadline.timeout.return_value = 2
        address = ("192.0.2.1", 443)
        for stage in ("connect", "tls"):
            with self.subTest(stage=stage):
                raw.reset_mock()
                context.reset_mock()
                raw.connect.side_effect = (
                    TimeoutError(TOKEN) if stage == "connect" else None
                )
                context.wrap_socket.side_effect = ssl.SSLError(TOKEN)
                with (
                    mock.patch.object(
                        gm,
                        "_resolve",
                        return_value=(
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            socket.IPPROTO_TCP,
                            address,
                        ),
                    ),
                    mock.patch.object(socket, "socket", return_value=raw),
                ):
                    with self.assertRaises((TimeoutError, ssl.SSLError)):
                        gm._GitHubConnection(deadline, context).connect()
                raw.close.assert_called_once()
                raw.connect.assert_called_once_with(address)

    def test_fixed_tcp_tls_constructor_no_proxy_or_retry(self):
        deadline, context, raw, tls = (mock.Mock() for _ in range(4))
        deadline.timeout.return_value = 2
        context.wrap_socket.return_value = tls
        address = ("192.0.2.1", 443)
        with (
            mock.patch.object(
                gm,
                "_resolve",
                return_value=(
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    address,
                ),
            ),
            mock.patch.object(socket, "socket", return_value=raw) as factory,
        ):
            connection = gm._GitHubConnection(deadline, context)
            self.assertEqual(
                (connection.host, connection.port), ("api.github.com", 443)
            )
            self.assertIsNone(connection._tunnel_host)
            connection.connect()
            raw.connect.assert_called_once_with(address)
            context.wrap_socket.assert_called_once_with(
                raw, server_hostname="api.github.com"
            )
            factory.assert_called_once()
            connection.close()
            tls.close.assert_called_once()

    def test_dns_worker_can_only_resolve_fixed_host_and_is_bounded(self):
        deadline = mock.Mock()
        deadline.timeout.return_value = 0.01
        started, release = threading.Event(), threading.Event()
        records = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.0.2.1", 443),
            )
        ]

        def slow(*args, **kwargs):
            started.set()
            release.wait(1)
            return records

        slot = threading.BoundedSemaphore(1)
        with (
            mock.patch.object(gm, "_DNS_SLOT", slot),
            mock.patch.object(
                socket, "getaddrinfo", side_effect=slow
            ) as resolver,
            mock.patch.object(
                socket, "socket", side_effect=AssertionError("socket")
            ),
        ):
            try:
                with self.assertRaises(queue.Empty):
                    gm._resolve(deadline)
                self.assertTrue(started.is_set())
                with self.assertRaises(gm.MetadataUnavailable):
                    gm._resolve(deadline)
                resolver.assert_called_once_with(
                    "api.github.com",
                    443,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )
            finally:
                release.set()
                # Synchronize bounded test cleanup with the resolver's finally.
                self.assertTrue(slot.acquire(timeout=1))
                slot.release()

    def test_dns_success_failure_and_invalid_records(self):
        deadline = mock.Mock()
        deadline.timeout.return_value = 1
        record = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("192.0.2.1", 443),
        )
        with mock.patch.object(socket, "getaddrinfo", return_value=[record]):
            self.assertEqual(
                gm._resolve(deadline),
                (record[0], record[1], record[2], record[4]),
            )
        for bad in ([], [record] * 17, [(*record[:4], ("evil.example", 443))]):
            with (
                self.subTest(bad=bad),
                mock.patch.object(socket, "getaddrinfo", return_value=bad),
                self.assertRaises((gm.MetadataUnavailable, ValueError)),
            ):
                gm._resolve(deadline)
        with (
            mock.patch.object(
                socket, "getaddrinfo", side_effect=OSError(TOKEN)
            ),
            self.assertRaises(gm.MetadataUnavailable),
        ):
            gm._resolve(deadline)


class IsolationTests(unittest.TestCase):
    def test_private_patches_and_runtime_globals_restore_in_same_process(self):
        baseline = (
            http.client.HTTPResponse,
            socket.socket,
            socket.getaddrinfo,
            socket.create_connection,
            ssl.SSLContext,
            gm._connection,
            gm._wall_clock,
            gm._monotonic,
            gm._DNS_SLOT,
            dict(os.environ),
        )
        for _ in range(2):
            case = ReaderTests(
                "test_success_exercises_raw_http_and_exact_projection"
            )
            result = unittest.TestResult()
            case.run(result)
            self.assertEqual((result.errors, result.failures), ([], []))
            self.assertEqual(
                baseline,
                (
                    http.client.HTTPResponse,
                    socket.socket,
                    socket.getaddrinfo,
                    socket.create_connection,
                    ssl.SSLContext,
                    gm._connection,
                    gm._wall_clock,
                    gm._monotonic,
                    gm._DNS_SLOT,
                    dict(os.environ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
