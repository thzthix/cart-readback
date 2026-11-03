"""Offline buyer-return binding tests, not PayPal/network/browser evidence."""

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cartreadback_app.http import LocalServer
from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.paypal_sandbox import (
    ORDER_PATH,
    OfflinePayPalSandboxAdapter,
)
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical
from test_domain import Workflow
from test_paypal_sandbox import MERCHANT, PROVIDER_ID, MemoryTransport

ORIGIN = "http://127.0.0.1:8765"


class BuyerReturnTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "db.sqlite3"
        self.store = Store(self.path)
        self.transport = MemoryTransport(self.path)
        self.adapter = OfflinePayPalSandboxAdapter(
            self.transport, MERCHANT, buyer_return_origin=ORIGIN
        )
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.service = Service(
            self.store, payments=self.adapter, clock=lambda: self.now
        )
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        request = json.loads(self.transport.calls[0][1].body)
        self.context = request["payment_source"]["paypal"]["experience_context"]
        self.state = parse_qs(urlsplit(self.context["return_url"]).query)[
            "state"
        ][0]

    def return_body(self, **extra):
        return {
            "expected_revision": self.flow.result["revision"],
            "snapshot_hash": self.flow.checkout["snapshot_hash"],
            "return_state": self.state,
            "provider_order_id": PROVIDER_ID,
            "outcome": "approved",
            **extra,
        }

    def perform(self, **extra):
        self.flow.result = self.service.mutate(
            self.flow.sid,
            "buyer-return",
            self.return_body(**extra),
            self.flow.checkout["order"]["order_id"],
        )
        return self.flow.checkout

    def test_modes_and_secret_are_separate(self):
        self.assertEqual("offline", self.flow.result["mode"])
        self.assertEqual(
            {
                "analysis": {"mode": "fixture", "is_fixture": True},
                "payment": {
                    "mode": "paypal-sandbox-offline",
                    "is_fixture": False,
                },
                "network_enabled": False,
            },
            self.flow.result["providers"],
        )
        public = canonical(self.service.bootstrap(self.flow.sid))
        self.assertNotIn(self.state, public)
        self.assertNotIn("state_hash", public)
        self.assertNotIn("approval_return", public)
        self.assertEqual("CONTINUE", self.context["user_action"])
        self.assertEqual("NO_SHIPPING", self.context["shipping_preference"])
        self.assertEqual(
            "cancelled",
            parse_qs(urlsplit(self.context["cancel_url"]).query)["outcome"][0],
        )
        self.assertEqual(
            f"https://www.sandbox.paypal.com/checkoutnow?token={PROVIDER_ID}",
            self.flow.checkout["order"]["approval_url"],
        )

    def test_return_is_recheck_only_and_final_intent_is_separate(self):
        self.transport.document["status"] = "APPROVED"
        returned = self.perform()
        self.assertEqual("SERVER_RECHECKED", returned["state"])
        self.assertTrue(returned["order"]["buyer_return"]["consumed"])
        self.assertEqual(
            ["POST", "GET"], [c[1].method for c in self.transport.calls]
        )
        self.flow.action("capture")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        posts = [
            c[1].path for c in self.transport.calls if c[1].method == "POST"
        ]
        self.assertEqual(
            [ORDER_PATH, f"{ORDER_PATH}/{PROVIDER_ID}/capture"], posts
        )

    def test_forged_approval_query_does_not_establish_approval(self):
        checkout = self.perform()
        self.assertEqual("ORDER_CREATED", checkout["state"])
        self.assertTrue(checkout["order"]["buyer_return"]["consumed"])
        with self.assertRaises(AppError):
            self.flow.action("capture")
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_cancel_retains_order_and_does_not_void_or_recreate(self):
        checkout = self.perform(outcome="cancelled")
        self.assertEqual("ORDER_CREATED", checkout["state"])
        self.assertTrue(checkout["order"]["buyer_return"]["cancelled"])
        self.assertEqual(2, len(self.transport.calls))
        with self.assertRaises(AppError):
            self.flow.create()
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_invalid_state_token_types_and_outcome_fail_before_lookup(self):
        for extra in (
            {"return_state": "x" * 43},
            {"return_state": []},
            {"return_state": True},
            {"provider_order_id": "OTHERORDER"},
            {"provider_order_id": []},
            {"outcome": "completed"},
            {"outcome": []},
            {"outcome": True},
            {"snapshot_hash": "x" * 64},
            {"expected_revision": 0},
        ):
            with self.subTest(extra=extra), self.assertRaises(AppError):
                self.perform(**extra)
        self.assertEqual(1, len(self.transport.calls))

    def test_foreign_owner_cannot_use_copied_state(self):
        foreign = self.store.session(None)[0]["sid"]
        with self.assertRaises(AppError):
            self.service.mutate(
                foreign,
                "buyer-return",
                self.return_body(expected_revision=0),
                self.flow.checkout["order"]["order_id"],
            )
        self.assertEqual(1, len(self.transport.calls))

    def test_expired_return_cannot_dispatch_lookup(self):
        self.now += timedelta(minutes=20)
        with self.assertRaises(AppError) as caught:
            self.perform()
        self.assertEqual("RETURN_REJECTED", caught.exception.code)
        self.assertEqual(1, len(self.transport.calls))

    def test_replay_is_rejected_after_cancel_with_current_revision(self):
        self.perform(outcome="cancelled")
        with self.assertRaises(AppError) as caught:
            self.perform(outcome="cancelled")
        self.assertEqual("RETURN_REJECTED", caught.exception.code)
        self.assertEqual(2, len(self.transport.calls))

    def test_timeout_consumes_return_and_preserves_same_unknown_order(self):
        self.transport.forced_response = TimeoutError("not public")
        checkout = self.perform()
        self.assertEqual("PAYMENT_UNKNOWN", checkout["state"])
        self.assertTrue(checkout["order"]["buyer_return"]["consumed"])
        self.assertEqual(PROVIDER_ID, checkout["order"]["provider_order_id"])
        self.transport.forced_response = None
        self.flow.action("reconcile")
        self.assertEqual("ORDER_CREATED", self.flow.checkout["state"])
        with self.assertRaises(AppError):
            self.perform()
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_incomplete_or_mismatched_returned_facts_cannot_capture(self):
        self.transport.document["status"] = "APPROVED"
        self.transport.document["purchase_units"][0]["custom_id"] = "c" * 64
        self.assertEqual("PAYMENT_UNKNOWN", self.perform()["state"])
        with self.assertRaises(AppError):
            self.flow.action("capture")

    def test_restart_retains_return_state_and_same_operation(self):
        self.service.close()
        self.service = Service(
            self.store, payments=self.adapter, clock=lambda: self.now
        )
        self.flow.service = self.service
        self.transport.document["status"] = "APPROVED"
        self.assertEqual("SERVER_RECHECKED", self.perform()["state"])
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_concurrent_return_only_commits_once_and_never_captures(self):
        self.transport.document["status"] = "APPROVED"
        body = self.return_body()
        order_id = self.flow.checkout["order"]["order_id"]

        def run():
            try:
                return self.service.mutate(
                    self.flow.sid, "buyer-return", body, order_id
                )
            except AppError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(1, sum(type(result) is dict for result in results))
        self.flow.result = self.service.bootstrap(self.flow.sid)
        # The conservative single-flight gate can commit UNKNOWN before the
        # valid read. A later result cannot overwrite that newer observation.
        self.assertIn(
            self.flow.checkout["state"], {"SERVER_RECHECKED", "PAYMENT_UNKNOWN"}
        )
        self.assertTrue(self.flow.checkout["order"]["buyer_return"]["consumed"])
        if self.flow.checkout["state"] == "PAYMENT_UNKNOWN":
            self.flow.action("reconcile")
            self.flow.action("verify")
        self.assertEqual("SERVER_RECHECKED", self.flow.checkout["state"])
        self.assertEqual(order_id, self.flow.checkout["order"]["order_id"])
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_single_flight_return_race_preserves_unknown_until_reconciled(self):
        self.transport.document["status"] = "APPROVED"
        started, release = threading.Event(), threading.Event()
        original_send = self.transport.send

        def delayed_send(endpoint, request, headers, *, timeout_seconds):
            if request.method == "GET" and not release.is_set():
                started.set()
                release.wait(1)
            return original_send(
                endpoint, request, headers, timeout_seconds=timeout_seconds
            )

        self.transport.send = delayed_send
        body = self.return_body()
        order_id = self.flow.checkout["order"]["order_id"]
        results = []

        def first_return():
            try:
                results.append(
                    self.service.mutate(
                        self.flow.sid, "buyer-return", body, order_id
                    )
                )
            except AppError as error:
                results.append(error.code)

        thread = threading.Thread(target=first_return)
        thread.start()
        try:
            self.assertTrue(started.wait(1))
            self.flow.result = self.service.mutate(
                self.flow.sid, "buyer-return", body, order_id
            )
            self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
            self.assertTrue(
                self.flow.checkout["order"]["buyer_return"]["consumed"]
            )
        finally:
            release.set()
            thread.join(2)
        self.assertEqual(["STALE_REVISION"], results)
        self.flow.action("reconcile")
        self.flow.action("verify")
        self.assertEqual("SERVER_RECHECKED", self.flow.checkout["state"])
        self.assertEqual(order_id, self.flow.checkout["order"]["order_id"])
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_callback_config_changes_wire_identity_and_rejects_unsafe_origins(
        self,
    ):
        no_return = OfflinePayPalSandboxAdapter(self.transport, MERCHANT)
        self.assertNotEqual(no_return.version, self.adapter.version)
        for origin in (
            "https://evil.test",
            "http://localhost:8765",
            "http://127.0.0.1:0",
            "http://127.0.0.1:65536",
            ORIGIN + "/",
            ORIGIN + "@evil.test",
        ):
            with self.subTest(origin=origin), self.assertRaises(AppError):
                OfflinePayPalSandboxAdapter(
                    self.transport, MERCHANT, buyer_return_origin=origin
                )

    def test_source_changed_return_is_stale_and_not_queried(self):
        self.service.inference = deepcopy(FixtureInferenceAdapter())
        self.service.inference.metadata = {
            **self.service.inference.metadata,
            "prompt_version": "changed",
        }
        with self.assertRaises(AppError) as caught:
            self.perform()
        self.assertEqual("STALE_SNAPSHOT", caught.exception.code)
        self.assertEqual(1, len(self.transport.calls))


class ReturnHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name) / "http.sqlite3")
        self.service = Service(self.store)
        self.addCleanup(self.service.close)
        ui = Path(__file__).resolve().parents[1] / "ui"
        self.server = LocalServer(("127.0.0.1", 0), self.service, ui)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.stop)
        transport = MemoryTransport(self.store.path)
        self.service.payments = OfflinePayPalSandboxAdapter(
            transport, MERCHANT, buyer_return_origin=self.server.origin
        )
        self.transport = transport
        self.flow = Workflow(self.service)
        self.flow.analyze()
        self.flow.confirm()
        self.flow.create()
        context = json.loads(transport.calls[0][1].body)["payment_source"][
            "paypal"
        ]["experience_context"]
        self.path = (
            urlsplit(context["return_url"]).path
            + "?"
            + urlsplit(context["return_url"]).query
            + "&token="
            + PROVIDER_ID
        )
        self.state = parse_qs(urlsplit(self.path).query)["state"][0]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, method, path, body=None, **headers):
        connection = HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            connection.request(
                method,
                path,
                body=canonical(body) if body else None,
                headers=headers,
            )
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_get_return_with_no_cookie_is_inert_and_does_not_create_session(
        self,
    ):
        before = self.service.bootstrap(self.flow.sid)
        with self.store.transaction() as connection:
            count = connection.execute(
                "SELECT count(*) FROM sessions"
            ).fetchone()[0]
        status, data, headers = self.request("GET", self.path)
        self.assertEqual(200, status)
        self.assertIn(b"<!doctype html>", data)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual("no-referrer", headers["Referrer-Policy"])
        self.assertNotIn(self.state.encode(), data)
        self.assertEqual(before, self.service.bootstrap(self.flow.sid))
        with self.store.transaction() as connection:
            self.assertEqual(
                count,
                connection.execute("SELECT count(*) FROM sessions").fetchone()[
                    0
                ],
            )
        self.assertEqual(1, len(self.transport.calls))
        # Query stripping must leave a reloadable, equally inert landing page.
        self.assertEqual(200, self.request("GET", "/payment-return")[0])
        self.assertEqual(before, self.service.bootstrap(self.flow.sid))

    def test_query_rejections_and_post_csrf_guards(self):
        for path in (
            self.path + "&state=" + self.state,
            self.path + "&redirect=https://evil.test",
            self.path.replace("outcome=approved", "outcome=captured"),
            self.path.replace("token=" + PROVIDER_ID, "token="),
            "/api/bootstrap?state=" + self.state,
        ):
            with self.subTest(path=path):
                self.assertEqual(400, self.request("GET", path)[0])
        route = (
            "/api/orders/"
            + self.flow.checkout["order"]["order_id"]
            + "/buyer-return"
        )
        body = {
            "expected_revision": self.flow.result["revision"],
            "snapshot_hash": self.flow.checkout["snapshot_hash"],
            "return_state": self.state,
            "provider_order_id": PROVIDER_ID,
            "outcome": "approved",
        }
        headers = {
            "Origin": self.server.origin,
            "Content-Type": "application/json",
            "Cookie": "cr_session=" + self.flow.sid,
            "X-CSRF-Token": self.flow.result.get(
                "csrf_token",
                self.service.bootstrap(self.flow.sid)["csrf_token"],
            ),
        }
        no_csrf = {
            key: value
            for key, value in headers.items()
            if key != "X-CSRF-Token"
        }
        self.assertEqual(403, self.request("POST", route, body, **no_csrf)[0])
        self.assertEqual(
            403,
            self.request(
                "POST",
                route,
                body,
                **{**headers, "Origin": "https://evil.test"},
            )[0],
        )
        self.assertEqual(1, len(self.transport.calls))
        self.transport.document["status"] = "APPROVED"
        status, raw, _ = self.request("POST", route, body, **headers)
        self.assertEqual(200, status, raw)
        result = json.loads(raw)
        self.assertEqual("offline", result["mode"])
        self.assertEqual("SERVER_RECHECKED", result["checkout"]["state"])
        self.assertEqual(
            ["POST", "GET"], [c[1].method for c in self.transport.calls]
        )

    def test_static_callback_query_is_never_a_post_action(self):
        self.assertEqual(400, self.request("POST", self.path, {})[0])
        self.assertEqual(1, len(self.transport.calls))

    def test_wrong_bound_callback_origin_rejects_server_setup(self):
        with self.assertRaises(ValueError):
            LocalServer(
                ("127.0.0.1", 0), self.service, Path(self.temporary.name)
            )


if __name__ == "__main__":
    unittest.main()
