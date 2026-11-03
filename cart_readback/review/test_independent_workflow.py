"""Independent no-network probes of money, ownership and recovery boundaries."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from cartreadback_app.inference import FixtureInferenceAdapter
from cartreadback_app.payments import FixturePaymentAdapter
from cartreadback_app.service import Service
from cartreadback_app.storage import Store
from cartreadback_app.validation import AppError, canonical, text_hash


class IndependentWorkflowTests(unittest.TestCase):
    """Own fresh databases and inputs; never call a real payment provider."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "review.sqlite3")
        self.service = Service(self.store)
        self.sid = self.store.session(None)[0]["sid"]

    def view(self):
        return self.service.bootstrap(self.sid)

    def act(self, action, fields=None, key=None, order_id=None):
        current = self.view()
        body = {"expected_revision": current["revision"], **(fields or {})}
        if action != "analyze":
            body.setdefault(
                "snapshot_hash", current["checkout"]["snapshot_hash"]
            )
        if (
            order_id is None
            and current["checkout"]
            and current["checkout"]["order"]
        ):
            order_id = current["checkout"]["order"]["order_id"]
        return self.service.mutate(
            self.sid,
            action,
            body,
            order_id,
            key or (str(uuid4()) if action in {"orders", "capture"} else None),
        )

    def analyze(self, product=None, choices=None):
        product = product or self.view()["catalog"][0]
        return self.act(
            "analyze",
            {
                "sku_id": product["sku_id"],
                "conditions": choices
                or [{"kind": "layout", "value": "UK_QWERTY"}],
            },
        )

    def confirm(self):
        checkout = self.view()["checkout"]
        return self.act(
            "confirm",
            {
                "review_id": checkout["review_id"],
                "confirmed_sku_id": checkout["sku_id"],
                "confirmed_condition_ids": [
                    c["condition_id"] for c in checkout["conditions"]
                ],
                "acknowledged_unknown_ids": [
                    r["condition_id"]
                    for r in checkout["results"]
                    if r["status"] == "unknown"
                ],
                "acknowledged_conflict_ids": [
                    r["condition_id"]
                    for r in checkout["results"]
                    if r["status"] == "conflict"
                ],
            },
        )

    def create(self):
        checkout = self.view()["checkout"]
        return self.act(
            "orders",
            {
                "review_id": checkout["review_id"],
                "confirmation_id": checkout["confirmation_id"],
            },
        )

    def ready(self):
        self.analyze()
        self.confirm()
        self.create()
        self.act("fixture-approve")
        return self.act("verify")

    def capture(self, final=True):
        return self.act(
            "capture",
            {
                "confirmation_id": self.view()["checkout"]["confirmation_id"],
                "final_confirmation": final,
            },
        )

    def count(self, table):
        with self.store.connect() as connection:
            return connection.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]

    def test_happy_path_approval_is_not_completion_and_capture_is_explicit(
        self,
    ):
        self.ready()
        self.assertEqual("SERVER_RECHECKED", self.view()["checkout"]["state"])
        for false_intent in (False, 1, "true", None):
            with self.subTest(intent=false_intent), self.assertRaises(AppError):
                self.capture(false_intent)
        self.assertEqual("COMPLETED", self.capture()["checkout"]["state"])
        self.assertEqual(2, self.count("operations"))

    def test_unknown_requires_individual_ack_and_remains_unknown(self):
        product = next(
            p
            for p in self.view()["catalog"]
            if "unknown" in p["baseline"]["included_cable"]
        )
        self.analyze(
            product, [{"kind": "included_cable", "value": "any cable"}]
        )
        checkout = self.view()["checkout"]
        with self.assertRaises(AppError):
            self.act(
                "confirm",
                {
                    "review_id": checkout["review_id"],
                    "confirmed_sku_id": checkout["sku_id"],
                    "confirmed_condition_ids": ["c1"],
                    "acknowledged_unknown_ids": [],
                    "acknowledged_conflict_ids": [],
                },
            )
        self.confirm()
        self.assertEqual(
            "unknown", self.view()["checkout"]["results"][0]["status"]
        )

    def test_new_review_rejects_old_snapshot_and_confirmation(self):
        self.analyze()
        old = self.confirm()["checkout"]
        self.analyze(self.view()["catalog"][1])
        with self.assertRaises(AppError):
            self.act(
                "orders",
                {
                    "review_id": old["review_id"],
                    "snapshot_hash": old["snapshot_hash"],
                    "confirmation_id": old["confirmation_id"],
                },
            )
        self.assertEqual(0, self.count("operations"))

    def test_changed_source_or_price_cannot_capture_stale_consent(self):
        self.ready()
        product = deepcopy(self.view()["catalog"][0])
        product["price_minor"] += 100
        product["source"]["text"] += "\nNew source revision."
        product["source"]["revision"] += 1
        product["source"]["sha256"] = text_hash(product["source"]["text"])
        self.store.replace_product(product)
        with self.assertRaises(AppError):
            self.capture()
        self.assertEqual(1, self.count("operations"))

    def test_model_identity_change_invalidates_confirmation(self):
        self.analyze()
        self.confirm()
        adapter = FixtureInferenceAdapter()
        adapter.metadata = {
            **adapter.metadata,
            "prompt_version": "independent-revision",
        }
        self.service = Service(self.store, inference=adapter)
        with self.assertRaises(AppError):
            self.create()
        self.assertEqual(0, self.count("operations"))

    def test_foreign_owner_cannot_approve_or_capture_known_order(self):
        self.ready()
        checkout = self.view()["checkout"]
        foreign = self.store.session(None)[0]["sid"]
        for action in ("fixture-approve", "verify", "capture", "reconcile"):
            body = {
                "expected_revision": 0,
                "snapshot_hash": checkout["snapshot_hash"],
            }
            if action == "capture":
                body.update(
                    confirmation_id=checkout["confirmation_id"],
                    final_confirmation=True,
                )
            with self.subTest(action=action), self.assertRaises(AppError):
                self.service.mutate(
                    foreign,
                    action,
                    body,
                    checkout["order"]["order_id"],
                    str(uuid4()),
                )
        self.assertEqual(1, self.count("operations"))

    def test_remote_item_money_merchant_and_binding_mismatch_block_capture(
        self,
    ):
        mutations = [
            lambda d: d.update(merchant_id="another-merchant"),
            lambda d: d.update(provider_mode="sandbox"),
            lambda d: d.update(custom_id="old-snapshot"),
            lambda d: d.update(reference_id="another-order"),
            lambda d: d.update(amount_minor=True),
            lambda d: d.update(amount_minor=float(d["amount_minor"])),
            lambda d: d.update(currency="EUR"),
            lambda d: d["items"][0].update(sku_id="different-sku"),
            lambda d: d["items"][0].update(quantity=2),
            lambda d: d.pop("items"),
        ]
        for index, mutate in enumerate(mutations):
            if index:
                self.setUp()
            self.ready()
            checkout = self.view()["checkout"]
            provider_id = checkout["order"]["provider_order_id"]
            with self.store.connect() as connection:
                original = json.loads(
                    connection.execute(
                        "SELECT document FROM fixture_provider_orders"
                    ).fetchone()[0]
                )
            changed = deepcopy(original)
            mutate(changed)
            with self.store.transaction() as connection:
                connection.execute(
                    "UPDATE fixture_provider_orders SET document = ? WHERE provider_order_id = ?",
                    (canonical(changed), provider_id),
                )
            with self.subTest(case=index):
                try:
                    result = self.capture()
                except AppError:
                    pass
                else:
                    self.assertEqual(
                        "PAYMENT_UNKNOWN", result["checkout"]["state"]
                    )
                    self.assertEqual("ORDER_MISMATCH", result["error"]["code"])
            self.assertEqual(1, self.count("operations"))

    def test_capture_timeout_after_success_reconciles_after_service_restart(
        self,
    ):
        self.ready()
        self.service.payments = FixturePaymentAdapter(
            "capture_timeout_after_success"
        )
        self.assertEqual("PAYMENT_UNKNOWN", self.capture()["checkout"]["state"])
        self.service = Service(Store(self.store.path))
        self.assertEqual("PAYMENT_UNKNOWN", self.view()["checkout"]["state"])
        self.assertEqual(
            "COMPLETED", self.act("reconcile")["checkout"]["state"]
        )
        self.assertEqual(2, self.count("operations"))
        self.assertEqual(1, self.count("fixture_provider_orders"))

    def test_unresolved_capture_does_not_clear_on_still_approved_lookup(self):
        self.ready()
        self.service.payments = FixturePaymentAdapter(
            "capture_timeout_before_success"
        )
        self.assertEqual("PAYMENT_UNKNOWN", self.capture()["checkout"]["state"])
        self.service = Service(Store(self.store.path))
        self.assertEqual(
            "PAYMENT_UNKNOWN", self.act("reconcile")["checkout"]["state"]
        )
        with self.assertRaises(AppError):
            self.capture()
        with self.assertRaises(AppError):
            self.analyze()
        self.assertEqual(2, self.count("operations"))

    def test_stale_source_does_not_prevent_unknown_capture_reconciliation(self):
        self.ready()
        self.service.payments = FixturePaymentAdapter(
            "capture_timeout_after_success"
        )
        self.assertEqual("PAYMENT_UNKNOWN", self.capture()["checkout"]["state"])
        product = deepcopy(self.view()["catalog"][0])
        product["source"]["text"] += "\nLater catalog description."
        product["source"]["revision"] += 1
        product["source"]["sha256"] = text_hash(product["source"]["text"])
        self.store.replace_product(product)
        public = self.view()["checkout"]
        self.assertTrue(public["stale"])
        self.assertIsNone(public["confirmation_id"])
        self.assertEqual(
            "COMPLETED", self.act("reconcile")["checkout"]["state"]
        )
        self.assertEqual(2, self.count("operations"))

    def test_create_timeout_cannot_start_replacement_order(self):
        self.analyze()
        self.confirm()
        self.service.payments = FixturePaymentAdapter(
            "create_timeout_after_success"
        )
        unknown = self.create()["checkout"]
        self.assertEqual("PAYMENT_UNKNOWN", unknown["state"])
        self.assertTrue(unknown["order"]["order_id"])
        self.assertIsNone(unknown["order"]["provider_order_id"])
        self.act("reconcile")
        with self.assertRaises(AppError):
            self.create()
        self.assertEqual(1, self.count("operations"))
        self.assertEqual(1, self.count("fixture_provider_orders"))

    def test_missing_provider_id_is_unknown_not_created(self):
        class MissingOrderId(FixturePaymentAdapter):
            def create(self, connection, request_id, expected):
                document = super().create(connection, request_id, expected)
                document["provider_order_id"] = None
                return document

        self.analyze()
        self.confirm()
        self.service.payments = MissingOrderId()
        result = self.create()["checkout"]
        self.assertEqual("PAYMENT_UNKNOWN", result["state"])
        self.assertIsNone(result["order"]["provider_order_id"])
        self.assertEqual(1, self.count("operations"))

    def test_process_failure_after_create_reservation_recovers_unknown(self):
        class InterruptedCreate(FixturePaymentAdapter):
            def create(self, connection, request_id, expected):
                raise RuntimeError(
                    "Synthetic worker interruption before side effect"
                )

        self.analyze()
        self.confirm()
        self.service.payments = InterruptedCreate()
        with self.assertRaises(RuntimeError):
            self.create()
        self.assertEqual(
            "ORDER_CREATE_PENDING", self.view()["checkout"]["state"]
        )
        self.assertEqual(1, self.count("operations"))
        self.service = Service(Store(self.store.path))
        self.assertEqual("PAYMENT_UNKNOWN", self.view()["checkout"]["state"])
        with self.assertRaises(AppError):
            self.create()
        self.assertEqual(0, self.count("fixture_provider_orders"))

    def test_process_failure_after_capture_reservation_recovers_unknown(self):
        class InterruptedCapture(FixturePaymentAdapter):
            def capture(self, connection, provider_order_id, request_id):
                raise RuntimeError(
                    "Synthetic worker interruption before side effect"
                )

        self.ready()
        self.service.payments = InterruptedCapture()
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertEqual("CAPTURE_PENDING", self.view()["checkout"]["state"])
        self.service = Service(Store(self.store.path))
        self.assertEqual("PAYMENT_UNKNOWN", self.view()["checkout"]["state"])
        self.assertEqual(
            "PAYMENT_UNKNOWN", self.act("reconcile")["checkout"]["state"]
        )
        with self.assertRaises(AppError):
            self.capture()
        self.assertEqual(2, self.count("operations"))

    def test_concurrent_create_and_capture_have_one_business_operation_each(
        self,
    ):
        self.analyze()
        checkout = self.confirm()["checkout"]
        body = {
            "expected_revision": self.view()["revision"],
            "snapshot_hash": checkout["snapshot_hash"],
            "review_id": checkout["review_id"],
            "confirmation_id": checkout["confirmation_id"],
        }

        def attempt(action, payload, order_id=None):
            try:
                self.service.mutate(
                    self.sid, action, payload, order_id, str(uuid4())
                )
                return "accepted"
            except AppError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(lambda _: attempt("orders", body), range(4))
            )
        self.assertEqual(1, results.count("accepted"))
        self.act("fixture-approve")
        checkout = self.act("verify")["checkout"]
        body = {
            "expected_revision": self.view()["revision"],
            "snapshot_hash": checkout["snapshot_hash"],
            "confirmation_id": checkout["confirmation_id"],
            "final_confirmation": True,
        }
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(
                    lambda _: attempt(
                        "capture", body, checkout["order"]["order_id"]
                    ),
                    range(4),
                )
            )
        self.assertEqual(1, results.count("accepted"))
        self.assertEqual(2, self.count("operations"))
        self.assertEqual(1, self.count("fixture_provider_orders"))


if __name__ == "__main__":
    unittest.main()
