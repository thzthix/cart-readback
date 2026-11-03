"""Independent actual loopback HTTP probes, not rendered-browser evidence."""

import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from uuid import uuid4

from cartreadback_app.http import LocalServer
from cartreadback_app.service import Service
from cartreadback_app.storage import Store


class IndependentHttpTests(unittest.TestCase):
    """Use real local sockets with fresh fixtures and no external requests."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "http-review.sqlite3")
        self.service = Service(self.store)
        self.server = LocalServer(
            ("127.0.0.1", 0),
            self.service,
            Path(__file__).resolve().parents[1] / "ui",
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""
        self.csrf = ""
        self.addCleanup(self.close)
        status, headers, data = self.request("GET", "/api/bootstrap")
        self.assertEqual(200, status)
        self.cookie = headers["set-cookie"].split(";", 1)[0]
        self.csrf = data["csrf_token"]
        self.initial = data

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def request(self, method, path, payload=None, override=None, raw=None):
        body = (
            raw
            if raw is not None
            else (json.dumps(payload).encode() if payload is not None else None)
        )
        headers = {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method == "POST":
            headers.update(
                {
                    "Origin": self.server.origin,
                    "X-CSRF-Token": self.csrf,
                    "Content-Type": "application/json",
                }
            )
        for key, value in (override or {}).items():
            if value is None:
                headers.pop(key, None)
            else:
                headers[key] = value
        connection = HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            response_headers = dict(
                (k.lower(), v) for k, v in response.getheaders()
            )
            content = response.read()
            data = (
                json.loads(content)
                if content
                and response_headers.get("content-type", "").startswith(
                    "application/json"
                )
                else content
            )
            return response.status, response_headers, data
        finally:
            connection.close()

    def test_bootstrap_has_fixture_notice_cookie_and_security_headers(self):
        status, headers, data = self.request("GET", "/api/bootstrap")
        self.assertEqual(200, status)
        self.assertEqual("fixture", data["mode"])
        self.assertIn("No money", data["notice"])
        self.assertEqual(6, len(data["catalog"]))
        self.assertEqual("no-store", headers["cache-control"])
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertIn(
            "frame-ancestors 'none'", headers["content-security-policy"]
        )
        _, headers, _ = self.request(
            "GET", "/api/bootstrap", override={"Cookie": None}
        )
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, headers["set-cookie"])

    def test_transport_guards_reject_cross_origin_missing_csrf_and_bad_host(
        self,
    ):
        payload = {
            "expected_revision": 0,
            "sku_id": self.initial["catalog"][0]["sku_id"],
            "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
        }
        cases = [
            ({"Origin": "https://attacker.invalid"}, 403),
            ({"Origin": None}, 403),
            ({"Host": "attacker.invalid"}, 403),
            ({"X-CSRF-Token": None}, 403),
            ({"Cookie": None}, 403),
            ({"Sec-Fetch-Site": "cross-site"}, 403),
            ({"Content-Type": "text/plain"}, 415),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                status, _, data = self.request(
                    "POST", "/api/analyze", payload, headers
                )
                self.assertEqual(expected, status)
                self.assertIn("error", data)
        self.assertEqual(
            0, self.request("GET", "/api/bootstrap")[2]["revision"]
        )

    def test_malformed_body_matrix_is_structured_without_business_mutation(
        self,
    ):
        for raw, expected in [
            (b'{"expected_revision":0,"expected_revision":1}', 400),
            (b'{"expected_revision":NaN}', 400),
            (b'{"expected_revision":Infinity}', 400),
            (b'{"x":"\xff"}', 400),
            (b"[]", 400),
            (b"{} garbage", 400),
            (b'{"x":' + b"[" * 20 + b"0" + b"]" * 20 + b"}", 400),
            (b"x" * 16385, 413),
        ]:
            with self.subTest(raw=raw[:70]):
                status, _, data = self.request("POST", "/api/analyze", raw=raw)
                self.assertEqual(expected, status)
                self.assertIn("error", data)
        self.assertEqual(
            0, self.request("GET", "/api/bootstrap")[2]["revision"]
        )

    def test_extra_money_fields_bool_revision_and_duplicate_conditions_rejected(
        self,
    ):
        original = {
            "expected_revision": 0,
            "sku_id": self.initial["catalog"][0]["sku_id"],
            "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
        }
        cases = [
            {**original, "amount_minor": 1},
            {**original, "owner": self.cookie},
            {**original, "expected_revision": False},
            {**original, "conditions": original["conditions"] * 2},
            {**original, "sku_id": "not-a-catalog-sku"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                status, _, data = self.request("POST", "/api/analyze", payload)
                self.assertIn(status, {400, 404})
                self.assertIn("error", data)
        self.assertEqual(
            0, self.request("GET", "/api/bootstrap")[2]["revision"]
        )

    def test_get_head_unknown_routes_and_queries_cannot_approve_or_capture(
        self,
    ):
        for method, path, expected in [
            ("GET", "/api/orders", 404),
            ("HEAD", "/api/confirm", 404),
            ("GET", "/api/orders/" + str(uuid4()) + "/capture", 404),
            ("GET", "/api/bootstrap?order=forged", 400),
            ("GET", "/../cartreadback_app/service.py", 404),
            ("TRACE", "/api/bootstrap", 405),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(expected, self.request(method, path)[0])
        self.assertEqual(
            0, self.request("GET", "/api/bootstrap")[2]["revision"]
        )

    def test_http_full_fixture_flow_and_idempotency_payload_conflict(self):
        def post(path, fields, key=None):
            current = self.request("GET", "/api/bootstrap")[2]
            payload = {"expected_revision": current["revision"], **fields}
            if path != "/api/analyze":
                payload.setdefault(
                    "snapshot_hash", current["checkout"]["snapshot_hash"]
                )
            headers = {"Idempotency-Key": key} if key else {}
            status, _, data = self.request("POST", path, payload, headers)
            self.assertEqual(200, status, data)
            return data

        current = post(
            "/api/analyze",
            {
                "sku_id": self.initial["catalog"][0]["sku_id"],
                "conditions": [{"kind": "layout", "value": "UK_QWERTY"}],
            },
        )
        review = current["checkout"]
        current = post(
            "/api/confirm",
            {
                "review_id": review["review_id"],
                "confirmed_sku_id": review["sku_id"],
                "confirmed_condition_ids": ["c1"],
                "acknowledged_unknown_ids": [],
                "acknowledged_conflict_ids": [],
            },
        )
        key = str(uuid4())
        current = post(
            "/api/orders",
            {
                "review_id": review["review_id"],
                "confirmation_id": current["checkout"]["confirmation_id"],
            },
            key,
        )
        order_path = "/api/orders/" + current["checkout"]["order"]["order_id"]
        self.assertEqual("ORDER_CREATED", current["checkout"]["state"])
        status, _, data = self.request(
            "POST",
            "/api/orders",
            {
                "expected_revision": current["revision"],
                "snapshot_hash": review["snapshot_hash"],
                "review_id": "different-review",
                "confirmation_id": current["checkout"]["confirmation_id"],
            },
            {"Idempotency-Key": key},
        )
        self.assertEqual(409, status)
        self.assertEqual("IDEMPOTENCY_CONFLICT", data["error"]["code"])
        post(order_path + "/fixture-approve", {})
        current = post(order_path + "/verify", {})
        current = post(
            order_path + "/capture",
            {
                "confirmation_id": current["checkout"]["confirmation_id"],
                "final_confirmation": True,
            },
            str(uuid4()),
        )
        self.assertEqual("COMPLETED", current["checkout"]["state"])


if __name__ == "__main__":
    unittest.main()
