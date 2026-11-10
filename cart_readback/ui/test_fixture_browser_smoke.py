"""Offline tests only: injected fake WebDriver/process, never launch Chrome."""

import base64
import hashlib
import http.client
import json
import os
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

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
                "passed" if fail is None else "failed",
            )
            self.assertNotIn("session", json.dumps(receipt))
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


if __name__ == "__main__":
    unittest.main()
