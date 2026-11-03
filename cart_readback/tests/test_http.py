"""Actual loopback HTTP checks, not direct handler calls or mocked requests."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from uuid import uuid4

from cartreadback_app.http import LocalServer
from cartreadback_app.service import Service
from cartreadback_app.storage import Store


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.temp.name) / "http.db")
        cls.service = Service(cls.store)
        # HTTP-owned sentinels, not production UI or browser integration evidence.
        cls.ui = Path(cls.temp.name) / "http-static-sentinels"
        cls.ui.mkdir()
        cls.assets = {
            "index.html": b"<!doctype html><!-- HTTP test sentinel -->",
            "app.mjs": b"// HTTP test app sentinel\n",
            "core.mjs": b"// HTTP test core sentinel\n",
            "styles.css": b"/* HTTP test style sentinel */\n",
        }
        for name, content in cls.assets.items():
            (cls.ui / name).write_bytes(content)
        (cls.ui / "not-allowlisted.txt").write_text(
            "HTTP test private sentinel"
        )
        ui = cls.ui
        cls.server = LocalServer(("127.0.0.1", 0), cls.service, ui)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = cls.server.origin

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.temp.cleanup()

    def setUp(self):
        self.cookie = None
        self.csrf = None
        self.result = self.request("GET", "/api/bootstrap")[1]
        self.csrf = self.result["csrf_token"]

    def request(
        self, method, path, body=None, headers=None, raw=None, cookie=True
    ):
        supplied = {
            "Origin": self.origin,
            "Content-Type": "application/json",
        }
        if self.cookie and cookie:
            supplied["Cookie"] = self.cookie
        if self.csrf:
            supplied["X-CSRF-Token"] = self.csrf
        supplied.update(headers or {})
        for key in list(supplied):
            if supplied[key] is None:
                del supplied[key]
        content = (
            raw
            if raw is not None
            else json.dumps(body).encode()
            if body is not None
            else None
        )
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body=content, headers=supplied)
            response = conn.getresponse()
            data = response.read()
            if response.getheader("Set-Cookie"):
                self.cookie = response.getheader("Set-Cookie").split(";", 1)[0]
            content_type = response.getheader("Content-Type", "")
            payload = (
                json.loads(data)
                if content_type.startswith("application/json") and data
                else data
            )
            return response.status, payload, dict(response.getheaders())
        finally:
            conn.close()

    def analyze(self, sku="KB-UK-C2C"):
        status, result, _ = self.request(
            "POST",
            "/api/analyze",
            {
                "expected_revision": self.result["revision"],
                "sku_id": sku,
                "conditions": [
                    {"kind": "layout", "value": "UK_QWERTY"},
                    {"kind": "included_cable", "value": "USB-C to USB-C"},
                ],
            },
        )
        self.assertEqual(200, status, result)
        self.result = result

    def confirm(self):
        c = self.result["checkout"]
        status, result, _ = self.request(
            "POST",
            "/api/confirm",
            {
                "expected_revision": self.result["revision"],
                "review_id": c["review_id"],
                "snapshot_hash": c["snapshot_hash"],
                "confirmed_sku_id": c["sku_id"],
                "confirmed_condition_ids": [
                    i["condition_id"] for i in c["conditions"]
                ],
                "acknowledged_unknown_ids": [
                    i["condition_id"]
                    for i in c["results"]
                    if i["status"] == "unknown"
                ],
                "acknowledged_conflict_ids": [
                    i["condition_id"]
                    for i in c["results"]
                    if i["status"] == "conflict"
                ],
            },
        )
        self.assertEqual(200, status, result)
        self.result = result

    def create_body(self):
        c = self.result["checkout"]
        return {
            "expected_revision": self.result["revision"],
            "review_id": c["review_id"],
            "snapshot_hash": c["snapshot_hash"],
            "confirmation_id": c["confirmation_id"],
        }

    def create(self):
        status, result, _ = self.request(
            "POST",
            "/api/orders",
            self.create_body(),
            {"Idempotency-Key": str(uuid4())},
        )
        self.assertEqual(200, status, result)
        self.result = result

    def action(self, action, extra=None):
        c = self.result["checkout"]
        body = {
            "expected_revision": self.result["revision"],
            "snapshot_hash": c["snapshot_hash"],
            **(extra or {}),
        }
        headers = (
            {"Idempotency-Key": str(uuid4())} if action == "capture" else {}
        )
        status, result, _ = self.request(
            "POST",
            f"/api/orders/{c['order']['order_id']}/{action}",
            body,
            headers,
        )
        self.assertEqual(200, status, result)
        self.result = result

    def test_cookie_and_security_response_headers(self):
        status, result, headers = self.request(
            "GET", "/api/bootstrap", cookie=False
        )
        self.assertEqual(200, status)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual("no-store", headers["Cache-Control"])
        self.assertEqual("nosniff", headers["X-Content-Type-Options"])
        self.assertIn(
            "frame-ancestors 'none'", headers["Content-Security-Policy"]
        )
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual("fixture", result["mode"])

    def test_actual_http_full_checkout_and_bootstrap_restore(self):
        self.analyze()
        self.confirm()
        self.create()
        self.action("fixture-approve")
        self.action("verify")
        self.assertEqual("SERVER_RECHECKED", self.result["checkout"]["state"])
        self.action(
            "capture",
            {
                "confirmation_id": self.result["checkout"]["confirmation_id"],
                "final_confirmation": True,
            },
        )
        status, restored, _ = self.request("GET", "/api/bootstrap")
        self.assertEqual(200, status)
        self.assertEqual("COMPLETED", restored["checkout"]["state"])
        self.assertEqual(
            self.result["checkout"]["order"], restored["checkout"]["order"]
        )

    def test_csrf_missing_wrong_and_nonascii(self):
        body = {
            "expected_revision": 0,
            "sku_id": "KB-UK-C2C",
            "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
        }
        for value in [None, "wrong-token", "é" * 20]:
            with self.subTest(value=value):
                status, result, _ = self.request(
                    "POST", "/api/analyze", body, {"X-CSRF-Token": value}
                )
                self.assertEqual(403, status)
                self.assertEqual("CSRF_REJECTED", result["error"]["code"])
        self.assertEqual(
            0, self.request("GET", "/api/bootstrap")[1]["revision"]
        )

    def test_host_origin_contenttype_and_missing_owner_fail_closed(self):
        for headers, expected in [
            ({"Host": "evil.example"}, 403),
            ({"Origin": "https://evil.example"}, 403),
            ({"Origin": None}, 403),
            ({"Origin": "null"}, 403),
            ({"Content-Type": "text/plain"}, 415),
            ({"Content-Type": "application/json; charset=utf-8"}, 415),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
            ({"Cookie": "cr_session=not-a-known-owner"}, 403),
        ]:
            status, result, _ = self.request(
                "POST", "/api/analyze", {}, headers
            )
            self.assertEqual(expected, status, result)
        self.assertEqual(
            403, self.request("POST", "/api/analyze", {}, cookie=False)[0]
        )

    def test_oversize_deep_duplicate_nonfinite_malformed_utf8_json_and_toptypes(
        self,
    ):
        bodies = [
            (b'{"x":"' + b"a" * 16384 + b'"}', 413),
            (b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}", 400),
            (b'{"expected_revision":0,"expected_revision":0}', 400),
            (b'{"x":NaN}', 400),
            (b'{"x":Infinity}', 400),
            (b'{"x":\xff}', 400),
            (b"[]", 400),
            (b"null", 400),
            (b'{"x":', 400),
        ]
        for raw, expected in bodies:
            with self.subTest(raw=raw[:30]):
                status, result, _ = self.request(
                    "POST", "/api/analyze", raw=raw
                )
                self.assertEqual(expected, status, result)
                self.assertNotIn("Traceback", json.dumps(result))
        self.analyze()  # The server still works after every malformed request.

    def test_unknown_fields_conditions_wrong_scalar_types_scenarios_and_queries(
        self,
    ):
        valid = {
            "expected_revision": 0,
            "sku_id": "KB-UK-C2C",
            "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
        }
        for field, value in [
            ("expected_revision", True),
            ("expected_revision", 0.0),
            ("sku_id", []),
            ("conditions", []),
            ("conditions", {}),
            ("conditions", [{"kind": "layout", "value": "ISO"}]),
            ("conditions", [{"kind": "layout", "value": "UK_QWERTY"}] * 2),
            ("scenario", []),
            ("scenario", {}),
            ("amount", 1),
        ]:
            status, result, _ = self.request(
                "POST", "/api/analyze", valid | {field: value}
            )
            self.assertEqual(400, status, result)
        self.assertEqual(
            400, self.request("GET", "/api/bootstrap?scenario=[]")[0]
        )
        self.assertEqual(
            400, self.request("POST", "/api/analyze?mode=real", valid)[0]
        )
        self.analyze()

    def test_unknown_sku_and_foreign_order_errors(self):
        status, _, _ = self.request(
            "POST",
            "/api/analyze",
            {
                "expected_revision": 0,
                "sku_id": "missing",
                "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
            },
        )
        self.assertEqual(404, status)
        self.analyze()
        self.confirm()
        self.create()
        order = self.result["checkout"]["order"]["order_id"]
        old_cookie, old_csrf = self.cookie, self.csrf
        self.csrf = None
        _, stranger, _ = self.request("GET", "/api/bootstrap", cookie=False)
        self.csrf = stranger["csrf_token"]
        status, result, _ = self.request(
            "POST",
            f"/api/orders/{order}/verify",
            {
                "expected_revision": 0,
                "snapshot_hash": self.result["checkout"]["snapshot_hash"],
            },
        )
        self.assertEqual(404, status, result)
        self.cookie, self.csrf = old_cookie, old_csrf

    def test_get_approve_capture_and_unsupported_methods_cannot_move_money(
        self,
    ):
        self.analyze()
        self.confirm()
        self.create()
        c = self.result["checkout"]
        for action in ["fixture-approve", "verify", "capture", "reconcile"]:
            self.assertEqual(
                404,
                self.request(
                    "GET", f"/api/orders/{c['order']['order_id']}/{action}"
                )[0],
            )
        for method in ["PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"]:
            self.assertEqual(405, self.request(method, "/api/analyze")[0])
        self.assertEqual(
            "ORDER_CREATED",
            self.request("GET", "/api/bootstrap")[1]["checkout"]["state"],
        )

    def test_http_concurrent_create_single_logical_order_and_uuid_requirement(
        self,
    ):
        self.analyze()
        self.confirm()
        body = self.create_body()
        self.assertEqual(400, self.request("POST", "/api/orders", body)[0])
        self.assertEqual(
            400,
            self.request(
                "POST", "/api/orders", body, {"Idempotency-Key": "bad-key"}
            )[0],
        )

        def create(_):
            return self.request(
                "POST", "/api/orders", body, {"Idempotency-Key": str(uuid4())}
            )[0]

        with ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(create, range(6)))
        self.assertEqual([200, 409, 409, 409, 409, 409], sorted(statuses))

    def test_static_mime_and_no_directory_or_arbitrary_file_access(self):
        for path, mime in [
            ("/", "text/html"),
            ("/app.mjs", "text/javascript"),
            ("/core.mjs", "text/javascript"),
            ("/styles.css", "text/css"),
        ]:
            status, content, headers = self.request("GET", path)
            self.assertEqual(200, status)
            filename = "index.html" if path == "/" else path[1:]
            self.assertEqual(self.assets[filename], content)
            self.assertTrue(headers["Content-Type"].startswith(mime))
        for path in [
            "/../service.py",
            "/.env",
            "/cartreadback_app/service.py",
            "/%2e%2e/README.md",
            "/not-allowlisted.txt",
        ]:
            self.assertEqual(404, self.request("GET", path)[0])

    def test_missing_allowlisted_static_file_returns_404(self):
        asset = self.ui / "styles.css"
        content = asset.read_bytes()
        asset.unlink()
        try:
            self.assertEqual(404, self.request("GET", "/styles.css")[0])
        finally:
            asset.write_bytes(content)

    def test_non_loopback_binding_is_rejected(self):
        with self.assertRaises(ValueError):
            LocalServer(("0.0.0.0", 0), self.service, Path(self.temp.name))


if __name__ == "__main__":
    unittest.main()
