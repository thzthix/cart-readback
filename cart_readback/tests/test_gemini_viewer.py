"""Actual loopback viewer adversaries using fabricated provider and credentials."""

import contextlib
import copy
import http.client
import io
import json
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from cartreadback_app.gemini_viewer import GeminiResultViewer
from cartreadback_app.service import Service
from cartreadback_app.storage import Store, csrf_for, product_for
from cartreadback_app.validation import AppError, canonical
from test_gemini_service import CHOICES, NOW, fabricate

UI = Path(__file__).resolve().parents[1] / "ui"
API = "/gemini-viewer/api"


class ViewerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "synthetic.sqlite3")
        self.owner = self.store.session(None)[0]["sid"]
        runtime, self.wire, self.handle = fabricate(
            self.store, (self.owner,), free=True, max_calls=1
        )
        self.service = Service(
            self.store,
            gemini_analysis=runtime,
            clock=lambda: datetime.fromtimestamp(NOW, timezone.utc),
        )
        self.addCleanup(self.service.close)
        with patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("No provider"),
        ):
            self.result = self.service.mutate(
                self.owner,
                "analyze",
                {
                    "expected_revision": 0,
                    "sku_id": "KB-UK-C2C",
                    "conditions": [
                        {"kind": x["kind"], "value": x["value"]}
                        for x in CHOICES
                    ],
                },
            )
        with self.store.transaction() as connection:
            self.product = product_for(connection, "KB-UK-C2C")
        self.now = [0.0]
        self.server = GeminiResultViewer(
            ("127.0.0.1", 0),
            self.service,
            self.owner,
            self.product,
            CHOICES,
            UI,
            monotonic=lambda: self.now[0],
        )
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        launches = []
        self.server.launch(launches.append)
        self.capability = urlsplit(launches[0]).fragment.removeprefix("launch=")

    def stop(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, body=None, cookie=None, headers=None):
        merged = {"Sec-Fetch-Site": "same-origin"}
        if method == "POST":
            merged |= {
                "Origin": self.server.origin,
                "Content-Type": "application/json",
            }
        if cookie:
            merged["Cookie"] = cookie
        merged.update(headers or {})
        data = canonical(body) if isinstance(body, dict) else body
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=8
        )
        try:
            connection.request(method, path, data, merged)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def redeem(self):
        status, headers, _ = self.request(
            "POST", API + "/redeem", {"launch_capability": self.capability}
        )
        self.assertEqual(status, 200)
        self.assertIn(
            "HttpOnly; SameSite=Strict; Path=" + API + "; Max-Age=600",
            headers["Set-Cookie"],
        )
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_public_result_privacy_same_runtime_and_no_extra_dispatch(self):
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            cookie = self.redeem()
            status, headers, raw = self.request(
                "GET", API + "/bootstrap", cookie=cookie
            )
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertEqual(data["catalog"], [self.product])
        self.assertEqual(data["checkout"], self.result["checkout"])
        self.assertTrue(data["viewer"]["review_only"])
        self.assertNotIn("csrf_token", data)
        for secret in (
            self.owner,
            csrf_for(self.owner),
            self.capability,
            cookie.split("=", 1)[1],
            "fabricated-gemini-key-not-real",
            "project_private_fake",
            "credential_fake_v1",
            "host_fake_v1",
        ):
            self.assertNotIn(secret, raw.decode())
            self.assertNotIn(secret, output.getvalue())
        self.assertNotEqual(cookie, "cr_viewer=" + self.owner)
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIs(self.server.service, self.service)
        self.assertIs(self.server.service.store, self.store)
        self.assertEqual(self.wire["calls"], 1)
        self.assertEqual(self.handle.calls, 1)

    def test_missing_wrong_owner_and_duplicate_cookie_never_create_session(
        self,
    ):
        with patch.object(
            self.store,
            "session",
            side_effect=AssertionError("No owner creation"),
        ):
            for cookie in (
                None,
                "cr_session=" + self.owner,
                "cr_viewer=" + "x" * 43,
                "cr_viewer=" + "x" * 43 + "; cr_viewer=" + "y" * 43,
            ):
                self.assertEqual(
                    self.request("GET", API + "/bootstrap", cookie=cookie)[0],
                    403,
                )

    def test_all_mutations_and_unsupported_methods_denied_before_service(self):
        cookie = self.redeem()
        paths = ["/api/analyze", "/api/confirm", "/api/refresh", "/api/orders"]
        paths += [
            "/api/orders/00000000-0000-4000-8000-000000000000/" + action
            for action in (
                "fixture-approve",
                "buyer-return",
                "verify",
                "capture",
                "reconcile",
            )
        ]
        with (
            patch.object(
                self.service,
                "mutate",
                side_effect=AssertionError("No mutation"),
            ),
            patch.object(
                self.store,
                "session",
                side_effect=AssertionError("No owner creation"),
            ),
        ):
            for supplied in (cookie, "cr_session=" + self.owner):
                for path in paths:
                    self.assertEqual(
                        self.request(
                            "POST",
                            path,
                            {},
                            supplied,
                            {"X-CSRF-Token": csrf_for(self.owner)},
                        )[0],
                        403,
                    )
            for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
                self.assertEqual(
                    self.request(method, API + "/bootstrap", cookie=cookie)[0],
                    405,
                )
        self.assertEqual(self.wire["calls"], 1)

    def test_redemption_headers_shape_wrong_cookie_and_single_use(self):
        body = {"launch_capability": self.capability}
        cases = [
            (body, {"Origin": "http://evil.invalid"}, None),
            (body, {"Host": "localhost:" + str(self.server.server_port)}, None),
            (body, {"Sec-Fetch-Site": "cross-site"}, None),
            (body, {"Sec-Fetch-Site": "none"}, None),
            ({**body, "owner": self.owner}, {}, None),
            ({"launch_capability": "x" * 43}, {}, None),
            (body, {}, "cr_viewer=" + "x" * 43),
            (
                '{"launch_capability":"'
                + self.capability
                + '","launch_capability":"'
                + self.capability
                + '"}',
                {},
                None,
            ),
            ("[]", {}, None),
            (body, {}, "cr_viewer =bad"),
            (body, {}, "cr_viewer"),
            (body, {}, "other=x; other=y"),
        ]
        with patch.object(
            self.store,
            "session",
            side_effect=AssertionError("No owner creation"),
        ):
            for value, headers, cookie in cases:
                self.assertIn(
                    self.request(
                        "POST", API + "/redeem", value, cookie, headers
                    )[0],
                    (400, 403),
                )
            cookie = self.redeem()
            self.assertEqual(
                self.request("POST", API + "/redeem", body)[0], 403
            )
            self.assertEqual(
                self.request("POST", API + "/redeem", body, cookie)[0], 403
            )
            self.assertEqual(
                self.request(
                    "GET",
                    API + "/bootstrap",
                    cookie=cookie,
                    headers={"Sec-Fetch-Site": "cross-site"},
                )[0],
                403,
            )

    def test_atomic_redemption_race_one_winner(self):
        barrier = threading.Barrier(8)

        def attempt(_):
            barrier.wait(5)
            return self.request(
                "POST", API + "/redeem", {"launch_capability": self.capability}
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(result[0] == 200 for result in results), 1)
        self.assertEqual(
            sum("Set-Cookie" in result[1] for result in results), 1
        )
        self.assertEqual(self.wire["calls"], 1)

    def test_launch_and_session_nonrenewing_expiry(self):
        self.now[0] = 60
        self.assertEqual(
            self.request(
                "POST", API + "/redeem", {"launch_capability": self.capability}
            )[0],
            403,
        )
        self.now[0] = 0  # synthetic clock rewind, no runner or dispatch replay
        cookie = self.redeem()
        self.now[0] = 599
        self.assertEqual(
            self.request("GET", API + "/bootstrap", cookie=cookie)[0], 200
        )
        self.now[0] = 600
        self.assertEqual(
            self.request("GET", API + "/bootstrap", cookie=cookie)[0], 403
        )
        self.assertEqual(
            self.request(
                "POST", API + "/redeem", {"launch_capability": self.capability}
            )[0],
            403,
        )

    def test_expiry_and_catalog_change_retain_historical_evidence(self):
        cookie = self.redeem()
        self.service.clock = lambda: datetime.fromtimestamp(
            NOW + 101, timezone.utc
        )
        changed = copy.deepcopy(self.product)
        changed["price_minor"] += 1
        self.store.replace_product(changed)
        status, _, raw = self.request("GET", API + "/bootstrap", cookie=cookie)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertTrue(data["checkout"]["stale"])
        self.assertFalse(data["providers"]["analysis"]["dispatch_available"])
        self.assertEqual(data["catalog"], [self.product])
        self.assertEqual(
            data["checkout"]["analysis"]["evidence_kind"], "fabricated-offline"
        )
        self.assertEqual(self.wire["calls"], 1)

    def test_static_scope_and_duplicate_launch(self):
        status, headers, raw = self.request("GET", "/viewer")
        self.assertEqual(status, 200)
        self.assertIn("'sha256-", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertNotIn(self.capability, raw.decode())
        with self.assertRaises(AppError):
            self.server.launch(lambda _: None)
        for path in (
            "/",
            "/app.mjs",
            "/payment-return",
            "/api/bootstrap",
            "/viewer?owner=bad",
        ):
            self.assertIn(self.request("GET", path)[0], (403, 404))

    def test_duplicate_framing_headers_fail_closed(
        self,
    ):
        body = canonical({"launch_capability": self.capability}).encode()
        cases = [
            [
                ("Content-Length", str(len(body))),
                ("Content-Length", str(len(body))),
            ],
            [
                ("Content-Length", str(len(body))),
                ("Transfer-Encoding", "chunked"),
            ],
            [
                ("Content-Length", str(len(body))),
                ("Cookie", "cr_viewer=" + "x" * 43),
                ("Cookie", "cr_viewer=" + "y" * 43),
            ],
        ]
        for extras in cases:
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.server.server_port, timeout=8
            )
            try:
                connection.putrequest("POST", API + "/redeem")
                connection.putheader("Origin", self.server.origin)
                connection.putheader("Sec-Fetch-Site", "same-origin")
                connection.putheader("Content-Type", "application/json")
                for name, value in extras:
                    connection.putheader(name, value)
                connection.endheaders(body)
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()
        # Denied framing did not consume the launch capability.
        self.redeem()

    def test_server_close_joins_incomplete_request_and_revokes_capabilities(
        self,
    ):
        connection = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=8
        )
        connection.sendall(
            (
                "POST "
                + API
                + "/redeem HTTP/1.1\r\nHost: "
                + self.server.allowed_host
                + "\r\nOrigin: "
                + self.server.origin
                + "\r\nSec-Fetch-Site: same-origin\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
            ).encode()
        )
        # HTTP handler socket timeout bounds an incomplete body; close must join.
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        connection.close()
        self.assertIsNone(self.server._launch_token)
        self.assertIsNone(self.server._viewer_token)
        self.assertEqual(self.wire["calls"], 1)

    def test_injected_opener_can_fetch_before_return_and_shutdown_is_joined(
        self,
    ):
        import test_gemini_runner as runner_fixtures

        runner = runner_fixtures.runner
        created = []

        @contextlib.contextmanager
        def opened(*_args):
            yield (
                self.service,
                self.owner,
                {"catalog": self.product, "conditions": CHOICES},
            )

        def construct(*args):
            server = GeminiResultViewer(*args)
            created.append(server)
            return server

        def opener(url):
            parsed = urlsplit(url)
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=3
            )
            try:
                connection.request("GET", "/viewer")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                self.assertIs(created[0].service, self.service)
                self.assertIs(created[0].service.store, self.store)
            finally:
                connection.close()
            raise KeyboardInterrupt()

        with (
            patch.object(runner, "_approved_service", opened),
            patch.object(
                runner, "_analyze", return_value=self.result
            ) as analyze,
            patch(
                "cartreadback_app.gemini_viewer.GeminiResultViewer",
                side_effect=construct,
            ),
        ):
            runner.view(
                self.store.path, "synthetic-unused-owner-file", {}, 3, opener
            )
        analyze.assert_called_once()
        self.assertTrue(created[0]._stopped)
        self.assertIsNone(created[0]._launch_token)
        self.assertIsNone(created[0]._viewer_token)
        self.assertEqual(self.wire["calls"], 1)

    def test_fabricated_opener_exception_cannot_echo_private_url(self):
        server = GeminiResultViewer(
            ("127.0.0.1", 0),
            self.service,
            self.owner,
            self.product,
            CHOICES,
            UI,
        )
        try:

            def opener(url):
                raise ValueError(url)

            with self.assertRaises(AppError) as caught:
                server.launch(opener)
            self.assertNotIn("launch=", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertIsNone(server._launch_token)
        finally:
            server.server_close()

    def test_changed_scope_and_nonloopback_rejected(self):
        with self.assertRaises(AppError):
            GeminiResultViewer(
                ("127.0.0.1", 0),
                self.service,
                self.owner,
                self.product,
                [
                    {
                        "condition_id": "c1",
                        "kind": "layout",
                        "value": "DE_QWERTZ",
                    }
                ],
                UI,
            )
        with self.assertRaises(AppError):
            GeminiResultViewer(
                ("0.0.0.0", 0),
                self.service,
                self.owner,
                self.product,
                CHOICES,
                UI,
            )
