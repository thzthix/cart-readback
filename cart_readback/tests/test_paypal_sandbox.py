"""Fabricated PayPal wire probes; not genuine sandbox/API acceptance evidence."""

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cartreadback_app.payments import (
    FixturePaymentAdapter,
    PaymentRequest,
    ProviderAmbiguity,
    verify_provider_order,
)
from cartreadback_app.paypal_sandbox import (
    MAX_BODY_BYTES,
    OFFLINE_MODE,
    ORDER_PATH,
    SANDBOX_ENDPOINT,
    OfflinePayPalSandboxAdapter,
    SandboxWireResponse,
    normalize_paypal_order,
    sandbox_approval_url,
)
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical
from test_domain import Workflow

MERCHANT = "SYNTHETCDEMQX"
PROVIDER_ID = "OFFLINEORDER123"
CAPTURE_ID = "OFFLINECAPTURE123"


def expectation():
    return {
        "provider_mode": OFFLINE_MODE,
        "intent": "CAPTURE",
        "merchant_id": MERCHANT,
        "reference_id": str(uuid4()),
        "custom_id": "a" * 64,
        "items": [
            {
                "sku_id": "KB-UK-C2C",
                "name": "Synthetic keyboard",
                "quantity": 1,
                "unit_amount_minor": 7900,
                "currency": "USD",
            }
        ],
        "amount_minor": 7900,
        "currency": "USD",
    }


def response(document, code=200):
    return SandboxWireResponse(code, canonical(document).encode())


class MemoryTransport:
    """One in-memory fabricated provider with no network/credentials behavior."""

    def __init__(self, path=None):
        self.path = path
        self.calls = []
        self.document = None
        self.forced_response = None
        self.fail_after_effect = False
        self.incomplete = False
        self.capture_status = "COMPLETED"

    def send(self, endpoint, request, headers, *, timeout_seconds):
        if self.path:
            # Both create/get/capture must run outside the application writer.
            connection = sqlite3.connect(self.path, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
        self.calls.append(
            (endpoint, request, deepcopy(headers), timeout_seconds)
        )
        if self.forced_response is not None:
            result = self.forced_response
            if isinstance(result, Exception):
                raise result
            return result
        if request.path == ORDER_PATH:
            self.document = {
                **json.loads(request.body),
                "id": PROVIDER_ID,
                "status": "CREATED",
                "links": [
                    {
                        "rel": "approve",
                        "method": "GET",
                        "href": f"https://www.sandbox.paypal.com/checkoutnow?token={PROVIDER_ID}",
                    }
                ],
            }
        elif request.method == "POST":
            self.document["status"] = "COMPLETED"
            self.document["purchase_units"][0]["payments"] = {
                "captures": [
                    {
                        "id": CAPTURE_ID,
                        "status": self.capture_status,
                        "amount": {"currency_code": "USD", "value": "79.00"},
                        "final_capture": True,
                    }
                ]
            }
        if self.fail_after_effect and request.method == "POST":
            raise TimeoutError("Private raw error must never be persisted")
        document = deepcopy(self.document)
        if self.incomplete:
            document = {"id": document["id"], "status": document["status"]}
        return response(document, 200 if request.method == "GET" else 201)


class SandboxMappingTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.adapter = OfflinePayPalSandboxAdapter(self.transport, MERCHANT)
        self.expected = expectation()
        self.request = self.adapter.prepare("orders", self.expected, None)

    def wire(self):
        return {
            **json.loads(self.request.body),
            "id": PROVIDER_ID,
            "status": "CREATED",
        }

    def test_prepare_is_pure_exact_usd_mapping(self):
        self.assertEqual([], self.transport.calls)
        self.assertEqual(
            PaymentRequest(
                "POST", ORDER_PATH, canonical(json.loads(self.request.body))
            ),
            self.request,
        )
        unit = json.loads(self.request.body)["purchase_units"][0]
        self.assertEqual(
            {"currency_code": "USD", "value": "79.00"},
            unit["amount"]["breakdown"]["item_total"],
        )
        self.assertEqual("1", unit["items"][0]["quantity"])
        self.assertEqual({"merchant_id": MERCHANT}, unit["payee"])
        self.assertNotIn("provider_mode", self.request.body)
        self.assertNotIn("payment_source", self.request.body)
        self.assertEqual(
            "{}",
            self.adapter.prepare("capture", self.expected, PROVIDER_ID).body,
        )

    def test_invalid_expected_facts_never_exchange(self):
        cases = [
            ("provider_mode", "live"),
            ("intent", "AUTHORIZE"),
            ("merchant_id", "ABCDEFGHJKLMN"),
            ("currency", "EUR"),
            ("amount_minor", True),
            ("amount_minor", 79.0),
            ("amount_minor", 0),
            ("amount_minor", 9999999999),
            ("reference_id", "../bad"),
            ("custom_id", "wrong"),
            ("items", []),
            ("items", [{"quantity": 2}]),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                facts = deepcopy(self.expected)
                facts[key] = value
                with self.assertRaises(AppError):
                    self.adapter.prepare("orders", facts, None)
        self.assertEqual([], self.transport.calls)

    def test_dispatch_headers_exact_bytes_and_no_authentication(self):
        operation = str(uuid4())
        document = self.adapter.dispatch(operation, self.request)
        endpoint, sent, headers, timeout = self.transport.calls[0]
        self.assertEqual(SANDBOX_ENDPOINT, endpoint)
        self.assertIs(self.request, sent)
        self.assertEqual(operation, headers["PayPal-Request-Id"])
        self.assertEqual("return=representation", headers["Prefer"])
        self.assertNotIn("Authorization", headers)
        self.assertEqual(2.0, timeout)
        self.assertEqual(OFFLINE_MODE, document["provider_mode"])
        self.assertNotIn("captures", document)
        verify_provider_order(
            document, self.expected, PROVIDER_ID, MERCHANT, {"CREATED"}
        )

    def test_get_only_uses_fixed_order_path_and_no_post_request_id(self):
        self.transport.document = self.wire()
        self.adapter.get(PROVIDER_ID)
        endpoint, sent, headers, _ = self.transport.calls[-1]
        self.assertEqual(SANDBOX_ENDPOINT, endpoint)
        self.assertEqual(
            PaymentRequest("GET", f"{ORDER_PATH}/{PROVIDER_ID}", ""), sent
        )
        self.assertNotIn("PayPal-Request-Id", headers)
        self.assertNotIn("Prefer", headers)

    def test_invalid_paths_and_ids_cannot_reach_transport(self):
        for order_id in [
            None,
            3,
            "lowercase",
            "../OTHER",
            "A?x=y",
            "A/capture",
            "A" * 37,
        ]:
            with self.subTest(order_id=order_id), self.assertRaises(AppError):
                self.adapter.get(order_id)
        for path, body in [
            ("https://api-m.paypal.com/v2/checkout/orders", self.request.body),
            ("//host/path", "{}"),
            (f"{ORDER_PATH}/A/capture?x=1", "{}"),
            (f"{ORDER_PATH}/A/capture", "{ }"),
        ]:
            with self.subTest(path=path), self.assertRaises(AppError):
                self.adapter.dispatch(
                    str(uuid4()), PaymentRequest("POST", path, body)
                )
        self.assertEqual([], self.transport.calls)

    def test_request_roundtrip_rejects_extra_or_tampered_wire(self):
        for change in ["extra", "merchant", "amount", "quantity"]:
            raw = json.loads(self.request.body)
            unit = raw["purchase_units"][0]
            if change == "extra":
                raw["payment_source"] = {"card": {}}
            elif change == "merchant":
                unit["payee"]["merchant_id"] = "ABCDEFGHJKLMN"
            elif change == "amount":
                unit["amount"]["value"] = "79.000"
            else:
                unit["items"][0]["quantity"] = 1
            with self.subTest(change=change), self.assertRaises(AppError):
                self.adapter.dispatch(
                    str(uuid4()),
                    PaymentRequest("POST", ORDER_PATH, canonical(raw)),
                )
        for operation in ["browser-key", "", True, str(uuid4()).upper()]:
            with self.subTest(operation=operation), self.assertRaises(AppError):
                self.adapter.dispatch(operation, self.request)
        self.assertEqual([], self.transport.calls)

    def test_only_returned_facts_are_normalized(self):
        document = normalize_paypal_order(
            {"id": PROVIDER_ID, "status": "CREATED"}
        )
        self.assertEqual(
            {
                "provider_mode": OFFLINE_MODE,
                "provider_order_id": PROVIDER_ID,
                "status": "CREATED",
            },
            document,
        )
        for field in ["payee", "items", "custom_id", "reference_id", "amount"]:
            raw = self.wire()
            del raw["purchase_units"][0][field]
            normalized = normalize_paypal_order(raw)
            with self.subTest(field=field), self.assertRaises(AppError):
                verify_provider_order(
                    normalized,
                    self.expected,
                    PROVIDER_ID,
                    MERCHANT,
                    {"CREATED"},
                )

    def test_no_request_copied_over_mismatched_provider_facts(self):
        raw = self.wire()
        raw["purchase_units"][0]["payee"]["merchant_id"] = "ABCDEFGHJKLMN"
        self.transport.forced_response = response(raw, 201)
        document = self.adapter.dispatch(str(uuid4()), self.request)
        self.assertEqual("ABCDEFGHJKLMN", document["merchant_id"])
        with self.assertRaises(AppError):
            verify_provider_order(
                document, self.expected, PROVIDER_ID, MERCHANT, {"CREATED"}
            )

    def test_malformed_fields_and_unsupported_money_are_rejected(self):
        for value in [
            "79",
            "79.0",
            "79.000",
            "079.00",
            "+79.00",
            "7.9e1",
            79.0,
            True,
            "-1.00",
            "0.00",
        ]:
            raw = self.wire()
            raw["purchase_units"][0]["amount"]["value"] = value
            with self.subTest(value=value), self.assertRaises(AppError):
                normalize_paypal_order(raw)
        for unit_change in [
            "multiple",
            "currency",
            "breakdown",
            "items",
            "quantity",
        ]:
            raw = self.wire()
            unit = raw["purchase_units"][0]
            if unit_change == "multiple":
                raw["purchase_units"].append(deepcopy(unit))
            elif unit_change == "currency":
                unit["amount"]["currency_code"] = "EUR"
            elif unit_change == "breakdown":
                unit["amount"]["breakdown"]["shipping"] = {
                    "currency_code": "USD",
                    "value": "1.00",
                }
            elif unit_change == "items":
                unit["items"].append(deepcopy(unit["items"][0]))
            else:
                unit["items"][0]["quantity"] = "01"
            with self.subTest(change=unit_change), self.assertRaises(AppError):
                normalize_paypal_order(raw)

    def test_sandbox_approval_url_is_exactly_bound_to_order(self):
        raw = self.wire()
        self.assertIsNone(sandbox_approval_url(raw))
        url = f"https://www.sandbox.paypal.com/checkoutnow?token={PROVIDER_ID}"
        raw["links"] = [{"rel": "approve", "method": "GET", "href": url}]
        self.assertEqual(url, sandbox_approval_url(raw))
        for bad in [
            url.replace("sandbox.", ""),
            url.replace("https:", "http:"),
            url.replace("paypal.com", "paypal.com.evil.test"),
            url.replace("www.sandbox", "user@www.sandbox"),
            url + "#x",
            url + "&token=OTHER",
            url + "&x=y",
            url.replace(PROVIDER_ID, "OTHER"),
            url.replace(".com/", ".com:443/"),
            url.replace("token=", "to%6ben="),
        ]:
            raw["links"][0]["href"] = bad
            with self.subTest(url=bad), self.assertRaises(AppError):
                sandbox_approval_url(raw)
        raw["links"] = [{"rel": "approve", "method": "GET", "href": url}] * 2
        with self.assertRaises(AppError):
            sandbox_approval_url(raw)

    def test_response_bounds_and_failures_never_retry(self):
        replies = [
            SandboxWireResponse(302, b"{}"),
            SandboxWireResponse(500, b"{}"),
            SandboxWireResponse(True, b"{}"),
            SandboxWireResponse(200, b'{"id":"A","id":"B"}'),
            SandboxWireResponse(200, b'{"id":"A","x":NaN}'),
            SandboxWireResponse(200, b"[" * 17 + b"]" * 17),
            SandboxWireResponse(200, b" " * (MAX_BODY_BYTES + 1)),
            SandboxWireResponse(200, b"\xff"),
            SandboxWireResponse(200, b'{"id":"A","x":"\\ud800"}'),
            RuntimeError("raw secret-like error"),
            object(),
        ]
        for reply in replies:
            self.transport.forced_response = reply
            count = len(self.transport.calls)
            with (
                self.subTest(reply=type(reply)),
                self.assertRaises(ProviderAmbiguity),
            ):
                self.adapter.dispatch(str(uuid4()), self.request)
            self.assertEqual(count + 1, len(self.transport.calls))

    def test_lookup_cannot_change_provider_identity(self):
        self.transport.forced_response = response(
            {"id": "DIFFERENT", "status": "CREATED"}
        )
        with self.assertRaises(ProviderAmbiguity):
            self.adapter.get(PROVIDER_ID)
        capture = self.adapter.prepare("capture", self.expected, PROVIDER_ID)
        with self.assertRaises(ProviderAmbiguity):
            self.adapter.dispatch(str(uuid4()), capture)

    def test_settings_are_frozen_and_bind_configuration(self):
        with self.assertRaises(FrozenInstanceError):
            self.adapter.merchant_id = "ABCDEFGHJKLMN"
        other = OfflinePayPalSandboxAdapter(self.transport, MERCHANT, 1.0)
        self.assertNotEqual(self.adapter.version, other.version)
        for timeout in [True, 0, -1, 31, float("nan"), float("inf"), "2"]:
            with self.subTest(timeout=timeout), self.assertRaises(AppError):
                OfflinePayPalSandboxAdapter(self.transport, MERCHANT, timeout)

    def test_merchant_id_uses_published_account_identifier_alphabet(self):
        for merchant in [
            "SYNTHETICDEMO",
            "ABCDEFGHJKLM1",
            "ABCDEFGHJKLM0",
            "abcdefghijklM",
            "short",
            True,
        ]:
            with self.subTest(merchant=merchant), self.assertRaises(AppError):
                OfflinePayPalSandboxAdapter(self.transport, merchant)

    def test_timeout_blocks_overlap_and_late_result_cannot_be_reused(self):
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        calls = []

        class SlowTransport:
            def send(self, *_args, **_kwargs):
                calls.append(1)
                entered.set()
                release.wait(5)
                finished.set()
                return response({"id": PROVIDER_ID, "status": "CREATED"})

        adapter = OfflinePayPalSandboxAdapter(SlowTransport(), MERCHANT, 0.03)
        started = time.monotonic()
        try:
            with self.assertRaises(ProviderAmbiguity):
                adapter.dispatch(str(uuid4()), self.request)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(entered.is_set())
            with self.assertRaises(ProviderAmbiguity):
                adapter.get(PROVIDER_ID)
            self.assertEqual([1], calls)
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
        with self.assertRaises(ProviderAmbiguity):
            adapter.get(PROVIDER_ID)
        self.assertEqual([1], calls)

    def test_nonempty_capture_collection_never_authorizes_another_capture(self):
        for status in ["PENDING", "COMPLETED", "DECLINED", "REFUNDED"]:
            raw = self.wire()
            raw["status"] = "APPROVED"
            raw["purchase_units"][0]["payments"] = {
                "captures": [
                    {
                        "id": CAPTURE_ID,
                        "status": status,
                        "amount": {"currency_code": "USD", "value": "79.00"},
                        "final_capture": True,
                    }
                ]
            }
            with self.subTest(status=status), self.assertRaises(AppError):
                verify_provider_order(
                    normalize_paypal_order(raw),
                    self.expected,
                    PROVIDER_ID,
                    MERCHANT,
                    {"APPROVED"},
                )

    def test_fixture_still_requires_its_complete_capture_collection(self):
        expected = {**self.expected, "provider_mode": "fixture"}
        document = {
            **expected,
            "provider_order_id": PROVIDER_ID,
            "status": "CREATED",
        }
        with self.assertRaises(AppError):
            verify_provider_order(
                document, expected, PROVIDER_ID, MERCHANT, {"CREATED"}
            )


class SandboxServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "app.sqlite3"
        self.store = Store(self.path)
        self.transport = MemoryTransport(self.path)
        self.adapter = OfflinePayPalSandboxAdapter(self.transport, MERCHANT)
        self.service = Service(self.store, payments=self.adapter)
        self.addCleanup(lambda: self.service.close())
        self.flow = Workflow(self.service)
        self.flow.analyze()
        self.flow.confirm()

    def operation(self, kind):
        with self.store.transaction() as connection:
            return dict(
                connection.execute(
                    "SELECT * FROM operations WHERE kind = ?", (kind,)
                ).fetchone()
            )

    def approve_and_verify(self):
        self.transport.document["status"] = "APPROVED"
        self.transport.document.pop("links", None)
        self.flow.action("verify")

    def test_full_fabricated_lifecycle_uses_durable_dispatch(self):
        self.flow.create()
        self.assertEqual("ORDER_CREATED", self.flow.checkout["state"])
        self.assertIsNone(self.flow.checkout["order"]["approval_url"])
        self.approve_and_verify()
        self.assertEqual("SERVER_RECHECKED", self.flow.checkout["state"])
        self.flow.action("capture")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        self.assertEqual(CAPTURE_ID, self.flow.checkout["order"]["capture_id"])
        create, capture = self.operation("orders"), self.operation("capture")
        self.assertNotEqual(create["operation_id"], capture["operation_id"])
        self.assertEqual(
            create["upstream_payload"], self.transport.calls[0][1].body
        )
        self.assertEqual(
            create["operation_id"],
            self.transport.calls[0][2]["PayPal-Request-Id"],
        )
        self.assertEqual(
            capture["operation_id"],
            self.transport.calls[-1][2]["PayPal-Request-Id"],
        )
        self.assertEqual("SUCCEEDED", capture["status"])
        self.assertEqual(4, len(self.transport.calls))
        self.flow.action("capture")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        self.assertEqual(4, len(self.transport.calls))

    def test_browser_idempotency_does_not_become_provider_identity(self):
        browser_key = str(uuid4())
        body = self.flow.create_body()
        self.flow.create(browser_key)
        first = self.operation("orders")
        self.assertNotEqual(browser_key, first["operation_id"])
        with self.assertRaises(AppError) as caught:
            self.service.mutate(
                self.flow.sid, "orders", body, idempotency_key=browser_key
            )
        self.assertEqual("STALE_REVISION", caught.exception.code)
        body["expected_revision"] = self.flow.result["revision"]
        self.service.mutate(
            self.flow.sid, "orders", body, idempotency_key=browser_key
        )
        self.assertEqual(1, len(self.transport.calls))
        self.assertEqual(first, self.operation("orders"))

    def test_incomplete_create_keeps_id_and_get_reconciles_without_post(self):
        self.transport.incomplete = True
        self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(
            PROVIDER_ID, self.flow.checkout["order"]["provider_order_id"]
        )
        self.flow.action("reconcile")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.transport.incomplete = False
        self.flow.action("reconcile")
        self.assertEqual("ORDER_CREATED", self.flow.checkout["state"])
        self.assertEqual(
            ["POST", "GET", "GET"], [c[1].method for c in self.transport.calls]
        )

    def test_create_response_loss_never_manufactures_id_or_replays(self):
        self.transport.fail_after_effect = True
        self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertIsNone(self.flow.checkout["order"]["provider_order_id"])
        for _ in range(2):
            self.flow.action("reconcile")
        self.assertEqual(1, len(self.transport.calls))
        self.assertEqual(
            "CREATE_OUTCOME_UNKNOWN",
            self.flow.checkout["order"]["reconciliation_code"],
        )
        self.assertNotIn("Private raw", canonical(self.operation("orders")))

    def test_existing_remote_capture_blocks_verification_and_another_post(self):
        self.flow.create()
        self.transport.document["status"] = "APPROVED"
        self.transport.document["purchase_units"][0]["payments"] = {
            "captures": [
                {
                    "id": CAPTURE_ID,
                    "status": "PENDING",
                    "amount": {"currency_code": "USD", "value": "79.00"},
                    "final_capture": True,
                }
            ]
        }
        self.flow.action("verify")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        with self.assertRaises(AppError):
            self.flow.action("capture")
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_malformed_create_facts_preserve_valid_identity_for_reconcile(self):
        wire = {
            "id": PROVIDER_ID,
            "status": "CREATED",
            "purchase_units": [
                {"amount": {"currency_code": "USD", "value": "bad"}}
            ],
        }
        self.transport.forced_response = response(wire, 201)
        self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(
            PROVIDER_ID, self.flow.checkout["order"]["provider_order_id"]
        )
        self.transport.forced_response = response(wire)
        self.flow.action("reconcile")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual("GET", self.transport.calls[-1][1].method)
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_hostile_approval_link_retains_only_identity_and_no_url(self):
        self.transport.forced_response = response(
            {
                "id": PROVIDER_ID,
                "status": "CREATED",
                "links": [
                    {
                        "rel": "approve",
                        "method": "GET",
                        "href": "https://www.paypal.com/checkoutnow?token="
                        + PROVIDER_ID,
                    }
                ],
            },
            201,
        )
        self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(
            PROVIDER_ID, self.flow.checkout["order"]["provider_order_id"]
        )
        self.assertIsNone(self.flow.checkout["order"]["approval_url"])
        self.assertNotIn("paypal.com", canonical(self.operation("orders")))

    def test_completed_response_missing_capture_details_stays_unknown(self):
        self.flow.create()
        self.approve_and_verify()
        # A complete preflight GET is followed by an incomplete capture reply.
        original_send = self.transport.send

        class CaptureReplyMissing:
            def send(_self, endpoint, request, headers, *, timeout_seconds):
                reply = original_send(
                    endpoint, request, headers, timeout_seconds=timeout_seconds
                )
                if request.method == "POST":
                    raw = json.loads(reply.body)
                    raw["purchase_units"][0].pop("payments")
                    return response(raw, 201)
                return reply

        self.service.payments = OfflinePayPalSandboxAdapter(
            CaptureReplyMissing(), MERCHANT
        )
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual("UNKNOWN", self.operation("capture")["status"])

    def test_capture_response_loss_same_order_get_resolves_without_replay(self):
        self.flow.create()
        self.approve_and_verify()
        self.transport.fail_after_effect = True
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.transport.fail_after_effect = False
        self.flow.action("reconcile")
        self.assertEqual("COMPLETED", self.flow.checkout["state"])
        self.assertEqual(
            2, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_pending_capture_stays_unknown(self):
        self.flow.create()
        self.approve_and_verify()
        self.transport.capture_status = "PENDING"
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.flow.action("reconcile")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(
            2, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_incomplete_approved_lookup_sends_no_capture(self):
        self.flow.create()
        self.approve_and_verify()
        del self.transport.document["purchase_units"][0]["payee"]
        self.flow.action("capture")
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        self.assertEqual(
            1, sum(c[1].method == "POST" for c in self.transport.calls)
        )

    def test_worker_start_failure_is_sanitized_and_never_dispatches(self):
        with patch(
            "cartreadback_app.paypal_sandbox.threading.Thread.start",
            side_effect=RuntimeError("Private raw worker resource error"),
        ):
            self.flow.create()
        self.assertEqual("PAYMENT_UNKNOWN", self.flow.checkout["state"])
        operation = self.operation("orders")
        self.assertEqual("UNKNOWN", operation["status"])
        self.assertEqual("PROVIDER_OUTCOME_UNKNOWN", operation["error_code"])
        self.assertNotIn("Private raw", canonical(operation))
        self.assertEqual([], self.transport.calls)
        with self.assertRaises(ProviderAmbiguity):
            self.adapter.get(PROVIDER_ID)
        self.assertEqual([], self.transport.calls)

    def test_defaults_stay_fixture_no_sandbox_runtime_gate(self):
        self.service.close()
        self.service = Service(self.store)
        self.assertIsInstance(self.service.payments, FixturePaymentAdapter)
        self.assertEqual("fixture", self.service.payments.mode)
