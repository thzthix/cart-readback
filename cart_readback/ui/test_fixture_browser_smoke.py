"""Offline tests only: injected fake WebDriver/process, never launch Chrome."""

import base64
import hashlib
import http.client
import io
import json
import os
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from unittest.mock import Mock, patch

import fixture_browser_smoke as smoke


def measure(width=1200, blocked=False):
    return {
        "loaded": True,
        "width": width,
        "height": 2400,
        "dpr": 1,
        "overflow": False,
        "actions": 0,
        "synthetic": True,
        "sourceLabel": "Approved original source",
        "resultLabel": "Retained review · no action authority",
        "source": {"x": 16, "y": 300, "width": 250, "height": 200},
        "result": {
            "x": 16 if width == 320 else 500,
            "y": 550 if width == 320 else 300,
            "width": 250,
            "height": 500,
        },
        "results": 0 if blocked else 2,
        "unknown": 0 if blocked else 1,
        "blocked": blocked,
        "accountingUnknown": blocked,
    }


def png(width):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 2400, 8, 2, 0, 0, 0))
        + chunk(
            b"IDAT", zlib.compress((b"\x00" + b"\xff\xff\xff" * width) * 2400)
        )
        + chunk(b"IEND", b"")
    )


class FakeProcess:
    def __init__(self, events, hang=False):
        self.events = events
        self.hang = hang
        self.pid = 4321

    def terminate(self):
        self.events.append("terminate")

    def wait(self, timeout):
        self.events.append("wait")
        if self.hang:
            self.hang = False
            raise subprocess.TimeoutExpired("fake", timeout)

    def kill(self):
        self.events.append("kill")


class FakeServer:
    def __init__(self, events):
        self.events = events
        self.server_port = 12345
        self.blocked = False

    def serve_forever(self):
        self.events.append("serve")

    def shutdown(self):
        self.events.append("shutdown")

    def server_close(self):
        self.events.append("server_close")


class FakeDriver:
    def __init__(self, server, events, fail=None):
        self.server = server
        self.events = events
        self.fail = fail
        self.width = 1200

    def stage(self, stage):
        self.events.append(stage)
        if self.fail == stage:
            raise smoke.SmokeFailure(stage)

    def ready(self):
        self.stage("ready")
        return True

    def create(self, chrome, profile, width):
        self.stage("create")
        self.width = width
        profile.mkdir()
        return {"chrome": "156.0", "chromedriver": "156.0"}

    def command(self, method, path, payload=None):
        self.stage(path)
        if path == "/execute/sync":
            result = measure(self.width, self.server.blocked)
            if self.fail == "geometry":
                result["width"] = 999
            return result
        if path == "/screenshot":
            if self.fail == "png":
                return "not a PNG"
            return base64.b64encode(png(self.width)).decode()
        return None

    def close(self):
        self.stage("close")


class FixtureTests(unittest.TestCase):
    def delayed_command(self, method, path, delay, error=None):
        observed = {"requests": 0, "closes": 0, "elapsed": 0}

        class Connection:
            def __init__(self, host, port, timeout):
                observed.update(host=host, port=port, timeout=timeout)

            def request(self, actual_method, actual_path, body, headers):
                observed["requests"] += 1
                observed["request"] = (actual_method, actual_path)

            def getresponse(self):
                if error is not None:
                    raise error
                observed["elapsed"] = min(delay, observed["timeout"])
                if delay > observed["timeout"]:
                    raise TimeoutError("PRIVATE-DELAY-CANARY")
                response = Mock(status=200)
                response.read.return_value = b'{"value":null}'
                return response

            def close(self):
                observed["closes"] += 1

        with (
            patch.object(smoke.http.client, "HTTPConnection", Connection),
            patch.object(
                smoke.socket, "socket", side_effect=AssertionError("network")
            ),
            patch.object(
                smoke.subprocess, "Popen", side_effect=AssertionError("process")
            ),
        ):
            try:
                smoke.request(12345, method, path, {})
            except BaseException as caught:
                observed["error"] = caught
        self.assertEqual(observed["requests"], 1)
        self.assertEqual(observed["closes"], 1)
        self.assertEqual(observed["host"], "127.0.0.1")
        return observed

    def test_command_budget_allows_valid_delayed_responses(self):
        for suffix, delay in (
            ("/url", 4),
            ("/url", 9.9),
            ("/execute/sync", 4),
            ("/execute/sync", 4.9),
        ):
            with self.subTest(suffix=suffix, delay=delay):
                observed = self.delayed_command(
                    "POST", "/session/synthetic" + suffix, delay
                )
                self.assertNotIn("error", observed)
                self.assertEqual(observed["elapsed"], delay)

    def test_command_budget_exact_selection_and_expiry(self):
        cases = (
            ("POST", "/session/synthetic/url", 12),
            ("POST", "/session/synthetic/execute/sync", 7),
            ("POST", "/session", 3),
            ("GET", "/status", 3),
            ("POST", "/session/synthetic/timeouts", 3),
            ("DELETE", "/session/synthetic", 3),
            ("GET", "/session/synthetic/screenshot", 3),
            ("GET", "/session/synthetic/url", 3),
            ("POST", "/session/synthetic/url?extra=1", 3),
            ("POST", "/session/synthetic/execute/sync/extra", 3),
            ("POST", "/session/bad/id/url", 3),
            ("POST", "/session/" + "a" * 129 + "/url", 3),
        )
        for method, path, expected in cases:
            with self.subTest(method=method, path=path):
                observed = self.delayed_command(method, path, expected + 0.1)
                self.assertEqual(observed["timeout"], expected)
                self.assertEqual(observed["elapsed"], expected)
                self.assertIsInstance(observed["error"], TimeoutError)

    def test_command_budget_preserves_errors_and_cancellation(self):
        class HostileTimeout(TimeoutError):
            def __str__(self):
                raise AssertionError("error text read")

            @property
            def operation(self):
                raise AssertionError("error metadata read")

        for error in (
            HostileTimeout("PRIVATE-DELAY-CANARY"),
            OSError("PRIVATE-DELAY-CANARY"),
            KeyboardInterrupt("PRIVATE-DELAY-CANARY"),
            SystemExit(9),
        ):
            observed = self.delayed_command(
                "POST", "/session/synthetic/url", 0, error
            )
            self.assertIs(observed["error"], error)
        self.assertNotIn(
            "PRIVATE-DELAY-CANARY", self.offline_stdout.getvalue()
        )

    def test_command_budget_does_not_admit_new_endpoints(self):
        transport = Mock()
        driver = smoke.Driver(12345, transport)
        driver.session = "synthetic"
        for method, path in (
            ("GET", "/session/synthetic/url"),
            ("POST", "/session/synthetic/url?extra=1"),
            ("POST", "/session/other/url"),
            ("POST", "/session/synthetic/execute/sync/extra"),
        ):
            with self.assertRaises(smoke.SmokeFailure):
                driver.call(method, path)
        transport.assert_not_called()

    def setUp(self):
        # Test-only capture: fake negative controls must not look like hosted
        # render failures in the preceding offline step's job output.
        self.offline_stdout = io.StringIO()
        capture = patch("sys.stdout", self.offline_stdout)
        capture.start()
        self.addCleanup(capture.stop)

    def test_transport_timeout_keeps_session_operation(self):
        for operation, failed_path in (
            ("session_create", "/session"),
            ("session_timeouts", "/session/synthetic/timeouts"),
        ):
            with self.subTest(operation=operation):
                calls = []

                def transport(port, method, path, payload):
                    calls.append((method, path))
                    if path == failed_path:
                        raise TimeoutError("PRIVATE-TIMEOUT-CANARY")
                    return json.dumps(
                        {"value": {"sessionId": "synthetic"}}
                    ).encode()

                receipt = {"checks": []}
                diagnostics = smoke.Diagnostics(receipt)
                with self.assertRaises(TimeoutError):
                    with diagnostics.stage("session", "review-wide"):
                        smoke.Driver(12345, transport).create(
                            "/fake/chrome", Path("/fake/profile"), 1200
                        )
                primary = diagnostics.record["primary_failure"]
                self.assertEqual(primary.get("operation"), operation)
                self.assertEqual(primary["category"], "timeout")
                self.assertEqual(primary["stage"], "session")
                self.assertEqual(
                    len(calls), 1 if operation == "session_create" else 2
                )
                diagnostics.emit_failure(receipt)
                self.assertNotIn(
                    "PRIVATE-TIMEOUT-CANARY", self.offline_stdout.getvalue()
                )
                self.assertNotIn("PRIVATE-TIMEOUT-CANARY", json.dumps(receipt))
                self.assertEqual(primary["http_status"], "unavailable")

    def test_timeout_metadata_never_inspects_external_exception(self):
        class HostileTimeout(TimeoutError):
            def __str__(self):
                raise AssertionError("exception text inspected")

            @property
            def operation(self):
                raise AssertionError("external metadata inspected")

        receipt = {"checks": []}
        diagnostics = smoke.Diagnostics(receipt)
        with self.assertRaises(TimeoutError):
            with diagnostics.stage("session", "review-wide"):
                with smoke.failure_operation("session_create"):
                    raise HostileTimeout("PRIVATE-TIMEOUT-CANARY")
        self.assertEqual(
            diagnostics.record["primary_failure"]["operation"],
            "session_create",
        )
        diagnostics.emit_failure(receipt)
        self.assertNotIn(
            "PRIVATE-TIMEOUT-CANARY", self.offline_stdout.getvalue()
        )

    def test_timeout_metadata_does_not_relabel_other_failures(self):
        for error in (OSError("private"), KeyboardInterrupt("private")):
            receipt = {"checks": []}
            diagnostics = smoke.Diagnostics(receipt)
            with self.assertRaises(type(error)):
                with diagnostics.stage("session", "review-wide"):
                    with smoke.failure_operation("session_create"):
                        raise error
            self.assertNotIn(
                "operation", diagnostics.record["primary_failure"]
            )
        self.assertEqual(
            smoke.OperationTimeout("unlisted").operation, "unavailable"
        )

    def test_source_manifest_exact_and_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            content = b"public source"
            (path / "viewer.html").write_bytes(content)
            with patch.object(
                smoke,
                "SOURCE_HASHES",
                {"viewer.html": hashlib.sha256(content).hexdigest()},
            ):
                self.assertEqual(
                    smoke.checked_sources(path)["viewer.html"], content
                )
                (path / "viewer.html").write_bytes(b"mutated")
                with self.assertRaises(smoke.SmokeFailure):
                    smoke.checked_sources(path)

    def test_source_missing_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with self.assertRaises(smoke.SmokeFailure):
                smoke.checked_sources(path)
            (path / "target").write_bytes(b"x")
            (path / "viewer.html").symlink_to(path / "target")
            with self.assertRaises(smoke.SmokeFailure):
                smoke.checked_sources(path)

    def test_policy_exact_hashes(self):
        result = smoke.policy(b"<script>one</script><style>two</style>")
        self.assertIn(
            base64.b64encode(hashlib.sha256(b"one").digest()).decode(), result
        )
        self.assertNotIn("unsafe-inline", result)
        with self.assertRaises(smoke.SmokeFailure):
            smoke.policy(
                b"<script>a</script><script>b</script><style>c</style>"
            )

    def test_fixture_state_independent_and_synthetic(self):
        review, blocked = smoke.fixture(False), smoke.fixture(True)
        self.assertEqual(len(review["checkout"]["results"]), 2)
        self.assertEqual(blocked["checkout"]["results"], [])
        self.assertEqual(
            blocked["checkout"]["analysis"]["accounting_state"], "unknown"
        )
        self.assertFalse(review["providers"]["network_enabled"])
        self.assertIn(
            "PUBLIC SYNTHETIC", review["catalog"][0]["source"]["text"]
        )

    def test_environment_excludes_secrets_and_proxy(self):
        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "fake",
                "HTTPS_PROXY": "fake",
                "GEMINI_API_KEY": "fake",
            },
        ):
            env = smoke.clean_env(Path("/tmp/fake"))
        self.assertEqual(set(env), {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"})

    def test_local_http_routes_and_marker(self):
        sources = {
            "viewer.html": b"<script>x</script><style>y</style>",
            "viewer.mjs": b"public",
            "viewer-core.mjs": b"public",
            "core.mjs": b"public",
        }
        server = smoke.FixtureServer(sources)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(
                smoke.request(server.server_port, "GET", "/health", limit=128),
                smoke.MARKER,
            )
            self.assertEqual(
                smoke.request(server.server_port, "GET", "/viewer.mjs"),
                b"public",
            )
            for method, path in (
                ("GET", "/viewer?x=1"),
                ("GET", "/../viewer"),
                ("POST", "/gemini-viewer/api/redeem"),
                ("HEAD", "/viewer"),
                ("GET", "/unknown"),
            ):
                with (
                    self.subTest(method=method, path=path),
                    self.assertRaises(smoke.SmokeFailure),
                ):
                    smoke.request(server.server_port, method, path)
            with self.assertRaises(smoke.SmokeFailure):
                smoke.request(server.server_port, "GET", "/viewer", limit=3)
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=2
            )
            connection.request(
                "GET", "/viewer", headers={"Host": "untrusted.example"}
            )
            self.assertEqual(connection.getresponse().status, 400)
            connection.close()
            server.requests = 101
            with self.assertRaises(smoke.SmokeFailure):
                smoke.request(server.server_port, "GET", "/health")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_readiness_wrong_marker_timeout(self):
        ticks = iter(range(20))
        with self.assertRaises(smoke.SmokeFailure):
            smoke.wait_ready(
                lambda: False, clock=lambda: next(ticks), sleep=lambda _: None
            )
        smoke.wait_ready(lambda: True)

    def test_driver_json_and_endpoint_failures(self):
        for body in (b"not json", b"[]", b"{}", b'{"value":{"error":"bad"}}'):
            with self.subTest(body=body), self.assertRaises(smoke.SmokeFailure):
                smoke.Driver(1, lambda *args: body).ready()
        driver = smoke.Driver(1, lambda *args: b'{"value":{"ready":true}}')
        self.assertTrue(driver.ready())
        with self.assertRaises(smoke.SmokeFailure):
            driver.call("GET", "/arbitrary")

    def test_driver_session_and_version_validation(self):
        for value in (
            {},
            {"sessionId": "../bad"},
            {"sessionId": "fake", "capabilities": {}},
        ):
            driver = smoke.Driver(
                1, lambda *args: json.dumps({"value": value}).encode()
            )
            with (
                self.subTest(value=value),
                self.assertRaises(smoke.SmokeFailure),
            ):
                driver.create("/fixed/chrome", Path("/fixed/profile"), 320)
        calls = []

        def transport(*args):
            calls.append(args)
            return json.dumps(
                {
                    "value": {
                        "sessionId": "fake",
                        "capabilities": {
                            "browserVersion": "156.0",
                            "chrome": {"chromedriverVersion": "155.0"},
                        },
                    }
                }
            ).encode()

        with self.assertRaises(smoke.SmokeFailure):
            smoke.Driver(1, transport).create(
                "/fixed/chrome", Path("/fixed/profile"), 320
            )
        options = calls[0][3]["capabilities"]["alwaysMatch"][
            "goog:chromeOptions"
        ]
        self.assertEqual(
            options["mobileEmulation"]["deviceMetrics"]["width"], 320
        )
        self.assertFalse(options["mobileEmulation"]["deviceMetrics"]["mobile"])
        self.assertFalse(options["mobileEmulation"]["deviceMetrics"]["touch"])
        self.assertNotIn("--no-sandbox", options["args"])

    def test_layout_positive_and_negative_controls(self):
        for width in (320, 1200):
            for blocked in (True, False):
                smoke.check_measure(measure(width, blocked), width, blocked)
        for key, value in (
            ("width", 980),
            ("height", 200),
            ("dpr", 2),
            ("overflow", True),
            ("actions", 1),
            ("synthetic", False),
            ("loaded", False),
            ("unknown", 0),
        ):
            bad = measure(320)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(smoke.SmokeFailure):
                smoke.check_measure(bad, 320, False)
        bad = measure(320)
        bad["result"]["y"] = 300
        with self.assertRaises(smoke.SmokeFailure):
            smoke.check_measure(bad, 320, False)
        bad = measure(320, True)
        bad["results"] = 1
        with self.assertRaises(smoke.SmokeFailure):
            smoke.check_measure(bad, 320, True)

    def test_png_dimensions_and_malformed(self):
        good = base64.b64encode(png(320)).decode()
        self.assertEqual(smoke.png_bytes(good, 320), png(320))
        corrupt = bytearray(png(320))
        corrupt[29] ^= 1
        for value, width in (
            (base64.b64encode(corrupt).decode(), 320),
            (good, 1200),
            ("!!!", 320),
            (base64.b64encode(b"bad").decode(), 320),
        ):
            with (
                self.subTest(width=width),
                self.assertRaises(smoke.SmokeFailure),
            ):
                smoke.png_bytes(value, width)

    def lifecycle(self, fail=None):
        events = []
        server = FakeServer(events)
        envs = []

        def spawn(*args, **kwargs):
            self.assertTrue(kwargs["start_new_session"])
            events.append("spawn")
            envs.append(kwargs["env"])
            if fail == "spawn":
                raise OSError("fake spawn failure")
            return FakeProcess(events, hang=fail == "hang")

        def ready(probe):
            if not probe():
                raise smoke.SmokeFailure("ready")

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "artifacts"
            with (
                patch.object(
                    smoke,
                    "request",
                    return_value=smoke.MARKER if fail != "health" else b"wrong",
                ),
                patch.object(smoke, "wait_ready", side_effect=ready),
            ):
                if fail:
                    with self.assertRaises((smoke.SmokeFailure, OSError)):
                        smoke.run(
                            {},
                            output,
                            "/fake/chrome",
                            "/fake/driver",
                            spawn=spawn,
                            driver_factory=lambda _: FakeDriver(
                                server, events, fail
                            ),
                            server_factory=lambda _: server,
                            cleanup=lambda process: smoke.stop_process(
                                process,
                                signal_group=lambda pgid, kind: events.append(
                                    (pgid, kind)
                                ),
                                exists=lambda _: False,
                            ),
                        )
                else:
                    smoke.run(
                        {},
                        output,
                        "/fake/chrome",
                        "/fake/driver",
                        spawn=spawn,
                        driver_factory=lambda _: FakeDriver(server, events),
                        server_factory=lambda _: server,
                        cleanup=lambda process: smoke.stop_process(
                            process,
                            signal_group=lambda pgid, kind: events.append(
                                (pgid, kind)
                            ),
                            exists=lambda _: False,
                        ),
                    )
            receipt = json.loads((output / "receipt.json").read_text())
            self.assertLessEqual(
                {p.name for p in output.iterdir()}, smoke.ARTIFACT_NAMES
            )
            self.assertEqual(
                receipt["status"],
                "pending_job_conclusion" if fail is None else "failed",
            )
            self.assertNotIn("sessionId", json.dumps(receipt))
            self.assertNotIn("RAW_PRIVATE_SENTINEL", json.dumps(receipt))
            self.assertIs(receipt["job_conclusion_required"], True)
            self.assertEqual(
                receipt["checks_status"],
                "passed" if fail is None else "not_confirmed",
            )
            expected = {
                "health": "server_readiness",
                "spawn": "driver_start",
                "ready": "driver_readiness",
                "create": "session",
                "/url": "navigation",
                "/execute/sync": "render",
                "geometry": "measurement",
                "/screenshot": "png",
                "png": "png",
                "write": "write",
            }
            primary = receipt["diagnostics"]["primary_failure"]
            if fail in expected:
                self.assertEqual(primary["stage"], expected[fail])
            else:
                self.assertIsNone(primary)
            if fail in ("close", "hang"):
                self.assertTrue(
                    any(
                        item["status"] == "failed"
                        for item in receipt["diagnostics"]["cleanup"]
                    )
                )
        self.assertIn("shutdown", events)
        self.assertIn("server_close", events)
        for env in envs:
            self.assertFalse(Path(env["HOME"]).exists())
        if fail not in ("health", "spawn"):
            self.assertIn("terminate", events)
            self.assertIn("wait", events)
        return events

    def test_lifecycle_success_fake_only(self):
        events = self.lifecycle()
        self.assertEqual(events.count("spawn"), 4)
        self.assertEqual(events.count("close"), 4)

    def test_lifecycle_setup_render_cleanup_failures(self):
        for fail in (
            "health",
            "spawn",
            "ready",
            "create",
            "/url",
            "/execute/sync",
            "geometry",
            "/screenshot",
            "png",
            "close",
        ):
            with self.subTest(fail=fail):
                self.lifecycle(fail)

    def test_process_timeout_kill_is_failed_not_passed(self):
        self.assertIn("kill", self.lifecycle("hang"))

    def test_actual_pinned_source_when_available(self):
        directory = Path("ui")
        if not directory.exists():
            self.skipTest("four pinned source files not staged")
        self.assertEqual(
            set(smoke.checked_sources(directory)), set(smoke.SOURCE_HASHES)
        )

    def test_server_construction_and_thread_start_cleanup(self):
        for stage in ("construct", "thread-start"):
            events = []
            server = FakeServer(events)

            def factory(_):
                if stage == "construct":
                    raise OSError("injected construction failure")
                return server

            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "artifacts"
                with patch.object(
                    smoke.threading.Thread,
                    "start",
                    side_effect=RuntimeError("injected start failure"),
                ):
                    with self.assertRaises((OSError, RuntimeError)):
                        smoke.run(
                            {},
                            output,
                            "/fake/chrome",
                            "/fake/driver",
                            server_factory=factory,
                        )
                self.assertEqual(
                    json.loads((output / "receipt.json").read_text())["status"],
                    "failed",
                )
            if stage == "thread-start":
                self.assertIn("server_close", events)
                self.assertNotIn("shutdown", events)

    def test_session_delete_failure_clears_local_id(self):
        driver = smoke.Driver(
            1, lambda *args: b'{"value":{"error":"injected"}}'
        )
        driver.session = "fake"
        with self.assertRaises(smoke.SmokeFailure):
            driver.close()
        self.assertIsNone(driver.session)

    def test_png_rejects_valid_crc_but_invalid_compressed_pixels(self):
        data = bytearray(png(320))
        offset = 33
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        data[offset + 8] ^= 255
        end = offset + 12 + length
        data[end - 4 : end] = struct.pack(
            ">I", zlib.crc32(data[offset + 4 : end - 4])
        )
        with self.assertRaises(smoke.SmokeFailure):
            smoke.png_bytes(base64.b64encode(data).decode(), 320)

    def test_group_cleanup_lingering_and_signal_failure(self):
        events = []
        ticks = iter(range(20))
        process = FakeProcess(events)
        with self.assertRaises(smoke.SmokeFailure):
            smoke.stop_process(
                process,
                signal_group=lambda pgid, kind: events.append((pgid, kind)),
                exists=lambda _: True,
                clock=lambda: next(ticks),
                sleep=lambda _: None,
            )
        self.assertIn((4321, smoke.signal.SIGKILL), events)

        def denied(*_):
            raise PermissionError("injected")

        with self.assertRaises(PermissionError):
            smoke.stop_process(
                FakeProcess(events), signal_group=denied, exists=lambda _: False
            )
        self.assertIn("wait", events)

    def test_offscreen_and_nonfinite_geometry_negative_controls(self):
        for x in (-5000, 320, float("nan"), float("inf")):
            value = measure(320)
            value["source"]["x"] = x
            value["result"]["x"] = x
            with self.subTest(x=x), self.assertRaises(smoke.SmokeFailure):
                smoke.check_measure(value, 320, False)

    def test_diagnostic_categories_never_read_adversarial_text(self):
        class HostileError(Exception):
            def __str__(self):
                raise AssertionError("exception string accessed")

        class HostileBase(BaseException):
            pass

        cases = [
            (smoke.SmokeFailure("RAW_PRIVATE_SENTINEL"), "check_failed"),
            (TimeoutError("RAW_PRIVATE_SENTINEL"), "timeout"),
            (OSError("RAW_PRIVATE_SENTINEL"), "io_error"),
            (
                http.client.HTTPException("RAW_PRIVATE_SENTINEL"),
                "protocol_error",
            ),
            (ValueError("RAW_PRIVATE_SENTINEL"), "invalid_data"),
            (HostileError(), "unexpected_exception"),
            (HostileBase("RAW_PRIVATE_SENTINEL"), "unexpected_base_exception"),
            (KeyboardInterrupt("RAW_PRIVATE_SENTINEL"), "cancelled"),
            (SystemExit("RAW_PRIVATE_SENTINEL"), "cancelled"),
        ]
        for error, expected in cases:
            receipt = {}
            diagnostics = smoke.Diagnostics(receipt)
            with (
                self.subTest(expected=expected),
                self.assertRaises(type(error)),
            ):
                with diagnostics.stage("session", "review-wide"):
                    raise error
            self.assertEqual(
                receipt["diagnostics"]["primary_failure"]["category"], expected
            )
            self.assertNotIn("RAW_PRIVATE_SENTINEL", json.dumps(receipt))
        with self.assertRaises(smoke.SmokeFailure):
            with smoke.Diagnostics({}).stage("RAW_PRIVATE_SENTINEL"):
                pass

    def diagnostic_run(self, error, compound=False, second=False):
        events = []
        server = FakeServer(events)
        original_rmtree = smoke.shutil.rmtree

        class InjectedDriver(FakeDriver):
            def create(self, chrome, profile, width):
                value = super().create(chrome, profile, width)
                if not second or width == 320:
                    raise error
                return value

            def close(self):
                super().close()
                if compound:
                    raise RuntimeError("RAW_PRIVATE_SENTINEL delete")

        def cleanup(process):
            events.append("cleanup")
            if compound:
                raise OSError("RAW_PRIVATE_SENTINEL group")

        def rmtree(path, *args, **kwargs):
            if compound and Path(path).name == "Falsewide":
                raise OSError("RAW_PRIVATE_SENTINEL profile")
            return original_rmtree(path, *args, **kwargs)

        def shutdown():
            events.append("shutdown")
            raise OSError("RAW_PRIVATE_SENTINEL server")

        if compound:
            server.shutdown = shutdown
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            with (
                patch.object(smoke, "request", return_value=smoke.MARKER),
                patch.object(smoke.shutil, "rmtree", side_effect=rmtree),
            ):
                with self.assertRaises(BaseException):
                    smoke.run(
                        {},
                        output,
                        "/fake/chrome",
                        "/fake/driver",
                        spawn=lambda *args, **kwargs: FakeProcess(events),
                        driver_factory=lambda _: InjectedDriver(server, events),
                        server_factory=lambda _: server,
                        cleanup=cleanup,
                    )
            receipt = json.loads((output / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertNotIn("RAW_PRIVATE_SENTINEL", json.dumps(receipt))
            self.assertNotIn("sessionId", json.dumps(receipt))
            self.assertEqual(
                len(list(output.glob("*.png"))), 1 if second else 0
            )
        self.assertIn("server_close", events)
        return receipt

    def test_primary_preserved_across_compound_cleanup_failure(self):
        receipt = self.diagnostic_run(
            ValueError("RAW_PRIVATE_SENTINEL primary"), compound=True
        )
        diagnostics = receipt["diagnostics"]
        self.assertEqual(
            diagnostics["primary_failure"],
            {
                "stage": "session",
                "scenario": "review-wide",
                "status": "failed",
                "category": "invalid_data",
            },
        )
        failed = {
            item["stage"]
            for item in diagnostics["cleanup"]
            if item["status"] == "failed"
        }
        self.assertEqual(
            failed,
            {
                "session_cleanup",
                "process_cleanup",
                "profile_cleanup",
                "server_shutdown",
            },
        )
        self.assertEqual(
            diagnostics["cleanup"][-1]["stage"], "temporary_cleanup"
        )
        self.assertEqual(diagnostics["cleanup"][-1]["status"], "passed")

    def test_one_png_then_next_scenario_failure(self):
        receipt = self.diagnostic_run(
            RuntimeError("RAW_PRIVATE_SENTINEL"), second=True
        )
        self.assertEqual(
            receipt["diagnostics"]["primary_failure"]["scenario"],
            "review-narrow",
        )
        self.assertEqual(len(receipt["checks"]), 1)
        self.assertEqual(receipt["checks"][0]["scenario"], "review-wide")

    def test_cancellation_and_unexpected_base_remain_failed(self):
        class UnknownBase(BaseException):
            pass

        for error in (
            KeyboardInterrupt("RAW_PRIVATE_SENTINEL"),
            SystemExit("RAW_PRIVATE_SENTINEL"),
            UnknownBase("RAW_PRIVATE_SENTINEL"),
        ):
            with self.subTest(kind=type(error).__name__):
                receipt = self.diagnostic_run(error)
                self.assertIsNotNone(receipt["diagnostics"]["primary_failure"])

    def test_main_never_prints_raw_unknown_or_cancelled_errors(self):
        for error in (
            RuntimeError("RAW_PRIVATE_SENTINEL"),
            KeyboardInterrupt("RAW_PRIVATE_SENTINEL"),
            SystemExit("RAW_PRIVATE_SENTINEL"),
        ):
            output = io.StringIO()
            with (
                patch.dict(os.environ, {"FIXTURE_HOSTED_RUN": "1"}),
                patch.object(smoke, "checked_sources", side_effect=error),
                patch("sys.stdout", output),
                patch("sys.stderr", output),
            ):
                with self.assertRaises(SystemExit) as caught:
                    smoke.main()
            self.assertEqual(caught.exception.code, 1)
            self.assertIn(
                "PUBLIC_FIXTURE_RENDER_CHECKS_FAILED", output.getvalue()
            )
            self.assertNotIn("RAW_PRIVATE_SENTINEL", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())

    def test_png_write_failure_has_safe_stage(self):
        with patch.object(
            Path, "write_bytes", side_effect=OSError("RAW_PRIVATE_SENTINEL")
        ):
            self.lifecycle("write")

    def test_temporary_setup_failure_has_safe_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            with patch.object(
                smoke.tempfile,
                "TemporaryDirectory",
                side_effect=OSError("RAW_PRIVATE_SENTINEL"),
            ):
                with self.assertRaises(OSError):
                    smoke.run({}, output, "/fake/chrome", "/fake/driver")
            receipt = json.loads((output / "receipt.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(
                receipt["diagnostics"]["primary_failure"]["stage"], "setup"
            )
            self.assertNotIn("RAW_PRIVATE_SENTINEL", json.dumps(receipt))

    def test_internal_check_codes_closed_and_safe(self):
        class Hostile:
            def __str__(self):
                raise AssertionError("string read")

            def __hash__(self):
                raise AssertionError("hash read")

        for code in smoke.CHECK_CODES:
            self.assertEqual(
                smoke.failure_category(smoke.SmokeFailure(code)),
                "check_" + code.replace("-", "_"),
            )
        for value in ("RAW_PRIVATE_SENTINEL", Hostile(), None):
            error = smoke.SmokeFailure(value)
            self.assertEqual(smoke.failure_category(error), "check_failed")
            self.assertEqual(error.args, ("check_failed",))
        mutated = smoke.SmokeFailure("version")
        mutated.code = "RAW_PRIVATE_SENTINEL"
        self.assertEqual(smoke.failure_category(mutated), "check_failed")

    def test_failure_summary_rejects_unlisted_values(self):
        receipt = {"checks": [None] * 99}
        diagnostics = smoke.Diagnostics(receipt)
        diagnostics.record["primary_failure"] = {
            "stage": "RAW_PRIVATE_SENTINEL",
            "category": "RAW_PRIVATE_SENTINEL",
            "scenario": "RAW_PRIVATE_SENTINEL",
        }
        diagnostics.record["cleanup"] = [
            {"stage": "RAW_PRIVATE_SENTINEL", "status": "failed"},
            {"stage": "process_cleanup", "status": "failed"},
        ]
        output = io.StringIO()
        with patch("sys.stdout", output):
            diagnostics.emit_failure(receipt, receipt_write_failed=True)
        self.assertNotIn("RAW_PRIVATE_SENTINEL", output.getvalue())
        summary = json.loads(output.getvalue().split(" ", 1)[1])
        self.assertEqual(summary["primary_stage"], "unavailable")
        self.assertEqual(summary["failed_cleanup_stages"], ["process_cleanup"])
        self.assertEqual(summary["saved_png_count"], 4)
        self.assertEqual(summary["receipt_write"], "failed")

    def test_compound_failure_summary_preserves_primary(self):
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.diagnostic_run(
                ValueError("RAW_PRIVATE_SENTINEL"), compound=True
            )
        summary = json.loads(output.getvalue().split(" ", 1)[1])
        self.assertEqual(summary["primary_stage"], "session")
        self.assertEqual(summary["primary_category"], "invalid_data")
        self.assertEqual(summary["scenario"], "review-wide")
        self.assertEqual(summary["saved_png_count"], 0)
        self.assertEqual(len(summary["failed_cleanup_stages"]), 4)
        self.assertNotIn("RAW_PRIVATE_SENTINEL", output.getvalue())

    def test_receipt_write_failure_emits_safe_token(self):
        with tempfile.TemporaryDirectory() as temp:
            output = io.StringIO()
            with (
                patch.object(
                    smoke.tempfile,
                    "TemporaryDirectory",
                    side_effect=ValueError("RAW_PRIVATE_SENTINEL"),
                ),
                patch.object(
                    smoke,
                    "write_receipt_temp",
                    side_effect=OSError("RAW_PRIVATE_SENTINEL receipt"),
                ),
                patch("sys.stdout", output),
            ):
                with self.assertRaises(OSError):
                    smoke.run(
                        {}, Path(temp) / "out", "/fake/chrome", "/fake/driver"
                    )
            self.assertNotIn("RAW_PRIVATE_SENTINEL", output.getvalue())
            summary = json.loads(output.getvalue().split(" ", 1)[1])
            self.assertEqual(summary["receipt_write"], "failed")
            self.assertEqual(summary["primary_stage"], "setup")
            self.assertEqual(summary["primary_category"], "invalid_data")

    def test_late_staging_write_failure_publishes_no_receipt(self):
        real_write = smoke.write_receipt_temp
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            output.mkdir()
            receipt = {"status": "passed", "checks": []}
            diagnostics = smoke.Diagnostics(receipt)

            def late_write(path, data):
                calls.append(path)
                real_write(path, data)
                raise OSError("RAW_PRIVATE_SENTINEL late close")

            stdout = io.StringIO()
            with (
                patch.object(
                    smoke, "write_receipt_temp", side_effect=late_write
                ),
                patch("sys.stdout", stdout),
            ):
                with self.assertRaises(OSError):
                    smoke.publish_receipt(output, receipt, diagnostics)
            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0], output / "receipt.json")
            self.assertFalse((output / "receipt.json").exists())
            self.assertFalse(calls[0].exists())
            self.assertEqual(receipt["status"], "failed")
            self.assertNotIn("RAW_PRIVATE_SENTINEL", stdout.getvalue())
            self.assertEqual(
                json.loads(stdout.getvalue().split(" ", 1)[1])["receipt_write"],
                "failed",
            )

    def test_replace_failure_before_and_after_effect_invalidates(self):
        real_replace = Path.replace
        for after_effect in (False, True):
            calls = []
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "out"
                output.mkdir()
                receipt = {"status": "passed", "checks": []}
                diagnostics = smoke.Diagnostics(receipt)

                def replace(path, target):
                    calls.append((path, target))
                    if after_effect:
                        real_replace(path, target)
                    raise OSError("RAW_PRIVATE_SENTINEL replace")

                with (
                    patch.object(Path, "replace", replace),
                    patch("sys.stdout", io.StringIO()),
                ):
                    with self.assertRaises(OSError):
                        smoke.publish_receipt(output, receipt, diagnostics)
                self.assertEqual(len(calls), 1)
                self.assertFalse((output / "receipt.json").exists())
                self.assertFalse(calls[0][0].exists())
                self.assertEqual(receipt["status"], "failed")

    def test_failed_invalidation_never_leaves_standalone_passed_receipt(self):
        real_replace, real_unlink = Path.replace, Path.unlink
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            output.mkdir()
            receipt = {"status": "passed", "checks": []}
            diagnostics = smoke.Diagnostics(receipt)

            def replace(path, target):
                calls.append("replace")
                real_replace(path, target)
                raise OSError("RAW_PRIVATE_SENTINEL after replace")

            def unlink(path, *args, **kwargs):
                calls.append(path.name)
                if path.name == "receipt.json":
                    raise PermissionError("RAW_PRIVATE_SENTINEL invalidation")
                return real_unlink(path, *args, **kwargs)

            stdout = io.StringIO()
            with (
                patch.object(Path, "replace", replace),
                patch.object(Path, "unlink", unlink),
                patch("sys.stdout", stdout),
            ):
                with self.assertRaises(OSError):
                    smoke.publish_receipt(output, receipt, diagnostics)
            persisted = json.loads((output / "receipt.json").read_text())
            self.assertEqual(persisted["status"], "pending_job_conclusion")
            self.assertIs(persisted["job_conclusion_required"], True)
            self.assertEqual(calls.count("replace"), 1)
            self.assertEqual(calls.count("receipt.json"), 1)
            self.assertEqual(receipt["status"], "failed")
            self.assertNotIn("RAW_PRIVATE_SENTINEL", stdout.getvalue())
            summary = json.loads(stdout.getvalue().split(" ", 1)[1])
            self.assertEqual(summary["receipt_write"], "failed")
            self.assertEqual(summary["receipt_invalidation"], "failed")

    def test_http_kind_status_bounds_and_body_limit(self):
        for status, body, kind, expected_status in (
            (500, b"private body", "non_200", 500),
            (100, b"x", "non_200", 100),
            (599, b"x", "non_200", 599),
            (99, b"x", "non_200", "unavailable"),
            (600, b"x", "non_200", "unavailable"),
            (True, b"x", "non_200", "unavailable"),
            ("500", b"x", "non_200", "unavailable"),
            (200, b"12345", "oversize", 200),
        ):
            connection, response = Mock(), Mock()
            connection.getresponse.return_value = response
            response.status = status
            response.read.side_effect = lambda n: body[:n]
            with patch.object(
                smoke.http.client, "HTTPConnection", return_value=connection
            ):
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.request(1, "POST", "/session", {}, limit=4)
            self.assertEqual(caught.exception.http_kind, kind)
            self.assertEqual(caught.exception.http_status, expected_status)
            response.read.assert_called_once_with(5)
            connection.close.assert_called_once()
        response.status = 200
        response.read.side_effect = lambda n: b"1234"
        with patch.object(
            smoke.http.client, "HTTPConnection", return_value=connection
        ):
            self.assertEqual(
                smoke.request(1, "GET", "/status", limit=4), b"1234"
            )

    def test_http_w3c_error_whitelist_drops_private_fields(self):
        for label, expected in list(smoke.WEBDRIVER_ERRORS.items()) + [
            ("RAW_PRIVATE_SENTINEL", "unavailable")
        ]:
            body = json.dumps(
                {
                    "value": {
                        "error": label,
                        "message": "RAW_PRIVATE_SENTINEL https://secret.invalid/session/SECRET",
                        "stacktrace": "SECRET",
                        "data": {"sessionId": "SECRET"},
                    }
                }
            ).encode()
            connection, response = Mock(), Mock()
            connection.getresponse.return_value = response
            response.status, response.read.return_value = 500, body
            with patch.object(
                smoke.http.client, "HTTPConnection", return_value=connection
            ):
                with self.assertRaises(smoke.SmokeFailure) as caught:
                    smoke.request(1, "POST", "/session", {})
            self.assertEqual(caught.exception.webdriver_error, expected)
            self.assertEqual(caught.exception.args, ("http",))
            receipt = {"checks": []}
            diagnostics = smoke.Diagnostics(receipt)
            with self.assertRaises(smoke.SmokeFailure):
                with diagnostics.stage("session", "review-wide"):
                    with smoke.failure_operation("session_create"):
                        raise caught.exception
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                diagnostics.emit_failure(receipt)
            summary = json.loads(stdout.getvalue().split(" ", 1)[1])
            self.assertEqual(summary["operation"], "session_create")
            self.assertEqual(summary["webdriver_error"], expected)
            self.assertEqual(summary["http_kind"], "non_200")
            self.assertEqual(summary["http_status"], 500)
            self.assertNotIn("SECRET", stdout.getvalue() + json.dumps(receipt))
            self.assertNotIn(
                "secret.invalid", stdout.getvalue() + json.dumps(receipt)
            )
        for body in (b"bad", b"[]", b'{"value":[]}', b'{"value":{"error":5}}'):
            self.assertEqual(smoke.bounded_webdriver_error(body), "unavailable")

    def test_oversized_error_body_not_parsed(self):
        connection, response = Mock(), Mock()
        connection.getresponse.return_value = response
        response.status, response.read.return_value = 500, b"12345"
        with (
            patch.object(
                smoke.http.client, "HTTPConnection", return_value=connection
            ),
            patch.object(smoke, "bounded_webdriver_error") as parser,
        ):
            with self.assertRaises(smoke.SmokeFailure) as caught:
                smoke.request(1, "POST", "/session", {}, limit=4)
        parser.assert_not_called()
        self.assertEqual(caught.exception.http_kind, "non_200")
        self.assertEqual(caught.exception.webdriver_error, "unavailable")

    def test_exact_session_operation_and_version_check(self):
        for operation in ("session_create", "session_timeouts", "version"):
            calls = []

            def transport(port, method, path, payload):
                calls.append(path)
                if (operation == "session_create" and path == "/session") or (
                    operation == "session_timeouts"
                    and path.endswith("/timeouts")
                ):
                    raise smoke.SmokeFailure(
                        "http",
                        http_kind="non_200",
                        http_status=500,
                        webdriver_error="session_not_created",
                    )
                if path == "/session":
                    return json.dumps(
                        {
                            "value": {
                                "sessionId": "PRIVATESESSION",
                                "capabilities": {
                                    "browserVersion": "156.0",
                                    "chrome": {"chromedriverVersion": "155.0"},
                                },
                            }
                        }
                    ).encode()
                return b'{"value":null}'

            driver = smoke.Driver(1, transport)
            receipt = {"checks": []}
            diagnostics = smoke.Diagnostics(receipt)
            with self.assertRaises(smoke.SmokeFailure):
                with diagnostics.stage("session", "review-wide"):
                    driver.create("/fixed/chrome", Path("/fixed/profile"), 1200)
            primary = receipt["diagnostics"]["primary_failure"]
            self.assertEqual(primary["operation"], operation)
            self.assertEqual(
                primary["category"],
                "check_version" if operation == "version" else "check_http",
            )
            self.assertEqual(
                len(calls), 1 if operation == "session_create" else 2
            )
            self.assertNotIn("PRIVATESESSION", json.dumps(receipt))

    def test_http_metadata_hostility_and_subclass_fallback(self):
        class Hostile:
            def __str__(self):
                raise AssertionError("str accessed")

            def __hash__(self):
                raise AssertionError("hash accessed")

        class HostileFailure(smoke.SmokeFailure):
            @property
            def operation(self):
                raise AssertionError("subclass accessor read")

        for value in (Hostile(), True, 99, 600, "RAW_PRIVATE_SENTINEL"):
            error = smoke.SmokeFailure(
                "http",
                operation=value,
                http_kind=value,
                http_status=value,
                webdriver_error=value,
            )
            metadata = smoke.safe_failure_metadata(
                error.operation,
                error.http_kind,
                error.http_status,
                error.webdriver_error,
            )
            self.assertEqual(set(metadata.values()), {"unavailable"})
        error = HostileFailure.__new__(HostileFailure)
        Exception.__init__(error, "RAW_PRIVATE_SENTINEL")
        receipt = {"checks": []}
        diagnostics = smoke.Diagnostics(receipt)
        with self.assertRaises(HostileFailure):
            with diagnostics.stage("session", "review-wide"):
                with smoke.failure_operation("session_create"):
                    raise error
        self.assertEqual(
            receipt["diagnostics"]["primary_failure"]["category"],
            "check_failed",
        )
        self.assertNotIn("operation", receipt["diagnostics"]["primary_failure"])
        self.assertNotIn("RAW_PRIVATE_SENTINEL", json.dumps(receipt))


if __name__ == "__main__":
    unittest.main()
